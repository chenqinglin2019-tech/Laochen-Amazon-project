"""Keep the computer awake while a pipeline run works (r5d4).

r5d4 real run B0FSJBDTF2_US_20261012: between 12:51 and 13:00 UTC the wall clock ran about five minutes ahead of
the process clock and four model sessions ended with "stream disconnected" / "Connection failed" - the Mac slept.
A run now asks the operating system not to idle-sleep while it works and releases the request when it ends
(delivered, checkpoint or failure):

* macOS: ``caffeinate -i -s -w <pid>`` (no idle sleep; no system sleep on mains power; exits with the run);
* Windows: ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`` on the pipeline thread;
* anything else: nothing.

The display may still sleep. A closed lid on battery can still force sleep; nothing here can prevent that. A failure
to keep awake never fails a run.

r5d8: on macOS the request is checked once with ``pmset -g assertions`` (readable without privileges): 'caffeinate'
means the system lists it, 'caffeinate_unconfirmed' that it does not (or the check could not run), 'caffeinate_exited'
that caffeinate ended at once. The run reports actual sleep separately (run_pipeline.note_sleep).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    """Context manager; ``mode`` says what was done ('caffeinate', 'windows', 'none' or 'unavailable')."""

    def __init__(self, *, platform=None, popen=subprocess.Popen, which=shutil.which, kernel32=None, pid=None,
                 check=None):
        self.platform = platform or sys.platform
        self.popen, self.which, self.kernel32 = popen, which, kernel32
        self.check = check if check is not None else _assertions
        self.pid = pid or os.getpid()
        self.process = None
        self.mode = 'none'

    def __enter__(self):
        try:
            if self.platform == 'darwin':
                binary = self.which('caffeinate')
                if binary:
                    self.process = self.popen([binary, '-i', '-s', '-w', str(self.pid)],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.mode = self._confirm()
                else:
                    self.mode = 'unavailable'
            elif self.platform.startswith('win'):
                kernel32 = self.kernel32
                if kernel32 is None:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                if kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
                    self.kernel32 = kernel32
                    self.mode = 'windows'
                else:
                    self.mode = 'unavailable'
        except Exception:                      # keeping awake is an aid, never a reason to fail a run
            self.process, self.mode = None, 'unavailable'
        return self

    def _confirm(self):
        try:
            time.sleep(0.3)
            if self.process.poll() is not None:
                return 'caffeinate_exited'
            listed = self.check() or ''
        except Exception:
            return 'caffeinate_unconfirmed'
        return 'caffeinate' if 'pid %d(caffeinate)' % self.process.pid in listed else 'caffeinate_unconfirmed'

    def __exit__(self, *exc):
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except Exception:
                    self.process.kill()
            if self.mode == 'windows' and self.kernel32 is not None:
                self.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass
        return False


def _assertions():
    pmset = shutil.which('pmset') or '/usr/bin/pmset'
    return subprocess.run([pmset, '-g', 'assertions'], capture_output=True, text=True, timeout=5).stdout
