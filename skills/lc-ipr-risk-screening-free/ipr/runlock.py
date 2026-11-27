"""一单一个进程。这里管两件事：
1. 同一个任务目录不让两个进程同时跑（两边都写状态文件会写乱）。
2. 知道这台电脑上此刻还有没有别的单在跑：有的话，这一单的时间线放宽（需求 R-010：两单同时跑时每单 12 分钟）。
做法：在任务目录和一个本机公用的目录里各放一个小文件，里面是进程号；每到一步就碰一下文件（心跳）。
进程没了、或者太久没有心跳的，算已经停了。"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

LOCK_NAME = ".running"          # 任务目录里的记号文件
STALE_SECONDS = 30 * 60         # 这么久没有心跳就算停了
BEAT_SECONDS = 60               # 跑着的时候后台每隔这么久打一次心跳（AI 会话排队、限流等待可能很久，不能只靠每一步开头打）
FRESH_SECONDS = 60              # 记号文件建好不到这么久、内容还读不出来的：当它正在写，不动它
ENTRY_NAME = re.compile(r"\d+-[0-9a-f]{8}\.json")  # 公用目录里自己登记的文件长这样
REGISTRY_ENV = "LC_IPR_RUN_DIR"  # 测试时把公用目录指到临时目录


class Busy(ValueError):
    """这个任务目录正有另一个进程在跑。"""


def registry() -> Path:
    override = os.environ.get(REGISTRY_ENV)
    return Path(override) if override else Path(tempfile.gettempdir()) / "lc-ipr-running"


def alive(pid) -> bool:
    """这个进程号现在还有没有进程。"""
    if not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid < 2 ** 31:
        return False
    if os.name == "nt":  # Windows 上不能用 os.kill(pid, 0)：那会把进程杀掉
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # 拒绝访问：进程在，只是不让看
        code = wintypes.DWORD()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def read(path: Path):
    try:
        info = json.loads(Path(path).read_text(encoding="utf-8"))
        return info if isinstance(info, dict) else None
    except (OSError, ValueError):
        return None


def live(path: Path) -> bool:
    """这个记号文件背后的进程是不是还在跑。"""
    info = read(path)
    try:
        age = time.time() - Path(path).stat().st_mtime
    except OSError:
        return False
    if not info:
        return age < FRESH_SECONDS  # 刚建好、内容还没写完：当它在跑
    return age < STALE_SECONDS and alive(info.get("pid"))


def holder(task_dir) -> dict:
    """任务目录正被谁占着；没人占返回空字典。"""
    path = Path(task_dir) / LOCK_NAME
    return (read(path) or {}) if live(path) else {}


class RunLock:
    def __init__(self, task_dir, count: bool = True):
        """count=False：只锁任务目录，不算进"这台电脑上正在跑的单"（演示不开 AI 会话，不算）。"""
        self.path = Path(task_dir) / LOCK_NAME
        self.count = count
        self.token = uuid.uuid4().hex
        self.entry = registry() / ("%d-%s.json" % (os.getpid(), self.token[:8]))
        self.held = False
        self._stop = threading.Event()

    def _write(self, path: Path) -> None:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "token": self.token, "started": time.strftime("%Y-%m-%d %H:%M:%S")}, stream)

    def acquire(self) -> "RunLock":
        for _attempt in (1, 2):
            try:
                self._write(self.path)
                break
            except FileExistsError:
                seen = read(self.path) or {}
                if live(self.path):
                    raise Busy("这个任务正在另一个窗口里跑（从 %s 开始，进程号 %s）。等它结束再续跑，或者换一个任务目录。"
                               % (seen.get("started", "刚才"), seen.get("pid", "未知")))
                # 上次没收拾干净（比如窗口被直接关掉）：清掉再占。先改成一个独一无二的名字，看清挪开的确实是刚才判定过期的那个再删——
                # 两个进程同时来清时，后到的那个挪开的会是先到的刚建好的新记号：放回去，自己退出
                aside = self.path.with_name("%s.%s.old" % (LOCK_NAME, self.token[:8]))
                try:
                    os.rename(str(self.path), str(aside))
                except OSError:
                    continue  # 已经被别人挪走了：再试一次，这回多半会看到对方的新记号
                moved = read(aside) or {}
                try:
                    settled = time.time() - aside.stat().st_mtime > FRESH_SECONDS  # 改名不改文件时间：刚建好的新记号是"新"的
                except OSError:
                    settled = False
                # 挪开的得是刚才判定过期的那个：token 对得上；读不出 token 的（空文件）要确实放了很久才算
                if moved.get("token") != seen.get("token") or not (seen.get("token") or settled):
                    try:
                        if not self.path.exists():
                            os.rename(str(aside), str(self.path))
                    except OSError:
                        pass
                    raise Busy("这个任务刚刚被另一个窗口接着跑了。等它结束再续跑，或者换一个任务目录。")
                try:
                    aside.unlink()
                except OSError:
                    pass
        else:
            raise Busy("这个任务目录被占着，没法开跑。等一会儿再试，或者换一个任务目录。")
        self.held = True
        for leftover in self.path.parent.glob(LOCK_NAME + ".*.old"):  # 以前清理时没删掉的挪开文件：顺手清掉，任务目录里不留杂物
            try:
                leftover.unlink()
            except OSError:
                pass
        self._register()
        self._stop.clear()
        threading.Thread(target=self._keep_beating, name="ipr-heartbeat", daemon=True).start()
        return self

    def _register(self) -> None:
        if not self.count or not self.held:  # 已经收尾了就不再登记（后台那一下心跳可能正好赶在收尾之后）
            return
        try:
            self.entry.parent.mkdir(parents=True, exist_ok=True)
            self._write(self.entry)
        except FileExistsError:
            pass
        except OSError:
            self.count = False  # 公用目录写不了：只是没法知道有没有别的单在跑，不影响这一单

    def _keep_beating(self) -> None:
        while not self._stop.wait(BEAT_SECONDS):
            self.beat()

    def beat(self) -> None:
        """心跳：告诉别人这一单还在跑。"""
        if not self.held:
            return
        try:
            os.utime(str(self.path), None)
        except OSError:
            pass
        if self.count:
            try:
                os.utime(str(self.entry), None)
            except OSError:
                self._register()  # 登记被别的单当成过期的清掉了（比如电脑睡了一觉）：重新登记

    def others(self) -> int:
        """这台电脑上此刻还有几单在跑（不算自己）。顺手清掉已经停了的记号。"""
        if not self.count:
            return 0
        running = 0
        try:
            entries = list(self.entry.parent.glob("*.json"))
        except OSError:
            return 0
        for path in entries:
            if path == self.entry or not ENTRY_NAME.fullmatch(path.name):  # 不是自己这种登记文件的不碰
                continue
            if live(path):
                running += 1
            else:
                try:
                    if time.time() - path.stat().st_mtime > FRESH_SECONDS:  # 刚建好还没写完的不动
                        path.unlink()
                except OSError:
                    pass
        return running

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        self._stop.set()
        mine = read(self.path) or {}
        for path in ([self.path] if mine.get("token") == self.token else []) + ([self.entry] if self.count else []):
            try:
                path.unlink()
            except OSError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()
