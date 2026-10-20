"""Headless, disposable export process. Called only by the GUI coordinator."""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--library', required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args(argv)
    os.environ['MPLBACKEND'] = 'Agg'
    from core.experiment_bundle import _validate_record, _experiment_stem, _write_experiment_files
    def send(data):
        print(json.dumps(data, ensure_ascii=True), flush=True)
    try:
        source = Path(args.input).resolve()
        library = Path(args.library).resolve()
        # The coordinator owns this staging directory, including on cancellation
        # or a native renderer crash that bypasses Python exception handling.
        if source.parent.parent != library or not source.parent.name.startswith('.cpp_export_'):
            raise ValueError('导出临时目录须位于实验库内')
        with source.open(encoding='utf-8') as stream:
            record = _validate_record(json.load(stream))
        timestamp = datetime.now().astimezone()
        stem = _experiment_stem(args.name, timestamp)
        record['experiment_name'] = args.name.strip()
        record['exported_at'] = timestamp.isoformat()
        staged = source.parent/'experiment'
        staged.mkdir()
        _write_experiment_files(staged, record,
            lambda done, total, stage: send(dict(type='progress', done=done, total=total, stage=stage)))
        # The coordinator publishes only after this process exits cleanly.
        send(dict(type='ready', stem=stem))
        return 0
    except Exception as exc:
        import traceback
        send(dict(type='error', message=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
