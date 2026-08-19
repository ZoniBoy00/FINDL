import os
import yt_dlp
import logging
import re
import shutil
import subprocess
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from playwright.sync_api import sync_playwright
from findl.services.base import BaseExtractor
from findl.config import CHROME_UA, SESSION_DIR
from findl.ui.display import UI

class YleExtractor(BaseExtractor):
    def get_service_name(self):
        return "Yle Areena"

    def _extract_with_yle_dl(self, url):
        """Use yle-dl's stream selection when it is installed."""
        executable = shutil.which("yle-dl")
        if not executable:
            return None
        try:
            result = subprocess.run(
                [executable, "--showurl", url],
                capture_output=True, text=True, timeout=90, check=False,
            )
            if result.returncode != 0:
                logging.warning("[YLE] yle-dl stream lookup failed (exit %s)", result.returncode)
                return None
            manifest = next((line.strip() for line in result.stdout.splitlines()
                             if ".m3u8" in line or ".mpd" in line), None)
            if manifest:
                logging.info("[YLE] Stream selected through yle-dl")
                return {"title": None, "manifest_url": manifest}
        except (OSError, subprocess.TimeoutExpired) as exc:
            logging.warning("[YLE] yle-dl lookup unavailable: %s", exc)
        return None

    def _extract_from_player_api(self, url):
        """Read Yle's signed preview metadata endpoint (yle-dl's method)."""
        match = re.search(r"areena\.yle\.fi/(\d-\d+)", url)
        if not match:
            return None
        endpoint = f"https://player.api.yle.fi/v1/preview/{match.group(1)}.json"
        params = {
            "language": "fin", "ssl": "true", "countryCode": "FI",
            "host": "areenaylefi", "app_id": "player_static_prod",
            "app_key": "8930d72170e48303cf5f3867780d549b",
            "isPortabilityRegion": "true",
        }
        try:
            request_url = f"{endpoint}?{urlencode(params)}"
            request = Request(request_url, headers={"User-Agent": CHROME_UA})
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8")).get("data", {}).get("ongoing_ondemand", {})
            manifest = data.get("manifest_url")
            if not manifest:
                return None
            title = (data.get("title") or {}).get("fin") or (data.get("title") or {}).get("swe")
            logging.info("[YLE] Signed manifest selected through player API")
            return {"title": title, "manifest_url": manifest}
        except (HTTPError, URLError, TimeoutError, ValueError, AttributeError, OSError) as exc:
            logging.warning("[YLE] Player API lookup failed: %s", exc)
        return None

    def _extract_with_browser(self, url):
        """Fallback for signed Yle HLS URLs that yt-dlp cannot probe."""
        manifests = []
        title = None
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                SESSION_DIR, headless=True, channel="chrome", user_agent=CHROME_UA,
                args=["--lang=fi-FI,fi"]
            )
            page = context.pages[0] if context.pages else context.new_page()
            self._add_anti_detection(page)

            def capture(response):
                response_url = response.url
                if ".m3u8" in response_url and response_url not in manifests:
                    manifests.append(response_url)

            page.on("response", capture)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Yle places the player behind a consent dialog on a fresh
            # persistent profile. Accept the least surprising option so the
            # player can initialize and expose its signed manifest request.
            for consent_text in ("Vain välttämättömät", "Hyväksy kaikki"):
                try:
                    consent = page.get_by_role("button", name=consent_text)
                    if consent.count():
                        consent.first.click(timeout=3000)
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass
            try:
                title = page.locator("meta[property='og:title']").get_attribute("content")
            except Exception:
                title = None
            # Start playback automatically. On Yle the signed media request
            # is created only after the visible player action is triggered.
            for play_name in ("Toista", "Katso", "Play"):
                try:
                    play_button = page.get_by_role("button", name=re.compile(play_name, re.I))
                    if await_count := play_button.count():
                        play_button.first.click(timeout=3000)
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    pass
            # Fetch the same signed manifest that the Areena player uses,
            # from the page context. This preserves Yle's browser session and
            # avoids Python-side CDN/API restrictions.
            try:
                api_manifest = page.evaluate("""async () => {
                    const match = location.pathname.match(/(\\d-\\d+)/);
                    if (!match) return null;
                    const params = new URLSearchParams({
                      language: 'fin', ssl: 'true', countryCode: 'FI',
                      host: 'areenaylefi', app_id: 'player_static_prod',
                      app_key: '8930d72170e48303cf5f3867780d549b',
                      isPortabilityRegion: 'true'
                    });
                    const response = await fetch(
                      `https://player.api.yle.fi/v1/preview/${match[1]}.json?${params}`
                    );
                    if (!response.ok) return null;
                    return (await response.json())?.data?.ongoing_ondemand?.manifest_url || null;
                }""")
                if api_manifest and api_manifest not in manifests:
                    manifests.insert(0, api_manifest)
                    logging.info("[YLE] Browser selected signed player API manifest")
            except Exception as exc:
                logging.debug("[YLE] Browser player API lookup unavailable: %s", exc)
            page.wait_for_timeout(5000)
            try:
                video = page.locator("video").first
                if video.count():
                    video.click(timeout=3000)
            except Exception:
                pass
            try:
                page.evaluate("document.querySelector('video')?.play()")
            except Exception:
                pass
            page.wait_for_timeout(15000)
            context.close()

        if not manifests:
            logging.error("[YLE] Browser fallback did not observe an HLS manifest")
            return None
        master = next((item for item in manifests if re.search(r"/index\.m3u8(?:\?|$)", item, re.I)), None)
        if not master:
            master = next((item for item in manifests if "master" in item.lower() or "playlist" in item.lower()), None)
        if not master:
            master = next((item for item in manifests if not re.search(r"/index_\d+\.m3u8(?:\?|$)", item, re.I)), None)
        # Yle's player can request only one rendition (for example
        # index_2.m3u8). The signed Akamai path also exposes the parent
        # master under index.m3u8, which is needed for the audio track.
        if not master:
            variant = manifests[0]
            candidate = re.sub(r"/index_\d+(\.m3u8(?:\?.*)?)$", r"/index\1", variant, flags=re.I)
            master = candidate if candidate != variant else variant
            logging.info("[YLE] Using derived master manifest for audio/video selection")
        logging.info(f"[YLE] Browser fallback captured manifest ({len(manifests)} candidate(s))")
        return {"title": title, "manifest_url": master}

    def is_series(self, url):
        """Checks if the URL is a series/playlist page."""
        # Simple heuristic for Yle Areena
        # Series URLs usually have /sarjat/ or /ohjelmat/ and an ID starting with 1-
        if "/sarjat/" in url or "/ohjelmat/" in url:
            return True
        # Special case for some series URLs that look like single videos: https://areena.yle.fi/1-3671655
        if re.search(r'areena\.yle\.fi/\d-\d+', url):
            # We need to check if it's a playlist or single item
            # For now, let's treat these as potential series to allow playlist extraction
            return True
        return False

    def get_episodes(self, url):
        """
        Scrapes episode links and titles from a Yle series page using Playwright.
        Handle seasons and dynamic loading.
        """
        with sync_playwright() as p:
            if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)
            
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=CHROME_UA)
            
            UI.print_step(f"Scraping Yle series from [underline]{url}[/underline]", "running")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Basic wait
            page.wait_for_timeout(3000)
            
            episodes = []
            seen_ids = set()
            
            # Capture series title
            series_title = page.evaluate("() => document.querySelector('h1, [class*=\"series-title\"], [class*=\"program-title\"]')?.innerText.trim() || 'Yle Sarja'")
            
            def extract_visible(current_season=None):
                # Yle episode links usually have /1-XXXXXXX
                # We filter to only include links that are NOT in a recommendation section

                links_data = page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/1-"]'));
                    return links.filter(link => {
                        // Avoid recommendations/headers/footers
                        let parent = link.parentElement;
                        
                        // Check if inside nav or footer
                        if (link.closest('nav') || link.closest('footer')) return false;
                        
                        // Check text for language selectors
                        const text = link.innerText.toLowerCase();
                        if (text.includes("på svenska") || text.includes("in english")) return false;

                        while(parent) {
                            const pText = (parent.innerText || "").toLowerCase();
                            // Strict section filtering for Finnish UI elements
                            if (pText.includes("katso myös") || 
                                pText.includes("suosittelemme") || 
                                pText.includes("aiheesta muualla") ||
                                pText.includes("lisää kohteesta")) {
                                
                                // Verify if it's really a recommendation section (usually small/sidebar)
                                // If it contains a header with these words, it's definitely a recommendation section
                                const h = parent.querySelector('h1, h2, h3, h4, [class*="title"]');
                                if (h && (h.innerText.toLowerCase().includes("katso myös") || 
                                         h.innerText.toLowerCase().includes("suosittelemme"))) return false;
                                         
                                if (parent.classList.contains('related-items') || 
                                    parent.classList.contains('recommendations')) return false;
                            }
                            
                            parent = parent.parentElement;
                        }
                        
                        // Ensure it's part of an episode list structure if possible
                        return !!link.closest('li, [class*="Episode"], [class*="Card"], [class*="PlaylistItem"], [class*="GridItem"]');
                    }).map(link => ({
                        href: link.getAttribute("href"),
                        innerText: link.innerText,
                        html: link.innerHTML,
                        derivedTitle: (() => {
                            let p = link.closest('li, div[class*="Episode"], [class*="Card"], [class*="PlaylistItem"], [class*="GridItem"]') || link;
                            let h = p.querySelector('h1, h2, h3, h4, [class*="title"]');
                            return h ? h.innerText : link.innerText;
                        })()
                    }));
                }""")

                for item in links_data:
                    href = item['href']
                    if not href: continue
                    
                    # IDs are like 1-3671655
                    match = re.search(r'/(1-\d+)', href)
                    if match:
                        video_id = match.group(1)
                        if video_id not in seen_ids:
                            title = item['derivedTitle'].strip()
                            if title:
                                title = title.split("\n")[0].strip()
                                # Clean leading numbers like "1. Uusi naapuri"
                                title = re.sub(r'^\d+\.\s*', '', title)
                            
                            if not title or len(title) < 2:
                                title = f"Episode {video_id}"

                            if href.startswith("http"):
                                full_url = href
                            else:
                                full_url = "https://areena.yle.fi" + (href if href.startswith("/") else "/" + href)
                            
                            episodes.append({
                                "id": video_id,
                                "url": full_url,
                                "title": title,
                                "series": series_title,
                                "season": current_season or "Kausi 1"
                            })
                            seen_ids.add(video_id)

            # Look for season selection buttons/tabs
            try:
                season_texts = page.evaluate(r"""() => {
                    const elements = Array.from(document.querySelectorAll('button, [role="tab"], a, div, li'));
                    const results = [];
                    const seen = new Set();
                    elements.forEach(el => {
                        const txt = el.innerText.trim();
                        // Look for strings like "Kausi 1" (Season 1 in Finnish)
                        if (/^Kausi \d+$/i.test(txt) && !seen.has(txt.toUpperCase())) {
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
                            # Click the season button
                            clicked = page.evaluate("""(text) => {
                                const elements = Array.from(document.querySelectorAll('button, [role="tab"], a, div, li'));
                                const target = elements.find(el => el.innerText.trim().toUpperCase() === text.toUpperCase());
                                if (target) {
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
            except:
                extract_visible()
            
            browser.close()
            return episodes

    def extract(self, url):
        """
        Extraction logic for Yle Areena.
        Uses yt-dlp to extract manifest URL and other details.
        """
        logging.info(f"[YLE] Extracting info for: {url}")
        
        # We use yt-dlp to get the manifest and basic metadata
        # Yle content is usually HLS/DASH.
        
        if "areena.yle.fi" not in url:
            logging.error(f"[YLE] Invalid URL: {url}")
            return None

        api_result = self._extract_from_player_api(url)
        yle_dl_result = api_result or self._extract_with_yle_dl(url)
        if yle_dl_result:
            yle_dl_result.update({
                "subtitles": [], "cookies": {}, "license_url": None,
                "license_headers": {}, "psshs": [], "pssh": None,
                "origin": "https://areena.yle.fi", "series": None,
                "season": None, "episode": None, "is_movie": True,
            })
            return yle_dl_result

        # Prefer the browser-context API before yt-dlp. Yle's CDN signs the
        # manifest for the active browser session, while yt-dlp can return a
        # stale hdntl rendition that N_m3u8DL-RE receives as HTTP 403.
        browser_result = self._extract_with_browser(url)
        if browser_result and browser_result.get("manifest_url"):
            browser_result.update({
                "subtitles": [], "cookies": {}, "license_url": None,
                "license_headers": {}, "psshs": [], "pssh": None,
                "origin": "https://areena.yle.fi", "series": None,
                "season": None, "episode": None, "is_movie": True,
            })
            return browser_result

        # Mimic a real browser to prevent "Connection aborted" or "Remote disconnected"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            # Yle can return signed HLS variants that reject yt-dlp's
            # preliminary format probe with 403 even though the manifest
            # itself is usable by the downloader.
            'check_formats': False,
            'user_agent': CHROME_UA,
            'http_headers': {
                'User-Agent': CHROME_UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://areena.yle.fi/',
                'Origin': 'https://areena.yle.fi',
            }
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            if not info:
                return {"error": "yt-dlp returned no metadata"}

            # Handle entries (take first item if still passed to extract)
            if 'entries' in info:
                logging.warning(f"[YLE] Playlist detected in extract(), taking first item.")
                entries = [e for e in info['entries'] if e]
                if entries:
                    info = entries[0]

            result = {
                "title": info.get('title'),
                "manifest_url": info.get('url'),
                "subtitles": [],
                "cookies": info.get('cookies') or {},
                "license_url": None,
                "license_headers": {},
                "psshs": [],
                "pssh": None,
                "origin": "https://areena.yle.fi",
                "series": None,
                "season": None,
                "episode": None,
                "is_movie": True
            }

            # yt-dlp may return a single video rendition (index_2.m3u8).
            # Yle's signed path also has the parent master manifest, which
            # is required to discover and mux the audio rendition.
            if result["manifest_url"]:
                result["manifest_url"] = re.sub(
                    r"/index_\d+(\.m3u8(?:\?.*)?)$",
                    r"/index\1",
                    result["manifest_url"],
                    flags=re.I,
                )

            # If yt-dlp didn't find manifest in 'url', check 'formats'
            if not result["manifest_url"] and info.get('formats'):
                # Prefer m3u8 or mpd
                for f in reversed(info['formats']): # Go from highest quality down if possible, but mainly find manifest
                    f_url = f.get('url', '')
                    if '.m3u8' in f_url or '.mpd' in f_url or 'manifest' in f_url.lower():
                        result["manifest_url"] = f_url
                        break
                
                # If still none, take the last format as it's often the manifest/best
                if not result["manifest_url"]:
                    result["manifest_url"] = info['formats'][-1].get('url')

            # Cleanup title
            if result["title"]:
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")

            # Extract Subtitles
            if info.get('subtitles'):
                for lang, tracks in info['subtitles'].items():
                    for track in tracks:
                        if track.get('ext') in ['vtt', 'srt']:
                            label = lang
                            if "qag" in lang.lower() or "ohjelma" in lang.lower():
                                label = f"{lang} (Ohjelmatekstitys)"
                            
                            result["subtitles"].append({
                                "url": track.get('url'),
                                "language": lang,
                                "label": label
                            })

            # Deep Scan for PSSH if it's a DASH manifest
            if result["manifest_url"] and ".mpd" in result["manifest_url"]:
                pssh = self.get_pssh_from_manifest(result["manifest_url"])
                if pssh:
                    result["psshs"].append(pssh)
                    result["pssh"] = pssh
                    logging.info(f"[YLE] Found PSSH in DASH manifest")

            return result

        except Exception as e:
            logging.warning(f"[YLE] yt-dlp extraction failed, trying browser manifest fallback: {e}")
            fallback = self._extract_with_browser(url)
            if fallback and fallback.get("manifest_url"):
                fallback.update({
                    "subtitles": [], "cookies": {}, "license_url": None,
                    "license_headers": {}, "psshs": [], "pssh": None,
                    "origin": "https://areena.yle.fi", "series": None,
                    "season": None, "episode": None, "is_movie": True,
                })
                return fallback
            logging.error(f"[YLE] Extraction error: {e}")
            return None

