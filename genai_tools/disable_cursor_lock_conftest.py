"""Temporary: disable the cursor lock and run the thread-safety test.

Used to verify the regression test actually catches the bug. Deletes itself
after one use is fine — leaving in genai_tools/ per project rules.
"""
import threading


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def acquire(self, blocking=True, timeout=None):
        return True

    def release(self):
        pass


def pytest_configure(config):
    import database.database as ddb

    _orig_init = ddb.PostgresDB.__init__

    def _patched(self, *a, **kw):
        _orig_init(self, *a, **kw)
        self._cursor_lock = _NullLock()

    ddb.PostgresDB.__init__ = _patched
