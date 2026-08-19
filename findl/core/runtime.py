"""Runtime checks and safe formatting helpers."""
from __future__ import annotations
import importlib.util
import re
import shutil
from pathlib import Path
from findl.config import BASE_DIR, NM3U8DL_RE_PATH, SHAKA_PACKAGER_PATH

REQUIRED_MODULES = {
    "click": "click", "playwright": "playwright", "requests": "requests",
    "rich": "rich", "yt_dlp": "yt-dlp", "dotenv": "python-dotenv", "pywidevine": "pywidevine",
}

def redact_message(message: str) -> str:
    patterns = [
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s|]+", r"\1<redacted>"),
        (r"(?i)(cookie\s*[:=]\s*)[^|\n]+", r"\1<redacted>"),
        (r"(?i)(token|license_token|drm_token)\s*[:=]\s*[^\s,|]+", r"\1=<redacted>"),
        (r"(?i)\b[0-9a-f]{32}:[0-9a-f]{32}\b", "<key-redacted>"),
    ]
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message)
    return message

def runtime_report():
    report = []
    for module, package in REQUIRED_MODULES.items():
        report.append((f"Python: {package}", importlib.util.find_spec(module) is not None, ""))
    local_ffmpeg = BASE_DIR / "bin" / "ffmpeg.exe"
    ffmpeg_path = shutil.which("ffmpeg") or (str(local_ffmpeg) if local_ffmpeg.exists() else "")
    for label, path in (("N_m3u8DL-RE", NM3U8DL_RE_PATH), ("Shaka Packager", SHAKA_PACKAGER_PATH), ("ffmpeg", ffmpeg_path)):
        report.append((f"Binary: {label}", bool(path and Path(path).exists()), str(path or "not found")))
    return report
