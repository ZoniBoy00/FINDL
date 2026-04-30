import requests
import logging
import os
import glob
from pywidevine.cdm import Cdm
from pywidevine.device import Device
from pywidevine.pssh import PSSH
from findl.config import WVD_PATH, DEFAULT_HEADERS

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
            session_id = self.cdm.open()
            try:
                pssh_obj = PSSH(pssh_data)
                challenge = self.cdm.get_license_challenge(session_id, pssh_obj)
                
                # Strategies
                if "drmtoday" in license_url:
                    keys = self._handle_drmtoday(session_id, challenge, license_url, asset_id, drm_token, headers, cookies)
                    if keys: found_keys.extend(keys)
                elif "axprod.net" in license_url or "ruutu" in license_url or "axinom" in license_url:
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
                elif "theplatform.eu" in license_url:
                    # For thePlatform, pass only captured headers (not merged with DEFAULT_HEADERS)
                    # to avoid mtv.fi Origin/Referer contamination
                    tp_headers = kwargs.get("headers") or {}
                    keys = self._handle_theplatform(session_id, challenge, license_url, tp_headers, cookies)
                    if keys: found_keys.extend(keys)
                else:
                    keys = self._handle_standard(session_id, challenge, license_url, headers, cookies)
                    if keys: found_keys.extend(keys)
                
                # DO NOT break here! Some services (like Viaplay) use separate
                # PSSHs and keys for Audio and Video. We need to iterate all PSSHs
                # to gather all necessary decryption keys.
                # if found_keys:
                #     break # Success on one PSSH is usually enough
 
            except Exception as e:
                logging.error(f"[DRM] PSSH processing failed: {e}")
                continue
            finally:
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
            'Origin': (original_headers or {}).get('Origin') or (original_headers or {}).get('origin') or 'https://www.sfanytime.com',
            'Referer': (original_headers or {}).get('Referer') or (original_headers or {}).get('referer') or 'https://www.sfanytime.com/',
            'Accept': '*/*',
            'Connection': 'keep-alive',
            'Accept-Encoding': None # Prevent requests from adding gzip
        }

        # Priority: X-AxDRM-Message or X-Axinom-DRM-Token header
        token = drm_token
        if not token and original_headers:
            token = original_headers.get('X-AxDRM-Message') or original_headers.get('x-axdrm-message') or \
                    original_headers.get('X-Axinom-DRM-Token') or original_headers.get('x-axinom-drm-token')

        if token:
            # Clean token (remove 'Bearer ' and quotes)
            token = token.replace("Bearer ", "").strip().strip('"').strip("'")
            req_headers['X-AxDRM-Message'] = token
            # SF Anytime uses X-Axinom-DRM-Token
            req_headers['X-Axinom-DRM-Token'] = token

        # Ensure the Origin isn't Ruutu if we are on SF Anytime
        if "axprod.net" in license_url and not ("ruutu.fi" in req_headers['Origin']):
             # If it's not ruutu, it's likely sfanytime or similar
             pass # Already handled by (original_headers or {}) check

        logging.info(f"[DRM] Sending Axinom request with WidevineProxy2 logic...")

        # Use Session and CLEAR headers to ensure no leakage from 'requests' defaults
        session = requests.Session()
        session.headers.clear() 
        
        try:
            res = session.post(license_url, data=challenge, headers=req_headers, timeout=15)
            if res.status_code == 200:
                return self._parse_license(session_id, res.content)
            else:
                logging.error(f"[DRM] Axinom rejected ({res.status_code}): {res.text[:500]}")
                if "Origin" in req_headers:
                    logging.info(f"[DRM] Request Origin was: {req_headers['Origin']}")
        except Exception as e:
            logging.error(f"[DRM] Axinom request failed: {e}")
            
        return []

    def _handle_standard(self, session_id, challenge, license_url, headers, cookies=None):
        """Strategy for Generic Widevine"""
        logging.info(f"[DRM] Sending standard license request to: {license_url[:60]}...")
        res = requests.post(license_url, data=challenge, headers=headers, cookies=cookies, timeout=15)
        if res.status_code == 200:
            logging.info(f"[DRM] License request successful.")
            return self._parse_license(session_id, res.content)
        
        logging.error(f"[DRM] License request failed with status {res.status_code}")
        logging.debug(f"[DRM] Response: {res.text[:500]}")
        return []

    def _handle_theplatform(self, session_id, challenge, license_url, headers, cookies=None):
        """Strategy for Viaplay/thePlatform Widevine - replicates browser request closely"""
        from urllib.parse import urlparse, parse_qs, urlencode

        logging.info(f"[DRM] Sending thePlatform request to: {license_url[:60]}...")

        parsed = urlparse(license_url)
        query_params = parse_qs(parsed.query)

        # Build CLEAN captured headers from license_headers only (NOT DEFAULT_HEADERS)
        # The 'headers' param may contain DEFAULT_HEADERS (with mtv.fi Origin/Referer) merged
        # with the captured license_headers. We need to strip all non-Viaplay pollution.
        captured = {}
        raw_headers = (headers or {})
        for h, v in raw_headers.items():
            h_lower = h.lower()
            # Strip headers that cause HTTP 431 or are unnecessary for the license server
            if h_lower in ('content-length', 'host', 'connection', 'accept-encoding',
                           'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform',
                           'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site'):
                continue
            # Skip mtv.fi / ruutu.fi origins/referers that leak from DEFAULT_HEADERS
            if h_lower in ('origin', 'referer') and ('mtv.fi' in v or 'ruutu.fi' in v):
                continue
            # Skip DEFAULT_HEADERS user-agent in favour of our own
            if h_lower == 'user-agent':
                continue
            captured[h] = v

        # Deduplicate headers: if both 'Referer' and 'referer' exist, keep lowercase only
        dedup_lower_seen = set()
        for h in list(captured.keys()):
            lk = h.lower()
            if lk in dedup_lower_seen:
                del captured[h]
            else:
                dedup_lower_seen.add(lk)

        # Log captured headers for debugging (mask sensitive values partially)
        safe_captured = {k: (v[:20] + '...' if len(v) > 30 else v) for k, v in captured.items()}
        logging.info(f"[DRM] Cleaned captured headers: {safe_captured}")

        # Helper to build strategy dicts with CLEAN headers (no DEFAULT_HEADERS pollution)
        def make_strategy(name, url, overrides, use_cookies=None):
            h = captured.copy()
            # Remove cookie from headers (use dict-based cookies instead)
            for ck in ('Cookie', 'cookie'):
                h.pop(ck, None)
            h.update(overrides)
            return {'name': name, 'url': url, 'headers': h, 'cookies': use_cookies}

        no_cmcd_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode({k: v for k, v in query_params.items() if k != 'CMCD'}, doseq=True)}"

        # Base headers for all strategies - clean Viaplay-specific headers
        viaplay_base = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            'Content-Type': 'application/octet-stream',
            'Accept': '*/*',
            'Origin': 'https://viaplay.fi',
            'Referer': 'https://viaplay.fi/',
        }

        strategies = [
            # 1) Clean Viaplay headers with full URL (token is in URL query params)
            make_strategy('viaplay_clean_full_url', license_url, {**viaplay_base}),
            # 2) Clean Viaplay headers without CMCD query param
            make_strategy('viaplay_clean_no_cmcd', no_cmcd_url, {**viaplay_base}),
            # 3) With captured auth headers merged + full URL
            make_strategy('captured_plus_viaplay_full_url', license_url, {
                **viaplay_base,
                **{k: v for k, v in captured.items() if k.lower() not in ('user-agent', 'origin', 'referer', 'accept', 'content-type')},
            }),
            # 4) With captured auth headers merged + no CMCD
            make_strategy('captured_plus_viaplay_no_cmcd', no_cmcd_url, {
                **viaplay_base,
                **{k: v for k, v in captured.items() if k.lower() not in ('user-agent', 'origin', 'referer', 'accept', 'content-type')},
            }),
            # 5) Minimal headers - only essentials
            make_strategy('minimal_full_url', license_url, {
                'Content-Type': 'application/octet-stream',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            }),
            # 6) With cookies
            make_strategy('viaplay_with_cookies', no_cmcd_url, {**viaplay_base}, use_cookies=cookies),
        ]

        for strategy in strategies:
            h = strategy['headers'].copy()
            url = strategy['url']
            strategy_cookies = strategy.get('cookies')

            logging.info(f"[DRM] Trying strategy: {strategy['name']}")
            # Log full headers for debugging
            safe_h = {k: (v[:30] + '...' if len(str(v)) > 35 else v) for k, v in h.items()}
            logging.info(f"[DRM] Strategy headers: {safe_h}")

            try:
                session = requests.Session()
                session.headers.clear()

                res = session.post(url, data=challenge, headers=h, cookies=strategy_cookies, timeout=15)

                if res.status_code == 200:
                    logging.info(f"[DRM] thePlatform license request returned HTTP 200 with {strategy['name']}")
                    keys = self._parse_license(session_id, res.content)
                    if keys:
                        logging.info(f"[DRM] Keys acquired with {strategy['name']}: {len(keys)} key(s)")
                        return keys
                    else:
                        logging.warning(f"[DRM] Strategy {strategy['name']} returned 200 but no keys were parsed. Response preview: {res.content[:100]}")
                else:
                    body_preview = res.text[:300] if res.text else '(empty body)'
                    logging.info(f"[DRM] Strategy {strategy['name']} failed: HTTP {res.status_code} | Body: {body_preview}")
            except Exception as e:
                logging.info(f"[DRM] Strategy {strategy['name']} exception: {e}")

        logging.error(f"[DRM] All thePlatform strategies failed")
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
