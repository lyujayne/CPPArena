"""Thread-local cancellation, deadline and throttled algorithm-stage reporting."""
from contextlib import contextmanager
from contextvars import ContextVar
import time


class ExperimentCancelled(Exception):
    pass


_current = ContextVar('algorithm_execution_control', default=None)


@contextmanager
def execution_context(cancelled, report=None, timeout=None):
    state = {'cancelled': cancelled, 'report': report, 'last_report': 0.,
             'deadline': time.monotonic()+timeout if timeout is not None else None}
    token = _current.set(state)
    try:
        checkpoint()
        yield
    finally:
        _current.reset(token)


def checkpoint(stage=None, current=None, total=None, force=False):
    state = _current.get()
    if state is None:
        return
    if state['cancelled']():
        raise ExperimentCancelled('实验已终止')
    now = time.monotonic()
    if state['deadline'] is not None and now >= state['deadline']:
        raise TimeoutError('当前算法超过配置的运行时间上限')
    if stage and state['report'] and (force or now-state['last_report'] >= .15):
        suffix = f' {current}/{total}' if total is not None else ''
        scope = state.get('scope', '')
        state['report']((scope+'：' if scope else '')+stage+suffix)
        state['last_report'] = now


@contextmanager
def progress_scope(label):
    state = _current.get()
    if state is None:
        yield
        return
    previous = state.get('scope', '')
    state['scope'] = label
    try:
        yield
    finally:
        state['scope'] = previous
