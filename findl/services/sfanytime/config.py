SERVICE_NAME = "SF Anytime"
SERVICE_DOMAIN = "sfanytime.com"
SERVICE_URLS = ["sfanytime.com"]

ORIGIN = "https://www.sfanytime.com"
REFERER = "https://www.sfanytime.com/"

DRM_TYPE = "widevine"
USE_YT_DLP = False

COOKIE_DOMAIN = ".sfanytime.com"

# Patterns for movie/player URLs
VIDEO_PATH_PATTERN = r'/(?:movie|player)/([^/?#]+)'
SERIES_PATHS = [] 

SUBTITLE_LANGUAGES = ['fi.*', 'suo.*', 'en.*', 'und.*']
SUBTITLE_FORMATS = ['vtt', 'srt']

PREFER_M3U8 = False # MPD is common for widevine
MANIFEST_PRIORITY = ["manifest.mpd", "manifest.m3u8"]
