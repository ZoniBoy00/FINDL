__version__ = "0.0.3"

_EXPORTS = {
    "Downloader": ("findl.core.downloader", "Downloader"),
    "DRMHandler": ("findl.core.drm", "DRMHandler"),
    "KatsomoExtractor": ("findl.services.katsomo", "KatsomoExtractor"),
    "RuutuExtractor": ("findl.services.ruutu", "RuutuExtractor"),
    "YleExtractor": ("findl.services.yle", "YleExtractor"),
    "ViaplayExtractor": ("findl.services.viaplay", "ViaplayExtractor"),
    "SfAnytimeExtractor": ("findl.services.sfanytime", "SfAnytimeExtractor"),
}

def __getattr__(name):
    if name in _EXPORTS:
        import importlib
        module_name, attribute = _EXPORTS[name]
        value = getattr(importlib.import_module(module_name), attribute)
        globals()[name] = value
        return value
    raise AttributeError(name)
