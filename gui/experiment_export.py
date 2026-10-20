"""Background serialization and isolated rendering, with cancellable staging."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from PySide6.QtCore import QObject, Signal, Slot
from config.default_params import BASE_DIR
from core.experiment_bundle import dump_json, _publish_directory, _staging_directory


class ExportCancelled(Exception):
    pass


class ExperimentExportWorker(QObject):
    progress = Signal(int, int, str)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, library, record, name):
        super().__init__()
        self.library, self.record, self.name = Path(library), record, name
        self._cancelled = threading.Event()

    def cancel(self):
        # Invoked directly on the GUI thread; queued slots would be blocked
        # while run() coordinates the child process.
        self._cancelled.set()

    @Slot()
    def run(self):
        try:
            self.library.mkdir(parents=True, exist_ok=True)
            self.progress.emit(0, 0, '正在后台准备完整实验快照…')
            with _staging_directory(self.library) as temporary:
                root = Path(temporary)
                dump_json(root/'input.json', self.record, already_safe=True)
                if self._cancelled.is_set():
                    raise ExportCancelled()
                command = ([sys.executable, '--export-worker'] if getattr(sys, 'frozen', False)
                           else [sys.executable, '-m', 'core.export_process'])
                command += ['--input', str(root/'input.json'), '--library', str(self.library), '--name', self.name]
                environment = dict(os.environ, MPLBACKEND='Agg', PYTHONIOENCODING='utf-8',
                    OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
                with (root/'progress.jsonl').open('wb') as output, (root/'stderr.txt').open('wb') as errors:
                    process = subprocess.Popen(command, cwd=BASE_DIR, env=environment,
                        stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    success, failure = None, None
                    pending = ''
                    try:
                        with (root/'progress.jsonl').open(encoding='ascii') as updates:
                            while True:
                                ended = process.poll() is not None
                                pending += updates.read()
                                latest_progress = None
                                while '\n' in pending:
                                    line, pending = pending.split('\n', 1)
                                    message = json.loads(line)
                                    if message['type'] == 'progress':
                                        latest_progress = (message['done'], message['total'], message['stage'])
                                    elif message['type'] == 'ready':
                                        success = message['stem']
                                    elif message['type'] == 'error':
                                        failure = message['message']
                                if latest_progress:
                                    self.progress.emit(*latest_progress)
                                if ended:
                                    break
                                if self._cancelled.wait(.05):
                                    raise ExportCancelled()
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                    if process.returncode != 0 or not success:
                        detail = (root/'stderr.txt').read_text(encoding='utf-8', errors='replace')[-2000:]
                        raise RuntimeError(failure or f'导出进程异常退出（{process.returncode}）：{detail}')
                    if self._cancelled.is_set():
                        raise ExportCancelled()
                    target = _publish_directory(root/'experiment', self.library, success)
                    self.succeeded.emit(str(target))
        except ExportCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')
        finally:
            self.record = None
            self.finished.emit()
