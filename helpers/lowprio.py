# helpers/lowprio.py
#   vid_lock(key) : ek video ke liye ek hi download (same key pe doosra thread intezaar karta hai)
#   LowPrio()     : download/ffmpeg ko low CPU priority (nice) pe chalao, taaki VC ka audio na atke
import os
import threading
from contextlib import contextmanager

_guard = threading.Lock()
_locks: dict = {}  # key -> [RLock, refcount]


@contextmanager
def vid_lock(key):
    key = str(key)
    with _guard:
        ent = _locks.get(key)
        if ent is None:
            ent = _locks[key] = [threading.RLock(), 0]
        ent[1] += 1
    try:
        with ent[0]:
            yield
    finally:
        with _guard:
            ent[1] -= 1
            if ent[1] <= 0:
                _locks.pop(key, None)


class LowPrio:
    """with LowPrio(): ... -> is thread (aur uske bacche, jaise ffmpeg) ki niceness badha do, bahar aate hi wapas."""

    def __init__(self, nice: int = 10):
        self.nice = nice
        self._tid = None
        self._old = None

    def __enter__(self):
        try:
            self._tid = threading.get_native_id()
            self._old = os.getpriority(os.PRIO_PROCESS, self._tid)
            if self._old < self.nice:
                os.setpriority(os.PRIO_PROCESS, self._tid, self.nice)
            else:
                self._old = None
        except (AttributeError, OSError):
            self._old = None  # Windows / permission nahi -> chup-chaap skip
        return self

    def __exit__(self, *exc):
        if self._old is not None:
            try:
                os.setpriority(os.PRIO_PROCESS, self._tid, self._old)
            except (AttributeError, OSError):
                pass
        return False
