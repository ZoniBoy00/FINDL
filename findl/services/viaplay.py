import os
import re
import time
import base64
import logging
import json
from playwright.sync_api import sync_playwright
from pywidevine.license_protocol_pb2 import SignedMessage, LicenseRequest
from .base import BaseExtractor
from ..config import CHROME_UA, SESSION_DIR
from ..ui.display import UI

class ViaplayExtractor(BaseExtractor):
    def get_service_name(self):
        return "Viaplay"

    def is_series(self, url):
        """Checks if the URL is a series page."""
        return "/sarjat/" in url or "/tv/" in url

    def get_episodes(self, url):
        """
        Scrapes episode links from a Viaplay series page.
        Note: This is a basic implementation using Playwright to find episode links.
        """
        with sync_playwright() as p:
            if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=CHROME_UA)
            
            UI.print_step(f"Scraping Viaplay series from [underline]{url}[/underline]", "running")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Click cookie consent
            try:
                for _ in range(2):
                    # Check for consent buttons: "Hyväksy" (Accept)
                    for sel in ["#accept-all-button", "button:has-text('Hyväksy')", "button:has-text('Accept')"]:
                        if page.locator(sel).count() > 0:
                            page.locator(sel).first.click()
                            page.wait_for_timeout(1000)
                            break
                    else:
                        page.wait_for_timeout(1000)
                        continue
                    break
            except: pass

            page.wait_for_timeout(2000)

            # Capture series title
            series_title = page.evaluate("() => document.querySelector('h1, [class*=\"Header-title\"]')?.innerText.trim() || 'Viaplay Sarja'")

            episodes = []
            seen_urls = set()

            # Helper to extract visible episodes
            def extract_visible(current_season=None):
                # We focus on the episode list container
                links_data = page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/sarjat/"]'));
                    return links.map(link => ({
                        href: link.getAttribute("href"),
                        innerText: link.innerText,
                        // Try to get title from surrounding context
                        derivedTitle: (() => {
                            let p = link.closest('li, [class*="Item"], [class*="Episode"]') || link;
                            let h = p.querySelector('h1, h2, h3, h4, [class*="title"], [class*="Title"]');
                            return h ? h.innerText : link.innerText;
                        })()
                    })).filter(item => {
                        const h = item.href;
                        // Avoid season-only links or the main series page itself
                        if (!h || h.includes("/kaudet/") || h.includes("/seasons/")) return false;
                        return true;
                    });
                }""")

                for item in links_data:
                    href = item['href']
                    if href.rstrip("/") == url.rstrip("/"): continue
                    
                    if not href.startswith("http"):
                        full_url = "https://viaplay.fi" + (href if href.startswith("/") else "/" + href)
                    else:
                        full_url = href
                    
                    if full_url not in seen_urls:
                        title = item['derivedTitle'].strip()
                        if not title or len(title) < 2:
                            title = item['innerText'].strip() or "Episode"
                        
                        if title:
                            title = title.split("\n")[0].strip()
                        
                        episodes.append({
                            "url": full_url,
                            "title": title or "Episode",
                            "series": series_title,
                            "season": current_season or "Season 1"
                        })
                        seen_urls.add(full_url)

            # Look for season selection
            try:
                # Viaplay seasons are often in buttons, list items or spans that act as buttons
                # We'll use a robust JS approach similar to Ruutu/Katsomo
                season_texts = page.evaluate(r"""() => {
                    const elements = Array.from(document.querySelectorAll('button, [role="tab"], li, span, div, a'));
                    const seen = new Set();
                    const results = [];
                    elements.forEach(el => {
                        const txt = el.innerText.trim();
                        // Look for "Kausi X" (Season X in Finnish) or "Season X"
                        if (/^(Kausi|Season) \d+$/i.test(txt) && !seen.has(txt.toUpperCase())) {
                            results.push(txt);
                            seen.add(txt.toUpperCase());
                        }
                    });
                    return results;
                }""")
                
                if season_texts and len(season_texts) > 1:
                    UI.print_step(f"Found [bold cyan]{len(season_texts)}[/bold cyan] seasons: {', '.join(season_texts)}", "info")
                    for txt in season_texts:
                        try:
                            UI.print_step(f"Expanding [bold]{txt}[/bold]...", "info")
                            # Use JS to click the target safely
                            clicked = page.evaluate("""(text) => {
                                const elements = Array.from(document.querySelectorAll('button, [role="tab"], li, span, a, div'));
                                const target = elements.find(el => el.innerText.trim().toUpperCase() === text.toUpperCase());
                                if (target) {
                                    target.scrollIntoView({ block: 'center' });
                                    target.click();
                                    return true;
                                }
                                return false;
                            }""", txt)
                            
                            if clicked:
                                page.wait_for_timeout(2500)
                                extract_visible(current_season=txt)
                        except: pass
                else:
                    extract_visible()
            except Exception as e:
                logging.debug(f"[VIAPLAY] Season detection error: {e}")
                extract_visible()
            
            browser.close()
            return episodes

    def extract(self, url):
        """
        Main extraction logic for Viaplay.
        Uses Playwright to navigate, intercept network traffic, and extract playback details.
        Inspired by logic from the Kodi Viaplay plugin for metadata and endpoint discovery.
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
                ]
            )
            page = context.pages[0] if context.pages else context.new_page()

            # Anti-detection script
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
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
                "origin": "https://viaplay.fi",
                "metadata": {}
            }

            def handle_response(response):
                # Capture Stream/Product JSON Data (contains subtitles and license info)
                # Viaplay uses /stream/ for playback info and /product/ or /content/ for metadata
                if "viaplay.fi" in response.url and ("/stream/" in response.url or "/product/" in response.url or "/content/" in response.url):
                    try:
                        data = response.json()
                        
                        # Extract Metadata and Title
                        content = data.get("content", {})
                        if not content and "_embedded" in data:
                            content = data["_embedded"].get("viaplay:product", {}).get("content", {})
                        
                        if content:
                            # Try to build a better title (Series - S01E01 - Title)
                            series = content.get("series", {})
                            title = content.get("title")
                            
                            if series:
                                s_title = series.get("title")
                                season = content.get("season", {}).get("seasonNumber")
                                episode = content.get("episodeNumber")
                                if s_title and season and episode:
                                    result["title"] = f"{s_title}_S{int(season):02d}E{int(episode):02d}_{title}"
                                elif s_title:
                                    result["title"] = f"{s_title}_{title}"
                            
                            if not result["title"] and title:
                                result["title"] = title

                            # Capture extra metadata
                            result["metadata"].update({
                                "year": content.get("production", {}).get("year"),
                                "synopsis": content.get("synopsis"),
                                "duration": content.get("duration", {}).get("milliseconds")
                            })

                        # Extract manifest URL from _links (Kodi plugin logic)
                        links = data.get("_links", {})
                        for key in ["viaplay:media", "viaplay:playlist", "viaplay:encryptedPlaylist", "viaplay:fallbackMedia"]:
                            if key in links:
                                link_data = links[key]
                                if isinstance(link_data, list):
                                    result["manifest_url"] = link_data[0]["href"]
                                else:
                                    result["manifest_url"] = link_data["href"]
                                break

                        # Extract Subtitles (SAMI format preferred by Viaplay)
                        if "viaplay:sami" in links:
                            for s in links["viaplay:sami"]:
                                s_url = s.get("href")
                                if s_url:
                                    lang = s.get("language") or s.get("lang") or "fi"
                                    result["subtitles"].append({
                                        "url": s_url,
                                        "language": lang,
                                        "label": f"Viaplay {lang.upper()}"
                                    })
                        
                    except: pass

                # Capture License Request (Widevine)
                # Kodi plugin mentions play.viaplay.{tld}/api/license
                is_lic = any(kw in response.url for kw in ["/api/license", "play.viaplay", "lic.widevine.com"])
                if is_lic and response.request.method == "POST":
                    result["license_url"] = response.url
                    
                    # Capture License Headers (Auth tokens etc)
                    for h, v in response.request.headers.items():
                        h_lower = h.lower()
                        # Viaplay often uses 'authorization' or custom 'x-vmp-' headers
                        if any(kw in h_lower for kw in ['authorization', 'x-vmp-', 'cookie', 'token', 'x-viaplay']):
                            result["license_headers"][h] = v
                            
                    # Sniff PSSH from challenge body if possible
                    try:
                        body = response.request.post_data_buffer
                        if body:
                            msg = SignedMessage()
                            msg.ParseFromString(body)
                            req = LicenseRequest()
                            req.ParseFromString(msg.msg)
                            if req.contentId.widevinePsshData.psshData:
                                for p_bin in req.contentId.widevinePsshData.psshData:
                                    p_b64 = base64.b64encode(p_bin).decode()
                                    if p_b64 not in result["psshs"]:
                                        result["psshs"].append(p_b64)
                    except: pass

                # Capture manifest URL directly from network if not in JSON (fallback)
                if (".mpd" in response.url or ".m3u8" in response.url) and not any(k in response.url for k in ["vmap", "vast", "ads"]):
                    if not result["manifest_url"] or "encrypted" in response.url:
                        result["manifest_url"] = response.url

            page.on("response", handle_response)
            
            # Navigate to URL
            UI.print_step(f"Navigating to {url}", "info")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Interactive Play / Consent handling
            try:
                # Cookie Banner: "Hyväksy" (Accept)
                for sel in ["#accept-all-button", "button:has-text('Hyväksy')", "button:has-text('Accept')", ".accept-all"]:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        page.wait_for_timeout(1000)
                        break
                
                # Check for "Katso" (Watch) or "Vuokraa" (Rent) or play link
                # Kodi plugin uses 'play-link' data-test-id
                for sel in ["a[data-test-id='play-link']", "button:has-text('Katso')", "button:has-text('Watch')", ".PlayButton", ".Viaplay-Player"]:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        page.wait_for_timeout(2000)
                        break
            except: pass

            # Extract Title from page meta if still missing
            if not result["title"]:
                try:
                    og_title = page.locator('meta[property="og:title"]').get_attribute('content')
                    result["title"] = og_title or page.title()
                except: pass

            if result["title"]:
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")

            # Wait for data
            UI.print_step("Waiting for license data... (Login now if needed)", "running")
            start = time.time()
            max_wait = 120 
            
            while time.time() - start < max_wait:
                if result["manifest_url"] and result["license_url"]:
                    # Small extra wait to ensure headers are fully captured
                    page.wait_for_timeout(3000)
                    break
                
                # Try to trigger playback even if button click failed
                if (time.time() - start) > 15:
                    page.evaluate("if(document.querySelector('video')) document.querySelector('video').play()")
                    
                page.wait_for_timeout(1500)

            # Final PSSH check from manifest if needed
            if not result["psshs"] and result["manifest_url"]:
                UI.print_step("PSSH missing, deep scanning manifest...", "info")
                cur_cookies = {c['name']: c['value'] for c in context.cookies()}
                pssh = self.get_pssh_from_manifest(result["manifest_url"], cur_cookies, result["license_headers"])
                if pssh:
                    result["psshs"].append(pssh)

            result["cookies"] = {c['name']: c['value'] for c in context.cookies()}
            result["pssh"] = result["psshs"][0] if result["psshs"] else None
            
            context.close()
            return result

