import requests
import logging
import os
import glob
from pywidevine.cdm import Cdm
from pywidevine.device import Device
from pywidevine.pssh import PSSH
from ..config import WVD_PATH, DEFAULT_HEADERS

class DRMHandler:
    def __init__(self, wvd_path=WVD_PATH):
        if not os.path.exists(wvd_path):
            wvds = glob.glob("*.wvd")
            if wvds: wvd_path = wvds[0]
        
        if not os.path.exists(wvd_path):
            raise FileNotFoundError(f"WVD file not found: {wvd_path}")
            
        self.device = Device.load(wvd_path)
        self.cdm = Cdm.from_device(self.device)

    def get_keys(self, psshs, license_url, **kwargs):
        """
        Orchestrates key acquisition.
        Supports: Standard Widevine, DRMToday (Katsomo), Axinom (Ruutu).
        """
        if not psshs: return []
        found_keys = []
        session_id = self.cdm.open()
        
        headers = DEFAULT_HEADERS.copy()
        if kwargs.get("headers"): headers.update(kwargs["headers"])

        cookies = kwargs.get("cookies")

        # Context data
        drm_token = kwargs.get("drm_token")
        asset_id = kwargs.get("asset_id") or "tvmedia-20446735"

        # Prepare token list (single token as fallback)
        tokens = kwargs.get("drm_tokens") or []
        if drm_token and drm_token not in tokens:
            tokens.append(drm_token)
        if not tokens and drm_token: tokens = [drm_token]
        if not tokens: tokens = [None] # Try at least once without token if applicable

        for pssh_data in psshs:
            try:
                pssh_obj = PSSH(pssh_data)
                challenge = self.cdm.get_license_challenge(session_id, pssh_obj)
                
                # Strategies
                if "drmtoday" in license_url:
                    keys = self._handle_drmtoday(session_id, challenge, license_url, asset_id, drm_token, headers, cookies)
                    if keys: found_keys.extend(keys)
                elif "axprod.net" in license_url or "ruutu" in license_url:
                    # Iterate through all available tokens
                    for t in tokens:
                        try:
                            # Pass headers to allow fallback token extraction if needed, though 't' should be good
                            keys = self._handle_axinom(session_id, challenge, license_url, t, headers)
                            if keys:
                                found_keys.extend(keys)
                                logging.info(f"[DRM] Keys acquired with token: {t[:10]}..." if t else "[DRM] Keys acquired without token")
                                break # Found keys for this PSSH, stop trying tokens
                        except Exception as ax_e:
                            logging.debug(f"[DRM] Token failed: {ax_e}")
                            continue
                else:
                    keys = self._handle_standard(session_id, challenge, license_url, headers, cookies)
                    if keys: found_keys.extend(keys)
                
                if found_keys:
                    break # Success on one PSSH is usually enough
 
            except Exception as e:
                logging.error(f"[DRM] PSSH processing failed: {e}")
                continue
        
        self.cdm.close(session_id)
        return list(set(found_keys))
 
    def _handle_drmtoday(self, session_id, challenge, license_url, asset_id, drm_token, base_headers, cookies=None):
        """Strategy for MTV Katsomo / DRMToday"""
        lic_url = license_url
        if "assetId=" not in lic_url:
            lic_url += ("&" if "?" in lic_url else "?") + f"assetId={asset_id}"
        
        h = base_headers.copy()
        if drm_token:
            h['Authorization'] = f"Bearer {drm_token}"
            h['x-dt-auth-token'] = drm_token
        
        res = requests.post(lic_url, data=challenge, headers=h, cookies=cookies, timeout=15)
        if res.status_code == 200:
            return self._parse_license(session_id, res.content)
        return []
 
    def _handle_axinom(self, session_id, challenge, license_url, drm_token, original_headers=None):
        """Ultra-Strict Axinom Strategy (WidevineProxy2 Integration)"""
        
        # WidevineProxy2 style: Only essential headers.
        req_headers = {
            'Content-Type': 'application/octet-stream',
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            'Origin': 'https://www.ruutu.fi',
            'Referer': 'https://www.ruutu.fi/',
            'Accept': '*/*',
            'Connection': 'keep-alive',
            'Accept-Encoding': None # Prevent requests from adding gzip
        }

        # Priority: X-AxDRM-Message header
        token = drm_token
        if not token and original_headers:
            token = original_headers.get('X-AxDRM-Message') or original_headers.get('x-axdrm-message')

        if token:
            # Clean token (remove 'Bearer ' and quotes)
            token = token.replace("Bearer ", "").strip().strip('"').strip("'")
            req_headers['X-AxDRM-Message'] = token

        logging.info(f"[DRM] Sending Axinom request with WidevineProxy2 logic...")

        # Use Session and CLEAR headers to ensure no leakage from 'requests' defaults
        session = requests.Session()
        session.headers.clear() 
        
        try:
            res = session.post(license_url, data=challenge, headers=req_headers, timeout=15)
            if res.status_code == 200:
                return self._parse_license(session_id, res.content)
            else:
                logging.error(f"[DRM] Axinom rejected ({res.status_code}): {res.text[:200]}")
        except Exception as e:
            logging.error(f"[DRM] Axinom request failed: {e}")
            
        return []

    def _handle_standard(self, session_id, challenge, license_url, headers, cookies=None):
        """Strategy for Generic Widevine"""
        res = requests.post(license_url, data=challenge, headers=headers, cookies=cookies, timeout=15)
        if res.status_code == 200:
            return self._parse_license(session_id, res.content)
        return []

    def _parse_license(self, session_id, content):
        """Parses license content and extracts keys"""
        found = []
        try:
            self.cdm.parse_license(session_id, content)
            for key in self.cdm.get_keys(session_id):
                if key.type == 'CONTENT':
                    found.append(f"{key.kid.hex}:{key.key.hex()}")
        except Exception as e:
            logging.error(f"[DRM] License parsing error: {e}")
        return found
