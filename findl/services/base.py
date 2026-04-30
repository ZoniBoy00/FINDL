import re
import base64
import logging
import requests
from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlparse, parse_qs
from findl.config import DEFAULT_HEADERS, CHROME_UA, SESSION_DIR
from playwright.sync_api import sync_playwright
import os

logger = logging.getLogger(__name__)

def sanitize_path_name(name):
    if not name: return "Unknown"
    s = re.sub(r'[\<\>\:\"\/\\\|\?\*]', '-', str(name))
    s = re.sub(r'[\x00-\x1f]', '', s)
    return s.strip().strip('.')

class BaseExtractor(ABC):
    """
    Base class for all service extractors.
    """
    SERVICE_NAME = "BaseExtractor"
    SERVICE_URL = ""
    
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

    def _init_playwright_browser(self, headless=True, context_persistant=False):
        """Initialize Playwright browser with anti-detection scripts."""
        if not os.path.exists(SESSION_DIR):
            os.makedirs(SESSION_DIR)
        
        with sync_playwright() as p:
            if context_persistant:
                context = p.chromium.launch_persistent_context(
                    SESSION_DIR,
                    headless=headless,
                    channel="chrome",
                    user_agent=CHROME_UA,
                    ignore_default_args=["--enable-automation", "--no-sandbox", "--disable-component-update"],
                    args=[
                        "--start-maximized",
                        "--enable-widevine-cdm",
                        "--lang=fi-FI,fi"
                    ]
                )
                page = context.pages[0] if context.pages else context.new_page()
                self._add_anti_detection(page)
                return context, page
            else:
                browser = p.chromium.launch(headless=headless)
                page = browser.new_page(user_agent=CHROME_UA)
                self._add_anti_detection(page)
                return browser, page
    
    def _add_anti_detection(self, page):
        """Add anti-detection scripts to Playwright page."""
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['fi-FI', 'fi']});
        """)

    def _click_consent_buttons(self, page, selectors=None):
        """Common consent button clicking logic."""
        if selectors is None:
            selectors = [
                "#accept-all-button",
                "text='Hyväksy kaikki'",
                "button:has-text('Hyväksy')",
                "button:has-text('Accept')",
                "button:has-text('OK')"
            ]
        
        for sel in selectors:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                page.wait_for_timeout(1000)
                logger.info(f"[{self.SERVICE_NAME}] Clicked consent button: {sel}")
                return True
        return False

    def _click_play_button(self, page, selectors=None):
        """Common play button clicking logic."""
        if selectors is None:
            selectors = [
                "button:has-text('Katso')",
                "button:has-text('Toista')",
                ".play-icon",
                "button[aria-label='Play']",
                ".play-button",
                ".vjs-big-play-button"
            ]
        
        for sel in selectors:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                page.wait_for_timeout(2000)
                logger.info(f"[{self.SERVICE_NAME}] Clicked play button: {sel}")
                return True
        return False

    def _resolve_url(self, url):
        if "gnsnpaw.com" in url or "decision" in url:
            try:
                params = parse_qs(urlparse(url).query)
                if 'resource' in params: return params['resource'][0]
            except Exception as e:
                logger.debug(f"[{self.SERVICE_NAME}] URL resolution error: {e}")
        return url

    def parse_pssh_from_init(self, data):
        """Public alias for extracting PSSH from binary init segment"""
        return self._extract_pssh_from_binary(data)

    def _extract_pssh_from_binary(self, data):
        try:
            pos = data.find(b'pssh')
            if pos >= 4:
                size = int.from_bytes(data[pos-4:pos], byteorder='big')
                if size > 0 and pos + size <= len(data) + 4:
                    pssh_box = data[pos-4:pos+size-4]
                    logger.info(f"[{self.SERVICE_NAME}] Extracted PSSH from binary (size: {size})")
                    return base64.b64encode(pssh_box).decode()
        except Exception as e:
            logger.debug(f"[{self.SERVICE_NAME}] PSSH binary extraction error: {e}")
        return None

    def get_pssh_from_manifest(self, url, cookies=None, headers=None):
        url = self._resolve_url(url)
        try:
            req_headers = DEFAULT_HEADERS.copy()
            if headers: req_headers.update(headers)
            
            logger.info(f"[{self.SERVICE_NAME}] Scanning manifest for PSSH: {url[:50]}...")
            resp = requests.get(url, headers=req_headers, cookies=cookies, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[{self.SERVICE_NAME}] Manifest request failed: {resp.status_code}")
                return None
                
            content = resp.text
            match = re.search(r'#EXT-X-(?:SESSION-)?KEY:.*URI="data:[^;"]*?(?:;base64)?,([^"]+)"', content, re.I)
            if match:
                pssh = match.group(1).split(',')[0].strip()
                logger.info(f"[{self.SERVICE_NAME}] Found PSSH via HLS Key (data-URI)")
                return pssh

            match = re.search(r'pssh="?([^,\s"]+)"?', content, re.I)
            if match:
                pssh = match.group(1).strip()
                if len(pssh) > 40:
                    logger.info(f"[{self.SERVICE_NAME}] Found PSSH via pssh= attribute")
                    return pssh
            
            # DASH PSSH extraction - MUST filter for Widevine System ID
            # Widevine System ID: edef8ba9-79d6-4ace-a3c8-27dcd51d21ed
            widevine_pssh = None
            
            # Strategy 1: Find PSSH inside Widevine-specific ContentProtection block
            cp_blocks = re.findall(
                r'<ContentProtection[^>]*schemeIdUri="urn:uuid:edef8ba9[^"]*"[^>]*>(.*?)</ContentProtection>',
                content, re.I | re.S
            )
            for block in cp_blocks:
                m = re.search(r'<(?:[a-zA-Z0-9]+:)?pssh[^>]*>(.*?)</(?:[a-zA-Z0-9]+:)?pssh>', block, re.I | re.S)
                if m:
                    widevine_pssh = m.group(1).strip()
                    break
            
            # Strategy 2: Check all PSSH elements and verify system ID bytes
            if not widevine_pssh:
                all_psshs_found = re.findall(r'<(?:[a-zA-Z0-9]+:)?pssh[^>]*>(.*?)</(?:[a-zA-Z0-9]+:)?pssh>', content, re.I | re.S)
                widevine_sys_bytes = bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed")
                for candidate in all_psshs_found:
                    candidate = candidate.strip()
                    if not candidate:
                        continue
                    try:
                        decoded = base64.b64decode(candidate)
                        if widevine_sys_bytes in decoded:
                            widevine_pssh = candidate
                            break
                    except:
                        pass
                # Fallback: take the last one (Widevine often comes after PlayReady)
                if not widevine_pssh and all_psshs_found:
                    widevine_pssh = all_psshs_found[-1].strip()
            
            if widevine_pssh:
                logger.info(f"[{self.SERVICE_NAME}] Found Widevine PSSH via DASH Pattern")
                return widevine_pssh

            common_pssh_matches = re.findall(r'([a-zA-Z0-9+/=]{60,})', content)
            for candidate in common_pssh_matches:
                if "cHNzaA" in candidate:
                    logger.info(f"[{self.SERVICE_NAME}] Found PSSH via raw base64 scan")
                    return candidate

            if "#EXT-X-STREAM-INF" in content:
                sub_match = re.search(r'#EXT-X-STREAM-INF:.*?\n(.*?\.m3u8.*)', content, re.I)
                if sub_match:
                    sub_url = sub_match.group(1).strip()
                    if not sub_url.startswith("http"):
                        base = url.rsplit("/", 1)[0]
                        if sub_url.startswith("/"):
                            sub_url = "/".join(url.split("/")[:3]) + sub_url
                        else:
                            sub_url = f"{base}/{sub_url}"
                    
                    logger.debug(f"[{self.SERVICE_NAME}] Checking sub-playlist: {sub_url}")
                    try:
                        sub_resp = requests.get(sub_url, headers=req_headers, cookies=cookies, timeout=10)
                        if sub_resp.status_code == 200:
                            sub_content = sub_resp.text
                            m = re.search(r'pssh="?([^,\s"]+)"?', sub_content, re.I)
                            if m: return m.group(1).strip()
                            m = re.search(r'#EXT-X-(?:SESSION-)?KEY:.*URI="data:[^;"]*?(?:;base64)?,([^"]+)"', sub_content, re.I)
                            if m: return m.group(1).split(',')[0].strip()
                    except Exception as e:
                        logger.debug(f"[{self.SERVICE_NAME}] Sub-playlist error: {e}")
            
            init_match = re.search(r'#EXT-X-MAP:URI="(.*?)"', content, re.I)
            if init_match:
                init_url = urljoin(url, init_match.group(1))
                init_resp = requests.get(init_url, headers=req_headers, cookies=cookies, timeout=15)
                if init_resp.status_code == 200:
                    pssh = self._extract_pssh_from_binary(init_resp.content)
                    if pssh:
                        logger.info(f"[{self.SERVICE_NAME}] Found PSSH via Init Segment")
                        return pssh
            
        except Exception as e:
            logger.error(f"[{self.SERVICE_NAME}] Manifest scan error: {e}")
        return None
