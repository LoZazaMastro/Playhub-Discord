"""Read-only process identity for the plugin's private Windows client."""
import ctypes
import ntpath
import os
from ctypes import wintypes


def read(pid):
    if os.name != "nt" or type(pid) is not int or pid <= 0:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        return None
    try:
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        times = [wintypes.FILETIME() for _ in range(4)]
        if (kernel.WaitForSingleObject(handle, 0) != 258
                or not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length))
                or not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times))):
            return None
        birth = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
        return {"pid": pid, "birth": birth, "path": image.value}
    finally:
        kernel.CloseHandle(handle)


def parent_pid(pid):
    if os.name != "nt":
        return None
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if entry.pid == pid:
                return int(entry.parent)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return None
    finally:
        kernel.CloseHandle(snapshot)


def matches(identity, executable):
    if (not isinstance(identity, dict) or type(identity.get("pid")) is not int
            or type(identity.get("birth")) is not int or identity["birth"] <= 0
            or not isinstance(identity.get("path"), str)):
        return False
    expected = ntpath.normcase(ntpath.abspath(str(executable)))
    if ntpath.normcase(ntpath.abspath(identity["path"])) != expected:
        return False
    current = read(identity["pid"])
    return bool(current and current["birth"] == identity["birth"]
                and ntpath.normcase(ntpath.abspath(current["path"])) == expected)


def capture(pid, executable, parent):
    identity = read(pid)
    if identity and matches(identity, executable) and parent_pid(pid) == parent:
        return identity
    return None
