"""Safe text decoding for external commands used by JARVIS.

Windows tools do not all write using the same encoding. Python can run in UTF-8
mode while PowerShell, tasklist, nvidia-smi, schtasks, ffmpeg or vendor tools
still emit ANSI/OEM bytes. A normal ``subprocess.run(..., text=True)`` may then
raise UnicodeDecodeError inside CPython's private reader thread.

This module keeps binary subprocesses unchanged and only supplies a tolerant
encoding for text-mode subprocesses that did not choose one explicitly.
"""
from __future__ import annotations

import locale
import os
import subprocess
import threading
from typing import Any

_LOCK = threading.Lock()
_INSTALLED = False


def subprocess_text_encoding() -> str:
    """Return the configurable, byte-safe encoding for child-process text."""
    configured = os.getenv("JARVIS_SUBPROCESS_ENCODING", "").strip()
    if configured:
        return configured
    if os.name == "nt":
        # ``mbcs`` follows the active Windows ANSI code page and, unlike UTF-8,
        # accepts every byte produced by common localized Windows utilities.
        return "mbcs"
    return locale.getpreferredencoding(False) or "utf-8"


def install_subprocess_text_compat() -> None:
    """Make text-mode subprocess output tolerant without changing binary calls."""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED or getattr(subprocess.Popen, "_jarvis_text_safe", False):
            _INSTALLED = True
            return

        original_popen = subprocess.Popen
        default_encoding = subprocess_text_encoding()

        class JarvisSafePopen(original_popen):  # type: ignore[misc, valid-type]
            _jarvis_text_safe = True
            _jarvis_original_popen = original_popen

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                text_mode = bool(
                    kwargs.get("text")
                    or kwargs.get("universal_newlines")
                    or kwargs.get("encoding") is not None
                    or kwargs.get("errors") is not None
                )
                if text_mode:
                    if kwargs.get("encoding") is None:
                        kwargs["encoding"] = default_encoding
                    if kwargs.get("errors") is None:
                        kwargs["errors"] = "replace"
                super().__init__(*args, **kwargs)

        JarvisSafePopen.__name__ = "Popen"
        JarvisSafePopen.__qualname__ = "Popen"
        JarvisSafePopen.__module__ = "subprocess"
        subprocess.Popen = JarvisSafePopen  # type: ignore[assignment]
        _INSTALLED = True
