"""Start both frozen GUI entry points hidden, verify native titles, then close."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time
import psutil

root = Path(__file__).resolve().parents[1]
exe = root / 'dist' / 'CPPArena-v2.1.exe'
user32 = ctypes.windll.user32
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)


def check(arguments, expected):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    env = dict(os.environ)
    env.pop('QT_QPA_PLATFORM', None)
    process = subprocess.Popen([str(exe), *arguments], cwd=exe.parent, env=env, startupinfo=startup)
    tracked = set()
    found = []
    try:
        deadline = time.monotonic()+50
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Premature process exit: {process.returncode}')
            tracked = {process.pid} | {p.pid for p in psutil.Process(process.pid).children(recursive=True)}
            windows = []
            @callback_type
            def visit(handle, context):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                if pid.value in tracked:
                    title = ctypes.create_unicode_buffer(1024)
                    user32.GetWindowTextW(handle, title, 1024)
                    if title.value:
                        windows.append((handle, title.value))
                return True
            user32.EnumWindows(visit, 0)
            found = [(h, title) for h, title in windows if 'v2.1' in title and expected in title]
            if found:
                break
            time.sleep(.15)
        if not found:
            raise RuntimeError(f'Expected title not found; windows={windows}')
        # Give initialization/drawing a chance to complete after the title is set.
        time.sleep(1)
        if process.poll() is not None:
            raise RuntimeError('GUI exited during initialization')
        titles = [title for _, title in found]
        for handle, _ in found:
            user32.PostMessageW(handle, 0x0010, 0, 0)
        process.wait(timeout=10)
        if process.returncode != 0:
            raise RuntimeError(f'GUI closed with code {process.returncode}')
        return {'arguments': arguments, 'window_titles': titles, 'exit_code': process.returncode}
    finally:
        if process.poll() is None:
            for pid in tracked:
                try:
                    psutil.Process(pid).terminate()
                except psutil.NoSuchProcess:
                    pass
            process.wait(timeout=5)


if __name__ == '__main__':
    results = [check([], '覆盖路径规划'), check(['--history'], '历史实验平台')]
    target = root / 'verification' / 'v2.1' / 'executable_smoke.json'
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=True))
