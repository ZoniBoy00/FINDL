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

    def is_series(self, url):
        """Checks if the URL is a series/program page."""
        return "/ohjelmat/" in url

    def get_episodes(self, url):
        """Scrapes all episode links from a Ruutu series page, including multiple seasons."""
        with sync_playwright() as p:
            if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=CHROME_UA)
            
            UI.print_step(f"Scraping Ruutu series from [underline]{url}[/underline]", "running")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Click cookie consent
            try:
                for _ in range(2):
                    for btn_text in ["Hyväksy", "Accept", "Salli"]: # Consent button texts: "Hyväksy" (Accept), "Salli" (Allow)
                        btn = page.get_by_role("button", name=btn_text, exact=False)
                        if btn.count() > 0:
                            btn.first.click()
                            page.wait_for_timeout(1500)
                            break
                    else:
                        page.wait_for_timeout(1000)
                        continue
                    break
            except: pass

            episodes = []
            seen_ids = set()

            # Capture series title
            series_title = page.evaluate("() => document.querySelector('h1')?.innerText.trim() || 'Ruutu Original'")
            
            # Helper to extract visible episodes
            def extract_visible(current_season=None):
                # Focus on the main content area
                container = page.query_selector('.SeriesPage, main, #main-content, .SeriesEpisodes') or page
                links = container.query_selector_all('a[href*="/video/"]')
                
                for link in links:
                    href = link.get_attribute("href")
                    if not href: continue
                    
                    match = re.search(r'/video/(\d+)', href)
                    if match:
                        video_id = match.group(1)
                        
                        # Try to get the cleanest title possible
                        title = page.evaluate("""el => {
                            // 1. Try to find a heading in the closest card
                            let card = el.closest('div[class*="Card"], div[class*="Item"], div[class*="Episode"], [data-test*="card"]');
                            if (card) {
                                let h = card.querySelector('h1, h2, h3, h4, [class*="title"], [class*="Title"], [class*="heading"]');
                                if (h && h.innerText.trim().length > 3) return h.innerText;
                                
                                // Alternative: look for text that looks like a title (start with number or long text)
                                let lines = card.innerText.split('\\n').map(l => l.trim()).filter(l => l.length > 5 && !l.includes('play_circle'));
                                if (lines.length > 0) return lines[0];
                            }
                            
                            // 2. Try the link's own text
                            let txt = el.innerText.trim();
                            if (txt.length > 5 && !txt.includes('play_circle')) return txt;
                            
                            return txt;
                        }""", link).strip()
                        
                        # Clean prefixes
                        for prefix in ["Katso:", "Jatka:", "Katso tallennettu:", "Episode:", "Jakso:", "Watch:"]:
                            if title.lower().startswith(prefix.lower()):
                                title = title[len(prefix):].strip()
                        
                        title = title.replace("play_circle_outline", "").strip()
                        if title: title = title.split("\n")[0].strip()
                        
                        # Fallback
                        if not title or len(title) < 2 or title.lower() in ["katso", "jatka", "play"]:
                            title = f"Episode {video_id}"

                        # Check if we already have this ID
                        existing_index = next((i for i, e in enumerate(episodes) if e['id'] == video_id), None)
                        
                        full_url = "https://www.ruutu.fi" + (href if href.startswith("/") else "/" + href)
                        
                        if existing_index is None:
                            episodes.append({
                                "id": video_id,
                                "url": full_url,
                                "title": title,
                                "series": series_title,
                                "season": current_season or "Kausi 1"
                            })
                            seen_ids.add(video_id)
                        else:
                            # If we have a weak title (like "Jakso 1") and now found a better one, update it
                            # Also prioritize items NOT in hero
                            is_hero = page.evaluate("el => !!el.closest('.Hero, .SeriesHero, [class*=\"Hero\"], [class*=\"hero\"]')", link)
                            if not is_hero and (len(title) > len(episodes[existing_index]['title']) or "Episode" in episodes[existing_index]['title']):
                                episodes[existing_index]['title'] = title
                                episodes[existing_index]['url'] = full_url

            # Scroll and check for seasons
            # Look for season tabs/buttons
            season_selectors = [
                'button', 
                '[role="tab"]',
                '.season-selector button',
                'a[href*="/kausi-"]'
            ]
            
            season_texts = []
            seen_names = set()
            
            # First, just collect the names of the seasons
            for sel in season_selectors:
                for el in page.query_selector_all(sel):
                    try:
                        txt = el.inner_text().strip()
                        if not txt: continue
                        txt_up = txt.upper()
                        if ("KAUSI" in txt_up or "SEASON" in txt_up) and el.is_visible():
                            if txt_up not in seen_names:
                                season_texts.append(txt)
                                seen_names.add(txt_up)
                    except: pass
            
            if season_texts:
                UI.print_step(f"Found [bold cyan]{len(season_texts)}[/bold cyan] seasons: {', '.join(season_texts)}", "info")
                
                for txt in season_texts:
                    try:
                        UI.print_step(f"Expanding [bold]{txt}[/bold]...", "info")
                        
                        # Use JavaScript to find and click the element by text
                        # This is much more reliable than Playwright's built-in click which can be picky about visibility/overlays
                        clicked = page.evaluate("""(text) => {
                            const elements = Array.from(document.querySelectorAll('button, [role="tab"], a'));
                            const target = elements.find(el => {
                                const elText = el.innerText.trim().toUpperCase();
                                return elText === text.toUpperCase() || elText.includes(text.toUpperCase());
                            });
                            if (target) {
                                target.scrollIntoView({ block: 'center' });
                                target.click();
                                return true;
                            }
                            return false;
                        }""", txt)
                        
                        if clicked:
                            page.wait_for_timeout(2500) # Give more time for content to switch
                            
                            # Extract episodes for this season
                            last_count = -1
                            for _ in range(3):
                                current_count = len(episodes)
                                extract_visible(current_season=txt)
                                if len(episodes) == current_count: break # No new episodes found
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                page.wait_for_timeout(1500)
                        else:
                            UI.print_step(f"Could not find element for {txt}", "warn")
                            
                    except Exception as e:
                        UI.print_step(f"Error clicking season {txt}: {str(e)}", "warn")
            else:
                # Just scroll and extract if no season buttons found
                for _ in range(5):
                    extract_visible()
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

            browser.close()
            return episodes

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
                for btn_text in ["Hyväksy", "Kyllä", "Accept", "Hyväksy kaikki", "Salli"]: # Consent and confirmation: "Hyväksy" (Accept), "Kyllä" (Yes), "Salli" (Allow)
                    if page.get_by_role("button", name=btn_text, exact=False).count() > 0:
                        page.get_by_role("button", name=btn_text, exact=False).first.click()
                        page.wait_for_timeout(2000)
                        break
                
                for sel in [".play-button", "button.play", ".player-play-button", "[aria-label='Toista']", ".vjs-big-play-button"]: # "Toista" = Play
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
                            "label": "Program subtitles"
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
                                    
                                    # Labelin tunnistus
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
