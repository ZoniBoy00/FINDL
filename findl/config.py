import os
from dotenv import load_dotenv

load_dotenv()

# Project Info
APP_NAME = "FINDL"
APP_VERSION = "0.0.1"
APP_AUTHOR = "ZoniBoy00"

# Paths
BASE_DIR = os.getcwd()
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "downloads")
TEMP_DIR = os.path.abspath("_tmp_findl")
SESSION_DIR = os.path.join(BASE_DIR, "findl_sessions")
WVD_PATH = os.getenv("WVD_PATH", "./device.wvd")

# Binary Paths
NM3U8DL_RE_PATH = os.getenv("NM3U8DL_RE_PATH", "bin/N_m3u8DL-RE.exe")
SHAKA_PACKAGER_PATH = os.getenv("SHAKA_PACKAGER_PATH", "bin/packager-win-x64.exe")

# Network / Headers
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
