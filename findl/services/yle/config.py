SERVICE_NAME = "Yle Areena"
SERVICE_DOMAIN = "areena.yle.fi"
SERVICE_URLS = ["areena.yle.fi"]

ORIGIN = "https://areena.yle.fi"
REFERER = "https://areena.yle.fi/"

DRM_TYPE = "widevine"
USE_YT_DLP = True

COOKIE_DOMAIN = ".yle.fi"

VIDEO_PATH_PATTERN = r'/(\d-\d+)'
SERIES_PATHS = ["/sarjat/", "/ohjelmat/"]

SUBTITLE_LANGUAGES = ['fi.*', 'suo.*', 'en.*', 'und.*']
SUBTITLE_FORMATS = ['vtt', 'srt']

PREFER_M3U8 = True
MANIFEST_PRIORITY = ["master", "gatekeeper"]

YT_DLP_OPTIONS = {
    'format': 'bestvideo+bestaudio/best',
    'force_generic_extractor': True,
    'impersonate': 'chrome',
    'socket_timeout': 60,
    'retries': 10,
}