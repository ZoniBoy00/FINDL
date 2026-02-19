import yt_dlp
import logging
import re
import requests
from .base import BaseExtractor
from ..config import CHROME_UA

class YleExtractor(BaseExtractor):
    def get_service_name(self):
        return "Yle Areena"

    def extract(self, url):
        """
        Extraction logic for Yle Areena.
        Uses yt-dlp to extract manifest URL and other details.
        """
        logging.info(f"[YLE] Extracting info for: {url}")
        
        # We use yt-dlp to get the manifest and basic metadata
        # Yle content is usually HLS/DASH.
        
        if "areena.yle.fi" not in url:
            logging.error(f"[YLE] Invalid URL: {url}")
            return None

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'user_agent': CHROME_UA,
            'extract_flat': 'in_playlist',
            'yesplaylist': False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            if not info:
                return None

            # Handle playlists/series (take first item)
            if 'entries' in info:
                logging.warning(f"[YLE] Playlist/Series detected, taking first item.")
                entries = [e for e in info['entries'] if e]
                if entries:
                    info = entries[0]
                    # If it's a flat entry, extract the full info
                    if info.get('_type') == 'url' or not info.get('formats'):
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl_deep:
                            info = ydl_deep.extract_info(info.get('url') or info.get('webpage_url'), download=False)

            result = {
                "title": info.get('title'),
                "manifest_url": info.get('url'),
                "subtitles": [],
                "cookies": {},
                "license_url": None,
                "license_headers": {},
                "psshs": [],
                "pssh": None,
                "origin": "https://areena.yle.fi"
            }

            # If yt-dlp didn't find manifest in 'url', check 'formats'
            if not result["manifest_url"] and info.get('formats'):
                # Prefer m3u8 or mpd
                for f in info['formats']:
                    if f.get('ext') in ['m3u8', 'mpd'] or 'manifest' in f.get('url', '').lower():
                        result["manifest_url"] = f['url']
                        break

            # Cleanup title
            if result["title"]:
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")

            # Extract Subtitles
            if info.get('subtitles'):
                for lang, tracks in info['subtitles'].items():
                    for track in tracks:
                        if track.get('ext') in ['vtt', 'srt']:
                            label = lang
                            if "qag" in lang.lower() or "ohjelma" in lang.lower():
                                label = f"{lang} (Ohjelmatekstitys)"
                            
                            result["subtitles"].append({
                                "url": track.get('url'),
                                "language": lang,
                                "label": label
                            })

            # Deep Scan for PSSH if it's a DASH manifest
            if result["manifest_url"] and ".mpd" in result["manifest_url"]:
                pssh = self.get_pssh_from_manifest(result["manifest_url"])
                if pssh:
                    result["psshs"].append(pssh)
                    result["pssh"] = pssh
                    logging.info(f"[YLE] Found PSSH in DASH manifest")

            return result

        except Exception as e:
            logging.error(f"[YLE] Extraction error: {e}")
            return None
