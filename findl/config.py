import os
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = "FINDL"
APP_VERSION = "0.0.3"
APP_AUTHOR = "ZoniBoy00"

def _resolve_path(value: str, default: Path) -> str:
    path = Path(value) if value else default
    return str(path if path.is_absolute() else BASE_DIR / path)

OUTPUT_DIR = _resolve_path(os.getenv("OUTPUT_DIR", "downloads"), BASE_DIR / "downloads")
TEMP_DIR = _resolve_path(os.getenv("TEMP_DIR", "_tmp_findl"), BASE_DIR / "_tmp_findl")
SESSION_DIR = _resolve_path(os.getenv("SESSION_DIR", "findl_sessions"), BASE_DIR / "findl_sessions")
LOG_DIR = _resolve_path(os.getenv("LOG_DIR", "bin/Logs"), BASE_DIR / "bin" / "Logs")

os.makedirs(LOG_DIR, exist_ok=True)

WVD_PATH = _resolve_path(os.getenv("WVD_PATH", "device.wvd"), BASE_DIR / "device.wvd")

NM3U8DL_RE_PATH = _resolve_path(os.getenv("NM3U8DL_RE_PATH", "bin/N_m3u8DL-RE.exe"), BASE_DIR / "bin" / "N_m3u8DL-RE.exe")
SHAKA_PACKAGER_PATH = _resolve_path(os.getenv("SHAKA_PACKAGER_PATH", "bin/packager-win-x64.exe"), BASE_DIR / "bin" / "packager-win-x64.exe")

CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
CHROME_UA_CH = '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"'

DEFAULT_HEADERS = {
    'User-Agent': CHROME_UA,
    'Origin': 'https://www.mtv.fi',
    'Referer': 'https://www.mtv.fi/',
    'sec-ch-ua': CHROME_UA_CH,
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'Accept': '*/*',
    'Accept-Language': 'fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7'
}
