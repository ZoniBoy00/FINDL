import re
import base64
import logging
import requests
from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlparse, parse_qs
from ..config import DEFAULT_HEADERS

class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, url):
        pass

    @abstractmethod
    def get_service_name(self):
        pass

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
            # Use a more liberal regex to catch everything between data: and the following quote or comma
            match = re.search(r'#EXT-X-(?:SESSION-)?KEY:.*URI="data:text/plain;base64,(.*?)"', content, re.I)
            if match:
                pssh = match.group(1).split(',')[0].strip()
                logging.debug(f"[BASE] Found PSSH via HLS Key: {pssh[:40]}...")
                return pssh

            # Ruutu DASH PSSH (Axinom format / plain XML)
            if "<cenc:pssh>" in content:
                try:
                    pssh = content.split("<cenc:pssh>")[1].split("</cenc:pssh>")[0].strip()
                    logging.debug(f"[BASE] Found PSSH in DASH manifest (XML extract)")
                    return pssh
                except: pass

            # B. XML / JSON PSSH Patterns (DASH/MPD)
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

            # --- 2. FALLBACK: Recursion / Deep Scan ---

            # HLS Master Playlist -> Recurse into children
            if "#EXT-X-STREAM-INF" in content:
                lines = content.splitlines()
                urls = []
                for i, line in enumerate(lines):
                    if "#EXT-X-STREAM-INF" in line and i + 1 < len(lines):
                        urls.append(urljoin(url, lines[i+1].strip()))
                
                # Check up to 5 child playlists
                for child_url in urls[:5]:
                    found = self.get_pssh_from_manifest(child_url, cookies, headers)
                    if found: return found

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
