SERVICE_NAME = "Viaplay"
SERVICE_DOMAIN = "viaplay.fi"
SERVICE_URLS = ["viaplay.fi", "viaplay.se", "viaplay.dk", "viaplay.no"]

ORIGIN = "https://viaplay.fi"
REFERER = "https://viaplay.fi/"

DRM_TYPE = "widevine"
LICENSE_KEYWORDS = ["/api/license", "play.viaplay", "lic.widevine.com"]

USE_PLAYWRIGHT = True
PLAYWRIGHT_HEADLESS = False

COOKIE_DOMAIN = ".viaplay.fi"

SERIES_PATHS = ["/sarjat/", "/tv/"]
SEASON_PATTERN = r"^(Kausi|Season) \d+$"

API_PATHS = ["/stream/", "/product/", "/content/"]
MANIFEST_TYPES = ["viaplay:media", "viaplay:playlist", "viaplay:encryptedPlaylist", "viaplay:fallbackMedia"]

EPISODE_SELECTORS = [
    "#accept-all-button",
    "button:has-text('Hyväksy')",
    "button:has-text('Accept')",
    "a[data-test-id='play-link']",
    "button:has-text('Katso')"
]