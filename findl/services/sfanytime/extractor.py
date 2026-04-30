import os
import re
import time
import base64
import logging
import requests
from playwright.sync_api import sync_playwright
from pywidevine.license_protocol_pb2 import SignedMessage, LicenseRequest
from findl.services.base import BaseExtractor
from findl.config import CHROME_UA, SESSION_DIR
from findl.ui.display import UI

class SfAnytimeExtractor(BaseExtractor):
    def get_service_name(self):
        return "SF Anytime"

    def is_series(self, url):
        return False

    def get_episodes(self, url):
        return []

    def extract(self, url):
        """
        Main extraction logic for SF Anytime.
        Uses Playwright to navigate and intercept license/manifest.
        """
        with sync_playwright() as p:
            if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)
            
            context = p.chromium.launch_persistent_context(
                SESSION_DIR,
                headless=False,
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

            result = {
                "title": None,
                "manifest_url": None,
                "license_url": None,
                "license_headers": {},
                "psshs": [],
                "pssh": None,
                "drm_token": None,
                "subtitles": [],
                "cookies": {},
                "origin": "https://www.sfanytime.com",
                "is_movie": True
            }

            def handle_response(response):
                # Capture Manifest URLs
                if (".mpd" in response.url or ".m3u8" in response.url) and response.status == 200:
                    if not result["manifest_url"] or ".mpd" in response.url:
                        result["manifest_url"] = response.url
                        logging.info(f"[SFANYTIME] Manifest found: {response.url}")
                        
                        # Try to get PSSH from manifest content immediately
                        try:
                            content = response.text()
                            pssh = self.get_pssh_from_manifest_text(content)
                            if pssh and pssh not in result["psshs"]:
                                result["psshs"].append(pssh)
                                logging.info(f"[SFANYTIME] PSSH sniffed from manifest")
                        except: pass

                # Capture License Request
                is_lic = any(kw in response.url.lower() for kw in ["widevine", "license", "lic-wv", "axinom"])
                if is_lic and response.request.method == "POST":
                    result["license_url"] = response.url
                    logging.info(f"[SFANYTIME] License URL found: {response.url}")
                    
                    # Capture token from URL params if present
                    if "?" in response.url:
                         from urllib.parse import urlparse, parse_qs
                         params = parse_qs(urlparse(response.url).query)
                         for k, v in params.items():
                             if any(kw in k.lower() for kw in ['token', 'msg', 'auth']):
                                 result["drm_token"] = v[0]
                                 logging.info(f"[SFANYTIME] Captured token from URL: {k}={v[0][:20]}...")
                    
                    # Capture License Headers
                    for h, v in response.request.headers.items():
                        if h.lower() in ['authorization', 'x-axinom-drm-token', 'x-axdrm-message', 'x-ax-drm-message', 'x-axinom-message']:
                            result["license_headers"][h] = v
                            if h.lower() in ['x-axinom-drm-token', 'x-axdrm-message', 'x-ax-drm-message', 'x-axinom-message']:
                                result["drm_token"] = v
                            elif h.lower() == 'authorization' and not result["drm_token"]:
                                result["drm_token"] = v

                    # Sniff PSSH from License Challenge
                    body = response.request.post_data_buffer
                    if body:
                        try:
                            msg = SignedMessage()
                            msg.ParseFromString(body)
                            req = LicenseRequest()
                            req.ParseFromString(msg.msg)
                            if req.contentId.widevinePsshData.psshData:
                                for p_bin in req.contentId.widevinePsshData.psshData:
                                    p_b64 = base64.b64encode(p_bin).decode()
                                    if p_b64 not in result["psshs"]:
                                        result["psshs"].append(p_b64)
                                        logging.info(f"[SFANYTIME] PSSH sniffed from license challenge")
                        except: pass

            page.on("response", handle_response)
            
            # Navigate to URL
            UI.print_step(f"Navigating to [underline]{url}[/underline]", "running")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logging.warning(f"[SFANYTIME] Page load error: {e}")

            # Basic interactions to trigger video
            try:
                # Click Cookie Banner
                for sel in ["#accept-all-button", "button:has-text('Hyväksy')", "button:has-text('Accept')"]:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        page.wait_for_timeout(1000)
                        break
                
                # Check for Play Button
                for sel in ["button[aria-label*='Play']", ".play-button", "text='Katso'", "text='Play'"]:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        page.wait_for_timeout(2000)
                        break
            except: pass

            # Extract Title
            try:
                result["title"] = page.evaluate("() => document.querySelector('h1')?.innerText || document.title.split('|')[0]").strip()
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")
            except:
                result["title"] = "SF_Anytime_Video"

            # Waiting loop
            UI.print_step("Waiting for license/manifest data... (Login/Rent if needed)", "running")
            start = time.time()
            max_wait = 90
            
            while (time.time() - start < max_wait):
                if result["manifest_url"] and result["license_url"]:
                    # Wait a bit more to ensure PSSH is captured
                    if result["psshs"]:
                        page.wait_for_timeout(2000)
                        break
                
                # If we have manifest but no PSSH, try deep scan
                if result["manifest_url"] and (time.time() - start) > 30:
                    pssh = self.get_pssh_from_manifest(result["manifest_url"], headers={"Origin": "https://www.sfanytime.com"})
                    if pssh:
                        result["psshs"].append(pssh)
                        break

                page.wait_for_timeout(1000)
                if int(time.time() - start) % 15 == 0:
                    logging.info(f"[SFANYTIME] Still waiting... (elapsed: {int(time.time() - start)}s)")

            result["cookies"] = {c['name']: c['value'] for c in context.cookies()}
            result["pssh"] = result["psshs"][0] if result["psshs"] else None
            
            context.close()
            return result

    def get_pssh_from_manifest_text(self, content):
        """Helper to find PSSH in manifest text."""
        # DASH
        match = re.search(r'<(?:[a-zA-Z0-9]+:)?pssh[^>]*>(.*?)</(?:[a-zA-Z0-9]+:)?pssh>', content, re.I | re.S)
        if match: return match.group(1).strip()
        
        # Raw base64 scan
        common_pssh_matches = re.findall(r'([a-zA-Z0-9+/=]{60,})', content)
        for candidate in common_pssh_matches:
            if "cHNzaA" in candidate: return candidate
            
        return None
