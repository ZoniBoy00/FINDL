import re
import base64
import logging
import requests
from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlparse, parse_qs
from ..config import DEFAULT_HEADERS

class BaseExtractor(ABC):
    """
    Base class for all service extractors.
    """
    @abstractmethod
    def extract(self, url):
        pass

    @abstractmethod
    def get_service_name(self):
        pass

    def is_series(self, url):
        return False

    def get_episodes(self, url):
        return []

    def _resolve_url(self, url):
        if "gnsnpaw.com" in url or "decision" in url:
            try:
                params = parse_qs(urlparse(url).query)
                if 'resource' in params: return params['resource'][0]
            except: pass
        return url

    def parse_pssh_from_init(self, data):
        """Public alias for extracting PSSH from binary init segment"""
        return self._extract_pssh_from_binary(data)

    def _extract_pssh_from_binary(self, data):
        try:
            # Look for 'pssh' box (BMFF)
            pos = data.find(b'pssh')
            if pos >= 4:
                size = int.from_bytes(data[pos-4:pos], byteorder='big')
                if size > 0 and pos + size <= len(data) + 4:
                    pssh_box = data[pos-4:pos+size-4]
                    return base64.b64encode(pssh_box).decode()
        except: pass
        return None

    def get_pssh_from_manifest(self, url, cookies=None, headers=None):
        url = self._resolve_url(url)
        try:
            req_headers = DEFAULT_HEADERS.copy()
            if headers: req_headers.update(headers)
            
            resp = requests.get(url, headers=req_headers, cookies=cookies, timeout=15)
            if resp.status_code != 200:
                logging.debug(f"[BASE] Manifest request failed: {resp.status_code} ({url})")
                return None
                
            content = resp.text

            # --- 1. PRIORITY: Check current content for Keys/PSSH ---
            
            # A. HLS Key / Session Key (Katsomo Master/Media playlists)
            # Look for PSSH data in data-URI format
            match = re.search(r'#EXT-X-(?:SESSION-)?KEY:.*URI="data:[^;"]*?(?:;base64)?,([^"]+)"', content, re.I)
            if match:
                pssh = match.group(1).split(',')[0].strip()
                logging.debug(f"[BASE] Found PSSH via HLS Key (data-URI): {pssh[:40]}...")
                return pssh

            # Look for PSSH data in a direct pssh= attribute (common in A2D)
            match = re.search(r'pssh="?([^,\s"]+)"?', content, re.I)
            if match:
                pssh = match.group(1).strip()
                if len(pssh) > 40:
                    logging.debug(f"[BASE] Found PSSH via pssh= attribute: {pssh[:40]}...")
                    return pssh
            
            # Fallback for DASH/XML PSSH Patterns
            patterns = [
                r'<(?:[a-zA-Z0-9]+:)?pssh[^>]*>(.*?)</(?:[a-zA-Z0-9]+:)?pssh>', 
                r'cenc:pssh>(.*?)</cenc:pssh>',
            ]
            for p in patterns:
                match = re.search(p, content, re.I | re.S)
                if match:
                    pssh = match.group(1).strip()
                    logging.debug(f"[BASE] Found PSSH via DASH Pattern: {pssh[:40]}...")
                    return pssh

            # Final Fallback: Search for any long base64 string that looks like a PSSH box
            # cHNzaA is 'pssh' in base64 within a BMFF box
            common_pssh_matches = re.findall(r'([a-zA-Z0-9+/=]{60,})', content)
            for candidate in common_pssh_matches:
                if "cHNzaA" in candidate:
                    logging.debug(f"[BASE] Found PSSH via raw base64 scan: {candidate[:40]}...")
                    return candidate

            # --- 2. SECONDARY: Recurse into HLS sub-playlists if it's a master ---
            if "#EXT-X-STREAM-INF" in content:
                # Find first variant/media playlist
                sub_match = re.search(r'#EXT-X-STREAM-INF:.*?\n(.*?\.m3u8.*)', content, re.I)
                if sub_match:
                    sub_url = sub_match.group(1).strip()
                    if not sub_url.startswith("http"):
                        # Resolve relative path
                        base = url.rsplit("/", 1)[0]
                        if sub_url.startswith("/"):
                            sub_url = "/".join(url.split("/")[:3]) + sub_url
                        else:
                            sub_url = f"{base}/{sub_url}"
                    
                    logging.debug(f"[BASE] No PSSH in Master, checking Media Playlist: {sub_url}")
                    # Simple one-level recursion
                    try:
                        sub_resp = requests.get(sub_url, headers=req_headers, cookies=cookies, timeout=10)
                        if sub_resp.status_code == 200:
                            sub_content = sub_resp.text
                            # Apply the SAME logic to sub_content
                            # HLS/pssh search
                            m = re.search(r'pssh="?([^,\s"]+)"?', sub_content, re.I)
                            if m: return m.group(1).strip()
                            
                            # data-URI search
                            m = re.search(r'#EXT-X-(?:SESSION-)?KEY:.*URI="data:[^;"]*?(?:;base64)?,([^"]+)"', sub_content, re.I)
                            if m: return m.group(1).split(',')[0].strip()
                            
                            # base64 scan
                            matches = re.findall(r'([a-zA-Z0-9+/=]{60,})', sub_content)
                            for cand in matches:
                                if "cHNzaA" in cand: return cand
                    except: pass

            # B. XML / JSON PSSH patterns (DASH/MPD)
            patterns = [
                r'<(?:[a-zA-Z0-9]+:)?pssh[^>]*>(.*?)</(?:[a-zA-Z0-9]+:)?pssh>', 
                r'cenc:pssh>(.*?)</cenc:pssh>',
                r'"pssh(?:"|Value)?"\s*:\s*"([^"]{20,})"',
            ]
            for p in patterns:
                match = re.search(p, content, re.I | re.S)
                if match:
                    pssh = match.group(1).strip()
                    logging.debug(f"[BASE] Found PSSH via DASH Pattern: {pssh[:40]}...")
                    return pssh

            # Init Segment scan (MP4 header)
            init_match = re.search(r'#EXT-X-MAP:URI="(.*?)"', content, re.I)
            if init_match:
                init_url = urljoin(url, init_match.group(1))
                init_resp = requests.get(init_url, headers=req_headers, cookies=cookies, timeout=15)
                if init_resp.status_code == 200:
                    pssh = self._extract_pssh_from_binary(init_resp.content)
                    if pssh:
                        logging.debug(f"[BASE] Found PSSH via Init Segment: {pssh[:40]}...")
                        return pssh
            
        except Exception as e:
            logging.debug(f"[BASE] Manifest scan error: {e}")
        return None
