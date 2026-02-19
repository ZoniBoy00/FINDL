import os
import re
import time
import base64
import logging
import requests
from playwright.sync_api import sync_playwright
from pywidevine.license_protocol_pb2 import SignedMessage, LicenseRequest
from .base import BaseExtractor
from ..config import CHROME_UA, SESSION_DIR
from ..ui.display import UI

class KatsomoExtractor(BaseExtractor):
    def get_service_name(self):
        return "MTV Katsomo"


    
    def extract(self, url):
        """
        Main extraction logic for MTV Katsomo.
        Uses Playwright to navigate, intercept network traffic, and extract playback details.
        
        Args:
            url (str): The video URL to process.
            
        Returns:
            dict: Dictionary containing manifest_url, keys (via DRM handler), subtitles, etc.
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

            # Anti-detection script
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', {get: () => ['fi-FI', 'fi']});
            """)

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
                "origin": "https://www.mtv.fi"
            }

            def handle_response(response):
                # Capture Playback JSON Data
                if "a2d.tv" in response.url and "playback" in response.url:
                    try:
                        data = response.json()
                        json_str = response.text()
                        
                        # Sniff PSSH from JSON (some manifests are clean, but JSON has it)
                        matches = re.findall(r'"pssh":"([^"]{40,})"', json_str)
                        for m in matches:
                            if m not in result["psshs"]:
                                result["psshs"].append(m)
                                logging.info(f"[KATSOMO] PSSH found in playback JSON")

                        pb = data.get("playbackItem", {}) or data.get("playback", {})
                        if isinstance(pb, list): pb = pb[0]

                        # Manifest URL
                        if pb.get("manifestUrl"): 
                            result["manifest_url"] = pb["manifestUrl"]
                        
                        # DRM Token (castlabsToken)
                        lic_data = pb.get("license", {}) or pb.get("drm", {}).get("widevine", {})
                        token = lic_data.get("castlabsToken") or lic_data.get("drmToken") or lic_data.get("token")
                        if token:
                            result["drm_token"] = token
                        
                        # Subtitles from JSON
                        subs = pb.get("subtitles") or pb.get("subtitle") or []
                        caps = pb.get("captions") or pb.get("closedCaptions") or []
                        
                        all_raw_subs = []
                        if isinstance(subs, list): all_raw_subs.extend(subs)
                        if isinstance(caps, list): all_raw_subs.extend(caps)
                            
                        seen_urls = set()
                        for s in all_raw_subs:
                            url = s.get('url')
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                lang = s.get('language') or s.get('lang') or 'fi'
                                label = s.get('label') or s.get('type')
                                result["subtitles"].append({
                                    "url": url, 
                                    "language": lang,
                                    "label": label
                                })
                    except: pass

                # Capture License Request (Widevine)
                is_lic = any(kw in response.url for kw in ["lic.drmtoday.com", "lic.widevine.com", "license"])
                if is_lic and response.request.method == "POST":
                    result["license_url"] = response.url
                    
                    # Sniff PSSH from License Challenge Body if possible
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
                                        logging.info(f"[KATSOMO] PSSH sniffed from network challenge")
                        except: pass
                    
                    # Capture License Headers (Auth tokens etc)
                    for h, v in response.request.headers.items():
                        if h.lower().startswith('x-dt-') or h.lower() == 'authorization':
                            result["license_headers"][h] = v

            page.on("response", handle_response)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Interactive Play (Force video load to trigger network requests)
            try:
                # Click Cookie Banner
                for sel in ["#accept-all-button", "#consent_prompt_submit", "text='Hyväksy kaikki'"]:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        page.wait_for_timeout(1000)
                        break
                
                # Click Play Button
                for sel in ["button.play", "[data-test='play-button']", "text='Katso'", ".vjs-big-play-button"]:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        page.wait_for_timeout(2000)
                        break
            except: pass

            # Extract Metadata
            try:
                og_title = page.locator('meta[property="og:title"]').get_attribute('content')
                result["title"] = (og_title or page.title()).split("|")[0].strip()
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")
            except: pass

            # Final Wait Loop
            UI.print_step("Waiting for license data... (Login now if needed)", "running")
            start = time.time()
            max_wait = 120 
            
            while time.time() - start < max_wait:
                if result["manifest_url"] and result["license_url"]:
                    page.wait_for_timeout(2000)
                    break
                
                if (time.time() - start) > 15 and not result["license_url"]:
                    try:
                        page.evaluate("if(document.querySelector('video')) document.querySelector('video').play()")
                    except: pass
                    
                page.wait_for_timeout(1000)

            # Deep Scan: Try to find PSSH in manifest if sniffing failed
            if not result["psshs"] and result["manifest_url"]:
                UI.print_step("Sniffing failed, deep scanning manifest...", "info")
                cur_cookies = {c['name']: c['value'] for c in context.cookies()}
                headers = {"Origin": "https://www.mtv.fi", "Referer": "https://www.mtv.fi/"}
                pssh = self.get_pssh_from_manifest(result["manifest_url"], cur_cookies, headers)
                if pssh:
                    result["psshs"].append(pssh)
                    logging.info(f"[KATSOMO] Found PSSH via deep scan")

            # Always scan manifest for subtitles to find program subtitles (qag)
            if result["manifest_url"]:
                try:
                    man_subs = self.get_subtitles_from_manifest_url(result["manifest_url"])
                    if man_subs:
                        existing_urls = set(s['url'] for s in result["subtitles"])
                        for s in man_subs:
                            if s['url'] not in existing_urls:
                                result["subtitles"].append(s)
                                existing_urls.add(s['url'])
                                logging.info(f"[KATSOMO] Found subtitle in manifest: {s.get('label')}")
                except Exception as e:
                    logging.warning(f"[KATSOMO] Manifest subtitle scan failed: {e}")

            # Extra PSSH Scrape from Page Source
            try:
                content = page.content()
                matches = re.findall(r'"pssh(?:"|Value)?"\s*:\s*"([^"]{40,})"', content)
                for m in matches:
                    if m not in result["psshs"]:
                        result["psshs"].append(m)
            except: pass

            result["cookies"] = {c['name']: c['value'] for c in context.cookies()}
            result["pssh"] = result["psshs"][0] if result["psshs"] else None
            
            context.close()
            return result

    def get_subtitles_from_manifest_url(self, manifest_url):
        subs = []
        try:
            res = requests.get(manifest_url, headers={"User-Agent": CHROME_UA, "Origin": "https://www.mtv.fi"})
            if res.status_code == 200:
                lines = res.text.splitlines()
                # Parse EXT-X-MEDIA:TYPE=SUBTITLES
                for line in lines:
                    if line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"):
                        try:
                            uri_match = re.search(r'URI="([^"]+)"', line)
                            lang_match = re.search(r'LANGUAGE="([^"]+)"', line)
                            name_match = re.search(r'NAME="([^"]+)"', line)
                            char_match = re.search(r'CHARACTERISTICS="([^"]+)"', line) # e.g. public.accessibility.transcribes-spoken-dialog
                            
                            if uri_match:
                                uri = uri_match.group(1)
                                # Resolve relative URI
                                if not uri.startswith("http"):
                                    base = manifest_url.rsplit("/", 1)[0]
                                    if uri.startswith("/"):
                                        uri = "/".join(manifest_url.split("/")[:3]) + uri
                                    else:
                                        uri = f"{base}/{uri}"
                                
                                lang = lang_match.group(1) if lang_match else "unknown"
                                name = name_match.group(1) if name_match else lang
                                characteristics = char_match.group(1) if char_match else ""
                                
                                label = name
                                if "accessibility" in characteristics or "program" in name.lower() or "ohjelma" in name.lower():
                                    label = f"{name} (Ohjelmatekstitys)"
                                
                                subs.append({
                                    "url": uri,
                                    "language": lang,
                                    "label": label
                                })
                        except: pass
        except Exception as e:
            logging.warning(f"[KATSOMO] Failed to fetch manifest subs: {e}")
        return subs
