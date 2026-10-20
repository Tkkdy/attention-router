# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Foreground-window sampling and conservative V0 context hysteresis."""

from __future__ import annotations

import ctypes
import time
import subprocess
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


SAMPLE_ERRORS = frozenset({"WINDOW_CHANGED_DURING_SAMPLE", "FOREGROUND_UNAVAILABLE",
    "PROCESS_DISAPPEARED", "ACCESS_DENIED", "SAMPLER_INTERNAL_ERROR"})

class SamplingError(OSError):
    def __init__(self, category):
        self.category = category
        super().__init__(category)

def process_failure(code):
    return SamplingError("ACCESS_DENIED" if code == 5 else "PROCESS_DISAPPEARED" if code in {6, 87, 1168} else "FOREGROUND_UNAVAILABLE")


@dataclass(frozen=True)
class ForegroundSample:
    process: str
    title: str
    idle_seconds: float
    application: str | None = None
    site_marker: str | None = None


def foreground_application(executable: str) -> str | None:
    path = PureWindowsPath(executable)
    # Current Codex MSIX uses ChatGPT.exe. Its package identity distinguishes it
    # from the separate ChatGPT desktop app; an executable name alone cannot.
    if path.name.casefold() == "chatgpt.exe" and any(part.casefold().startswith("openai.codex_") for part in path.parts):
        return "codex_desktop"
    return "codex_desktop" if path.name.casefold() == "codex.exe" else None


class ContextDetector:
    def __init__(self, enter_seconds: float = 300, exit_seconds: float = 120) -> None:
        self.enter_seconds = enter_seconds
        self.exit_seconds = exit_seconds
        self.context = "IDLE"
        self._coding_since: float | None = None
        self._away_since: float | None = None

    def update(self, sample: ForegroundSample, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        coding_candidate = sample.process.casefold() in {"code.exe", "cursor.exe"}
        if coding_candidate:
            self._away_since = None
            self._coding_since = self._coding_since if self._coding_since is not None else now
            if now - self._coding_since >= self.enter_seconds:
                self.context = "CODING"
        else:
            self._coding_since = None
            if self.context == "CODING":
                self._away_since = self._away_since if self._away_since is not None else now
                if now - self._away_since >= self.exit_seconds:
                    self.context = "IDLE"
            else:
                self.context = "IDLE"
        return self.context


def read_site_marker(window):
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-File",
            str(Path(__file__).with_name("browser_site_marker.ps1")), "-WindowHandle", str(window)],
            capture_output=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW)
        return "chatgpt_web" if result.stdout.strip() == b"chatgpt_web" else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_foreground(*, read_title=True) -> ForegroundSample:
    """Read Windows foreground process/title/idle without third-party packages."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # Win64 handles are pointers; ctypes' default c_int return would truncate them.
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    window = user32.GetForegroundWindow()
    if not window:
        raise SamplingError("FOREGROUND_UNAVAILABLE")
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
    if not process_id.value:
        raise SamplingError("PROCESS_DISAPPEARED")
    process = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process:
        raise process_failure(kernel32.GetLastError())
    process_name = ""
    application = None
    if process:
        try:
            size = wintypes.DWORD(32768)
            path_buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(process, 0, path_buffer, ctypes.byref(size)):
                process_name = Path(path_buffer.value).name
                application = foreground_application(path_buffer.value)
            else:
                raise process_failure(kernel32.GetLastError())
        finally:
            kernel32.CloseHandle(process)

    # Only browser site markers are needed. Never persist or read other app titles.
    site_marker = None
    title_buffer = ctypes.create_unicode_buffer(1)
    if read_title and process_name.casefold() in {"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe"}:
        title_buffer = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(window) + 1)
        user32.GetWindowTextW(window, title_buffer, len(title_buffer))
        site_marker = read_site_marker(window)

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
    idle_seconds = 0.0
    if user32.GetLastInputInfo(ctypes.byref(info)):
        idle_seconds = ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000
    else:
        raise SamplingError("FOREGROUND_UNAVAILABLE")
    if user32.GetForegroundWindow() != window:
        raise SamplingError("WINDOW_CHANGED_DURING_SAMPLE")
    return ForegroundSample(process_name, title_buffer.value, idle_seconds, application, site_marker)
