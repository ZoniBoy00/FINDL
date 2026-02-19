import os
import re
import time
import base64
import logging
import requests
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from pywidevine.license_protocol_pb2 import SignedMessage, LicenseRequest
from .base import BaseExtractor
from ..config import CHROME_UA, SESSION_DIR
from ..ui.display import UI

class RuutuExtractor(BaseExtractor):
    def get_service_name(self):
        return "Ruutu"

    def extract(self, url):
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

            # Anti-detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', {get: () => ['fi-FI', 'fi']});
            """)

            # Relaxed Ad-Blocker (Let video load, block obvious trackers)
            def intercept(route):
                u = route.request.url.lower()
                if any(k in u for k in ["scorecardresearch", "analytics", "googletag", "gemius"]):
                    route.abort()
                else:
                    route.continue_()
            
            page.route("**/*", intercept)

            result = {
                "title": None,
                "manifest_url": None,
                "license_url": None,
                "license_headers": {},
                "psshs": [],
                "pssh": None,
                "subtitles": [],
                "cookies": {},
                "origin": "https://www.ruutu.fi",
                "drm_tokens": [], # For collecting multiple tokens (ads vs content)
                "drm_token": None
            }

            def handle_response(response):
                u = response.url.lower()

                # 1. Manifest Detection (Ignoring Ads)
                is_manifest = (".m3u8" in u or ".mpd" in u) and ".webmanifest" not in u
                if is_manifest and not any(k in u for k in ["vmap", "vast", "doubleclick", "/ads/", "ad-delivery"]):
                    if not result["manifest_url"] or "gatekeeper" in u:
                        result["manifest_url"] = response.url
                        logging.info(f"[RUUTU] Manifest detected: {u[:50]}...")

                # 2. PSSH Sniffing from Init Segments
                if "init.mp4" in u or "init-v1" in u:
                    try:
                        # Only fetch body if it's likely a media init segment
                        body = response.body()
                        pssh = self.parse_pssh_from_init(body)
                        if pssh and pssh not in result["psshs"]:
                            result["psshs"].append(pssh)
                            logging.info(f"[RUUTU] PSSH sniffed from init segment")
                    except Exception as e:
                        pass

                # 3. DRM License & Tokens
                if ("widevine" in u or "acquirelicense" in u) and response.request.method == "POST":
                    # IMPORTANT: Don't overwrite content license URL with ad license URLs
                    if not result["license_url"] or not any(k in u for k in ["vmap", "vast", "/ads/", "doubleclick"]):
                        result["license_url"] = response.url # Keep full URL (needed for CMCD params)
                        
                        # Capture HTTP Headers
                        for k, v in response.request.headers.items():
                            k_lower = k.lower()
                            
                            # General headers needed for license request
                            if k_lower in ['user-agent', 'origin', 'referer', 'authorization', 'content-type'] or k_lower.startswith('x-'):
                                result["license_headers"][k] = v
                            
                            # AXINOM TOKEN (Capture ALL candidates)
                            if k_lower == 'x-axdrm-message':
                                token = v
                                # Only keep as latest if it doesn't look like an ad request (u is the request URL)
                                if not any(k in u for k in ["vmap", "vast", "/ads/", "doubleclick"]):
                                    result["drm_token"] = token 
                                
                                if token not in result["drm_tokens"]:
                                    result["drm_tokens"].append(token)
                                    logging.info("[RUUTU] Axinom Token captured from network")
            
            page.on("response", handle_response)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Interactive Play
            try:
                for btn_text in ["Hyväksy", "Kyllä", "Accept", "Hyväksy kaikki", "Salli"]:
                    if page.get_by_role("button", name=btn_text, exact=False).count() > 0:
                        page.get_by_role("button", name=btn_text, exact=False).first.click()
                        page.wait_for_timeout(2000)
                        break
                
                for sel in [".play-button", "button.play", ".player-play-button", "[aria-label='Toista']", ".vjs-big-play-button"]:
                    btn = page.locator(sel)
                    if btn.count() > 0:
                        btn.first.click()
                        page.wait_for_timeout(2000)
                        break
            except: pass

            # Metadata
            try:
                og_title = page.locator('meta[property="og:title"]').get_attribute('content')
                result["title"] = (og_title or page.title()).split("|")[0].strip()
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")
            except: pass

            # Final Wait Loop (Extended for Ads)
            UI.print_step("Waiting for license data (skip ads)...", "running")
            start = time.time()
            while time.time() - start < 60:
                # Fast-forward ads
                try:
                    page.evaluate("document.querySelectorAll('video').forEach(v => { v.muted = true; v.playbackRate = 16; });")
                except: pass

                if result["manifest_url"] and (result["psshs"] or result["license_url"]):
                    UI.print_step("Manifest & License found, finalizing...", "running")
                    page.wait_for_timeout(3000)
                    break
                page.wait_for_timeout(1000)

            # Deep Scan: Try to find PSSH in manifest if sniffing failed
            if result["manifest_url"]:
                UI.print_step("Refining media info from manifest...", "info")
                cur_cookies = {c['name']: c['value'] for c in context.cookies()}
                headers = {"Origin": "https://www.ruutu.fi", "User-Agent": CHROME_UA}
                
                # 1. PSSH Scan
                if not result["psshs"]:
                    pssh = self.get_pssh_from_manifest(result["manifest_url"], cur_cookies, headers)
                    if pssh:
                        result["psshs"].append(pssh)
                
                # 2. Subtitle Scan
                try:
                    man_subs = self.get_subtitles_from_manifest_url(result["manifest_url"], cur_cookies, headers)
                    if man_subs:
                        existing_urls = set(s['url'] for s in result["subtitles"])
                        for s in man_subs:
                            if s['url'] not in existing_urls:
                                result["subtitles"].append(s)
                                existing_urls.add(s['url'])
                                logging.info(f"[RUUTU] Found subtitle: {s.get('label')} ({s.get('language')})")
                except Exception as e:
                    logging.warning(f"[RUUTU] Subtitle scan failed: {e}")

            # Extra PSSH Scrape from Page Source
            try:
                content = page.content()
                matches = re.findall(r'"pssh(?:"|Value)?"\s*:\s*"([^"]{40,})"', content)
                for m in matches:
                    if m not in result["psshs"]:
                        result["psshs"].append(m)
                        logging.info(f"[RUUTU] Found PSSH in page source")
            except: pass
            
            # Prioritize the tokens list for DRM handler
            if "drm_tokens" not in result: result["drm_tokens"] = []
            if result.get("drm_token") and result["drm_token"] not in result["drm_tokens"]:
                result["drm_tokens"].append(result["drm_token"])

            result["cookies"] = {c['name']: c['value'] for c in context.cookies()}
            result["pssh"] = result["psshs"][0] if result["psshs"] else None
            
            context.close()
            return result

    def get_subtitles_from_manifest_url(self, manifest_url, cookies=None, headers=None):
        subs = []
        try:
            res = requests.get(manifest_url, cookies=cookies, headers=headers, timeout=10)
            if res.status_code == 200:
                content = res.text
                
                # DASH (.mpd) support for Ruutu
                if ".mpd" in manifest_url or "<MPD" in content:
                    # Look for likely subtitle BaseURLs
                    urls = re.findall(r'<BaseURL>(.*?\.vtt|.*?\.srt)</BaseURL>', content)
                    if not urls:
                         # Sometimes it's inside <Representation>...<BaseURL>
                         urls = re.findall(r'<BaseURL>(.*?)</BaseURL>', content)
                         urls = [u for u in urls if ".vtt" in u or ".srt" in u]

                    for u in urls:
                        full_url = urljoin(manifest_url, u)
                        subs.append({
                            "url": full_url,
                            "language": "fi", 
                            "label": "Ohjelmatekstitys"
                        })
                
                # HLS (.m3u8) support
                elif "#EXT-X-MEDIA:TYPE=SUBTITLES" in content:
                    lines = content.splitlines()
                    for line in lines:
                        if line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES"):
                            try:
                                uri_match = re.search(r'URI="([^"]+)"', line)
                                lang_match = re.search(r'LANGUAGE="([^"]+)"', line)
                                name_match = re.search(r'NAME="([^"]+)"', line)
                                char_match = re.search(r'CHARACTERISTICS="([^"]+)"', line)
                                
                                if uri_match:
                                    uri = uri_match.group(1)
                                    full_url = urljoin(manifest_url, uri)
                                    
                                    lang = lang_match.group(1) if lang_match else "fi"
                                    name = name_match.group(1) if name_match else lang
                                    characteristics = char_match.group(1) if char_match else ""
                                    
                                    # Label Detection
                                    label = name
                                    if "public.accessibility.transcribes-spoken-dialog" in characteristics:
                                        label = f"{name} (Ohjelmatekstitys)"
                                    elif "ohjelma" in name.lower() or "program" in name.lower() or "accessibility" in name.lower():
                                        label = f"{name} (Ohjelmatekstitys)"
                                    
                                    if lang == "und": lang = "fi"

                                    subs.append({
                                        "url": full_url,
                                        "language": lang,
                                        "label": label
                                    })
                            except: pass
        except Exception as e:
            logging.warning(f"[RUUTU] Failed to fetch manifest subs: {e}")
        return subs
