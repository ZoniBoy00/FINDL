SERVICE_NAME = "Ruutu"
SERVICE_DOMAIN = "ruutu.fi"
SERVICE_URLS = ["ruutu.fi"]

ORIGIN = "https://www.ruutu.fi"
REFERER = "https://www.ruutu.fi/"

DRM_TYPE = "axinom"
LICENSE_KEYWORDS = ["gatetv", "nelonenmedia"]

USE_PLAYWRIGHT = True
PLAYWRIGHT_HEADLESS = False

COOKIE_DOMAIN = ".ruutu.fi"

VIDEO_PATH_PATTERN = r'/video/(\d+)'
SERIES_PATH = "/ohjelmat/"
SEASON_PATTERN = r"^Kausi \d+$"

AD_BLOCK_KEYWORDS = ["scorecardresearch", "analytics", "googletag", "gemius"]
MANIFEST_KEYWORDS = ["master", "gatekeeper"]

EPISODE_SELECTORS = [
    "button:has-text('Hyväksy')",
    "button:has-text('Accept')",
    "button:has-text('Salli')"
]