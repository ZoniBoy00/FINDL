WVD_PATH = "./device.wvd"

LICENSE_TIMEOUT = 15

DEFAULT_ASSET_ID = "tvmedia-20446735"

DRM_STRATEGIES = {
    "drmtoday": {
        "auth_headers": ["Authorization", "x-dt-auth-token"],
        "requires_asset_id": True
    },
    "axinom": {
        "auth_headers": ["X-AxDRM-Message"],
        "token_header": "X-AxDRM-Message",
        "strict_headers": True
    },
    "standard": {
        "auth_headers": ["Authorization"],
        "requires_cookies": False
    }
}

CONTENT_KEY_TYPE = "CONTENT"