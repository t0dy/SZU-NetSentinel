"""
SZU NetSentinel - 内存优化与后台轻量化运行支持
=============================================
在 Windows 平台下通过 CPython 垃圾回收与 Win32 psapi.EmptyWorkingSet API，
定期将后台常驻进程的工作集内存从 ~55MB 深度精简至 1MB~8MB，大幅降低系统资源占用。
"""

from __future__ import annotations

import gc
import sys


def trim_memory() -> None:
    """
    触发 Python 循环引用垃圾回收并通知 Windows 内核收缩进程工作集。
    非阻塞，安全捕获所有异常。
    """
    try:
        gc.collect()
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            h_proc = kernel32.GetCurrentProcess()
            psapi = ctypes.windll.psapi
            psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
            psapi.EmptyWorkingSet.restype = ctypes.c_int
            psapi.EmptyWorkingSet(h_proc)
    except Exception:
        pass
