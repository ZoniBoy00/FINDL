SERVICE_NAME = "MTV Katsomo"
SERVICE_DOMAIN = "mtv.fi"
SERVICE_URLS = ["mtv.fi", "katsomo.fi"]

ORIGIN = "https://www.mtv.fi"
REFERER = "https://www.mtv.fi/"

DRM_TYPE = "drmtoday"
LICENSE_ASSET_ID = "tvmedia-20446735"

USE_PLAYWRIGHT = True
PLAYWRIGHT_HEADLESS = False

COOKIE_DOMAIN = ".mtv.fi"

VIDEO_PATH_PATTERN = r'/video/([a-z0-9]{15,})'
SERIES_PATH = "/ohjelma/"
EPISODE_SELECTORS = [
    "#accept-all-button",
    "text='Hyväksy kaikki'",
    "button:has-text('Hyväksy')",
    "button:has-text('Katso')",
    "button:has-text('Toista')"
]