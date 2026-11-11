"""功能：为桌面批次提供可停止的网络等待、取消检查和暂存清理。
实现：后台批次绑定独立取消信号，网络调用可放弃等待，最终发布前锁定取消状态。
输入：界面停止请求、网络函数和本批新建目录；输出：正常结果或取消异常。
依赖：Python 标准库。
"""
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import Future
from pathlib import Path
import shutil
from threading import Event, Lock, Thread
import time


class GenerationCancelled(Exception):
    """用户停止了本次生成。"""


_current = ContextVar("generation_control", default=None)


class GenerationControl:
    def __init__(self):
        self.stopped = Event()
        self._lock = Lock()
        self._sealed = False
        self._batch_dir = None

    def cancel(self):
        with self._lock:
            if self._sealed:
                return False
            self.stopped.set()
            return True

    def can_cancel(self):
        with self._lock:
            return not self._sealed and not self.stopped.is_set()

    @contextmanager
    def activate(self):
        token = _current.set(self)
        try:
            checkpoint()
            yield
        finally:
            _current.reset(token)
            if self.stopped.is_set() and self._batch_dir is not None:
                path = self._batch_dir
                if path.is_dir() and path.resolve() == path:
                    shutil.rmtree(path)


def track_batch(directory: Path):
    """只登记管线刚创建、归属本批次的目录。"""
    control = _current.get()
    if control is not None:
        path = directory.parent.resolve() / directory.name
        if path.resolve() == path:
            control._batch_dir = path


def checkpoint():
    control = _current.get()
    if control is not None and control.stopped.is_set():
        raise GenerationCancelled()


def seal():
    """在不可中断的发布阶段前关闭停止入口，避免停止与发布同时生效。"""
    control = _current.get()
    if control is not None:
        with control._lock:
            checkpoint()
            control._sealed = True


def wait(seconds):
    control = _current.get()
    if control is None:
        time.sleep(seconds)
    elif control.stopped.wait(seconds):
        raise GenerationCancelled()


def network_call(fn, *args):
    """可放弃等待一个网络响应，调用线程不得写批次文件或启动后续流程。"""
    control = _current.get()
    if control is None:
        return fn(*args)
    checkpoint()
    outcome = Future()
    done = Event()

    def request():
        try:
            if control.stopped.is_set():
                raise GenerationCancelled()
            outcome.set_result(fn(*args))
        except BaseException as error:
            outcome.set_exception(error)
        finally:
            done.set()

    Thread(target=request, daemon=True).start()
    while not done.wait(0.05):
        checkpoint()
    checkpoint()
    return outcome.result()
