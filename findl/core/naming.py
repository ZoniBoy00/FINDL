"""Filename and folder naming rules for downloaded media."""
import os
import re
from urllib.parse import urlparse
def sanitize_path_name(name):
    """Keep filename-safe characters without importing optional browser dependencies."""
    return re.sub(r'[<>:"/\\|?*]', '', str(name or '')).strip().rstrip('.')

def format_series_title(info, ep=None):
    series = info.get("series")
    season = info.get("season")
    episode_num = info.get("episode")
    original_title = info.get("title", "Video")
    season_match = re.search(r"\d+", str(season)) if season else None
    season_value = int(season_match.group()) if season_match else None
    title_season = re.search(r"Kausi\s*(\d+)|Season\s*(\d+)", original_title, re.I)
    if title_season:
        detected = int(title_season.group(1) or title_season.group(2))
        if not season_value or detected == season_value:
            season = f"Kausi {detected}"
    if not episode_num:
        episode_match = re.search(r"Jakso\s*(\d+)|Episode\s*(\d+)", original_title, re.I)
        if episode_match:
            episode_num = int(episode_match.group(1) or episode_match.group(2))
    title = re.sub(r"[^\w\s-]", "", original_title).strip().replace(" ", "_")
    for label in ("Jakso", "Kausi", "Season", "Episode"):
        title = re.sub(rf"[-_\s]*{label}[-_\s]*\d+[-_\s]*", "", title, flags=re.I)
    title = re.sub(r"[-_]+", "_", title).strip("_-")
    if series:
        clean_series = sanitize_path_name(series)
        title = re.sub(rf"^{re.escape(clean_series)}[-_\s]*", "", title, flags=re.I).strip("_-")
    if not title or len(title) < 2:
        title = f"Episode_{episode_num:02d}" if episode_num else "Episode"
    if not series:
        return title
    season_number = re.search(r"\d+", str(season)) if season else None
    season_str = f"_S{int(season_number.group()):02d}" if season_number else ""
    episode_str = f"E{int(episode_num):02d}" if episode_num else ""
    series_name = re.sub(r"[^A-Z0-9]", "", sanitize_path_name(series).upper())
    return f"{series_name}{season_str}{episode_str}_{title}"

def get_folder_structure(info, ep=None):
    if not info.get("series"):
        return None
    series_name = re.sub(r"[^A-Z0-9]", "", sanitize_path_name(info["series"]).upper())
    return os.path.join(series_name, sanitize_path_name(info.get("season") or "Season 1"))

def title_from_url(url):
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\b\d{4}\b", "", slug)
    return re.sub(r"\s+", " ", slug).strip().title() or "Video"

def is_generic_title(title):
    normalized = re.sub(r"[_-]+", " ", str(title or "")).strip().lower()
    return normalized in {"video", "episode", "viaplay", "viaplay sarja", "yle", "yle areena", "yle sarja", "ruutu", "ruutu sarja", "mtv", "mtv katsomo", "katsomo", "sf anytime", "sfanytime"}
