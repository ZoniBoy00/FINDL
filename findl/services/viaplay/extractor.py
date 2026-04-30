import os
import re
import time
import base64
import logging
import json
import requests
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from pywidevine.license_protocol_pb2 import SignedMessage, LicenseRequest
from ..base import BaseExtractor
from ...config import CHROME_UA, SESSION_DIR
from ...ui.display import UI

class ViaplayExtractor(BaseExtractor):
    def get_service_name(self):
        return "Viaplay"

    def is_series(self, url):
        """Checks if the URL is a series page."""
        url_lower = url.lower()
        # Viaplay series pages: /sarjat/[slug], /tv/[slug], /elokuvat/ is movies
        if "/sarjat/" in url_lower or "/tv/" in url_lower or "/series/" in url_lower:
            # Exclude direct video/player URLs
            if "/player/" in url_lower or "/watch/" in url_lower:
                return False
            return True
        return False

    def get_episodes(self, url):
        """
        Fetches all episode links from a Viaplay series using the Content API.
        Much more reliable than browser scraping - gets ALL seasons and episodes.
        API: https://content.viaplay.fi/pc-fi/sarjat/{slug}?deviceKey=pcdash&azp=0
        """
        import requests

        # Extract series slug from input URL
        parsed_series_url = urlparse(url)
        series_path_parts = parsed_series_url.path.strip('/').split('/')
        # Handle URLs like /sarjat/seal-team or /tv/seal-team
        if len(series_path_parts) > 1 and series_path_parts[0] in ('sarjat', 'tv'):
            series_slug = series_path_parts[1]
            category = series_path_parts[0]
        else:
            series_slug = series_path_parts[-1]
            category = 'sarjat'

        UI.print_step(f"Fetching series data via Viaplay API for [bold white]{series_slug}[/bold white]", "running")

        # Fetch series page from Content API
        api_url = f"https://content.viaplay.fi/pc-fi/{category}/{series_slug}?deviceKey=pcdash&azp=0"
        headers = {
            'User-Agent': CHROME_UA,
            'Accept': 'application/json',
        }

        try:
            resp = requests.get(api_url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logging.error(f"[VIAPLAY] Failed to fetch series API: {e}")
            UI.print_step(f"API fetch failed: {e}", "error")
            return []

        # Extract series title from API response
        series_title = "Viaplay Sarja"
        try:
            blocks = data.get('_embedded', {}).get('viaplay:blocks', [])
            for block in blocks:
                if block.get('type') == 'article':
                    article = block.get('_embedded', {}).get('viaplay:article', {})
                    series_title = article.get('content', {}).get('title', series_title)
                    break
        except:
            pass

        episodes = []
        seen_ids = set()

        # Find all season-list blocks
        blocks = data.get('_embedded', {}).get('viaplay:blocks', [])
        season_blocks = [b for b in blocks if b.get('type') == 'season-list']

        UI.print_step(f"Found [bold cyan]{len(season_blocks)}[/bold cyan] season(s) for {series_title}", "info")

        for season_block in season_blocks:
            season_number = season_block.get('title', '1')  # "1", "2", etc.
            season_label = f"Kausi {season_number}"
            total_episodes = season_block.get('totalProductCount', 0)

            # Check if this season has embedded products (season 1 usually does)
            embedded_products = season_block.get('_embedded', {}).get('viaplay:products', [])

            if not embedded_products:
                # Need to fetch this season's episodes from the API
                season_api_url = season_block.get('_links', {}).get('self', {}).get('href', '')
                if season_api_url:
                    UI.print_step(f"Fetching {season_label} ({total_episodes} episodes)...", "info")
                    try:
                        season_resp = requests.get(season_api_url, headers=headers, timeout=30)
                        season_resp.raise_for_status()
                        season_data = season_resp.json()
                        embedded_products = season_data.get('_embedded', {}).get('viaplay:products', [])
                    except Exception as e:
                        logging.error(f"[VIAPLAY] Failed to fetch {season_label}: {e}")
                        UI.print_step(f"Failed to fetch {season_label}: {e}", "warn")
                        continue
            else:
                UI.print_step(f"Processing {season_label} ({total_episodes} episodes)...", "info")

            for product in embedded_products:
                if product.get('type') != 'episode':
                    continue

                public_path = product.get('publicPath', '')
                if not public_path:
                    continue

                # Build episode URL
                ep_url = f"https://viaplay.fi/{category}/{public_path}"

                # Dedup by publicPath
                if public_path in seen_ids:
                    continue
                seen_ids.add(public_path)

                # Extract episode metadata
                content = product.get('content', {})
                ep_title = content.get('title', '')
                series_info = content.get('series', {})
                ep_number = series_info.get('episodeNumber', 0)
                ep_display_title = series_info.get('episodeTitle', '')

                # Use the formatted episode title if available (e.g. "1. Tip of the Spear")
                if ep_display_title:
                    title = ep_display_title
                elif ep_title:
                    title = f"{ep_number}. {ep_title}" if ep_number else ep_title
                else:
                    title = f"Jakso {ep_number}" if ep_number else public_path.split('/')[-1]

                episodes.append({
                    "url": ep_url,
                    "title": title,
                    "series": series_title,
                    "season": season_label
                })

        # Sort by season number, then episode number
        def get_sort_key(ep):
            season_str = ep.get('season', 'Kausi 1')
            season_num = int(re.search(r'\d+', season_str).group()) if re.search(r'\d+', season_str) else 1
            title = ep.get('title', '')
            episode_num = int(re.search(r'\d+', title).group()) if re.search(r'\d+', title) else 0
            return (season_num, episode_num)

        episodes.sort(key=get_sort_key)

        total = len(episodes)
        if total > 0:
            UI.print_step(f"Found [bold green]{total}[/bold green] total episodes across {len(season_blocks)} seasons", "success")
        else:
            UI.print_step("No episodes found via API", "warn")

        return episodes

    def extract(self, url):
        """
        Main extraction logic for Viaplay.
        Uses Playwright to navigate, intercept network traffic, and extract playback details.
        Inspired by logic from the Kodi Viaplay plugin for metadata and endpoint discovery.
        """
        # Try to resolve slug from URL
        slug = None
        if "/player/default/" in url:
            # Handle potential double slashes
            path_part = url.split("/player/default/")[-1].lstrip("/")
            slug = path_part.strip("/")
        elif "viaplay.fi" in url:
            path = urlparse(url).path.strip("/")
            if path: slug = path
        
        UI.print_step(f"Resolved slug: [bold white]{slug or 'Unknown'}[/bold white]", "info")
        
        # Pre-emptive metadata fetch if possible
        api_info = {}
        if slug:
            try:
                # We can try to fetch metadata directly to speed things up
                api_url = f"https://content.viaplay.fi/pc-fi/content/{slug}?deviceKey=pcdash&azp=0"
                UI.print_step(f"Fetching API metadata...", "running")
                resp = requests.get(api_url, timeout=10)
                if resp.status_code == 200:
                    api_info = resp.json()
                    UI.print_step("Got metadata from API.", "success")
            except Exception as e:
                logging.debug(f"[VIAPLAY] API fetch error: {e}")

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
                "_api_license_url": None,
                "license_headers": {},
                "psshs": [],
                "pssh": None,
                "drm_token": None,
                "subtitles": [],
                "cookies": {},
                "origin": "https://viaplay.fi",
                "metadata": {},
                "series": None,
                "season": None,
                "episode": None,
                "is_movie": True
            }

            # Seed with API data if we got it
            if api_info:
                content = api_info.get("content", api_info)
                title = content.get("title")
                if title: result["title"] = title
                result["metadata"].update({
                    "year": content.get("production", {}).get("year"),
                    "synopsis": content.get("synopsis"),
                    "duration": content.get("duration", {}).get("milliseconds")
                })
                # Check for series info
                series = content.get("series", {})
                if series:
                    result["is_movie"] = False
                    result["series"] = series.get("title")
                    result["season"] = content.get("season", {}).get("seasonNumber")
                    result["episode"] = content.get("episodeNumber")

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
                        
                        if not content and "title" in data: # Direct metadata response
                            content = data
                        
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

                        # Look for license/drm links in the API response
                        # NOTE: Don't set result["license_url"] from API here.
                        # The browser must trigger its own Widevine POST so we can capture auth headers.
                        # Store API license as fallback only.
                        for lic_key in ["viaplay:license", "viaplay:drm", "viaplay:widevine"]:
                            if lic_key in links:
                                lic_data = links[lic_key]
                                if isinstance(lic_data, list):
                                    result["_api_license_url"] = lic_data[0]["href"]
                                else:
                                    result["_api_license_url"] = lic_data["href"]
                                UI.print_step(f"[dim]Found API license URL ({lic_key}), waiting for browser auth...[/dim]", "info")
                                break

                        # Look for DRM tokens in various places
                        if not result.get("drm_token"):
                            # Check content.drm or content.stream.drm
                            drm_info = content.get("drm") or data.get("drm") or {}
                            if isinstance(drm_info, dict):
                                token = drm_info.get("token") or drm_info.get("drmToken") or drm_info.get("widevineToken")
                                if token:
                                    result["drm_token"] = token
                                    UI.print_step("Found DRM token in API metadata.", "success")

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

                        # Store raw data for debugging/extra info
                        result["metadata"]["raw"] = data

                    except Exception as e:
                        logging.debug(f"[VIAPLAY] Response parsing error: {e}")

                # Capture License Request (Widevine / Viaplay)
                if response.request.method == "POST":
                    UI.print_step(f"[dim]Observed POST: {response.url[:70]}[/dim]", "info")
                
                # Be aggressive: catch anything with 'license', 'widevine', 'vmp', 'play.viaplay', 'lic.' or Viaplay auth headers
                is_lic_url = any(kw in response.url.lower() for kw in ["license", "widevine", "vmp", "play.viaplay", "lic.", "getrawwidevinelicense", "theplatform"])

                # Check headers for Viaplay-specific DRM tokens
                has_drm_headers = False
                for h in response.request.headers:
                    h_lower = h.lower()
                    if any(kw in h_lower for kw in ['x-vmp-', 'x-viaplay-', 'authorization', 'mtg-at']):
                        has_drm_headers = True
                        break

                if (is_lic_url or has_drm_headers) and response.request.method == "POST":
                    # For thePlatform/Widevine license URLs, ALWAYS capture the URL and headers
                    # because the token is usually in the URL query params, not headers.
                    # The challenge body may be empty in Playwright interception, so we can't rely on is_challenge.
                    if is_lic_url:
                        if not result["license_url"]:
                            UI.print_step(f"[bold green]CAPTURED license URL:[/bold green] {response.url}", "success")
                        result["license_url"] = response.url

                        # Capture ALL headers from the license request so we can replicate the browser exactly
                        for h, v in response.request.headers.items():
                            h_lower = h.lower()
                            # Skip problematic headers that cause HTTP 431
                            if h_lower in ('content-length', 'host', 'connection', 'accept-encoding'):
                                continue
                            # Only keep useful headers to avoid bloat
                            if any(kw in h_lower for kw in ['authorization', 'x-vmp-', 'cookie', 'token', 'x-viaplay', 'mtg-at', 'origin', 'referer', 'content-type', 'accept', 'user-agent']):
                                result["license_headers"][h] = v

                    # Also store headers from ANY request that has DRM headers (fallback)
                    elif has_drm_headers and not is_lic_url:
                        for h, v in response.request.headers.items():
                            h_lower = h.lower()
                            if any(kw in h_lower for kw in ['authorization', 'x-vmp-', 'token', 'x-viaplay', 'mtg-at']):
                                result["license_headers"][h] = v

                    # Sniff PSSH from challenge body if possible
                    try:
                        body = response.request.post_data_buffer
                        if body and len(body) > 50:
                            msg = SignedMessage()
                            msg.ParseFromString(body)
                            req = LicenseRequest()
                            req.ParseFromString(msg.msg)
                            if req.content_id.widevine_pssh_data.pssh_data:
                                for p_bin in req.content_id.widevine_pssh_data.pssh_data:
                                    p_b64 = base64.b64encode(p_bin).decode()
                                    if p_b64 not in result["psshs"]:
                                        result["psshs"].append(p_b64)
                                        UI.print_step("Extracted PSSH from license challenge body.", "success")
                    except Exception as e:
                        import traceback
                        UI.print_step(f"Failed to extract PSSH from challenge: {e}", "warning")

                # Capture manifest URL directly from network if not in JSON (fallback)
                # Note: We filter out dedicated ad manifests (vmap, vast) but allow manifests that might have ad-params
                is_ad_manifest = any(k in response.url.lower() for k in ["vmap", "vast", "ads/v1/ads"])
                if (".mpd" in response.url or ".m3u8" in response.url) and not is_ad_manifest:
                    # Prefer encrypted/ism manifests as they are usually the main ones
                    if not result["manifest_url"] or "encrypted" in response.url or ".ism/index" in response.url:
                        import urllib.parse as urlparse
                        import re
                        parsed = urlparse.urlparse(response.url)
                        query_params = urlparse.parse_qs(parsed.query)
                        # Remove ad-related query parameters to avoid multi-period SSAI issues
                        clean_params = {k: v for k, v in query_params.items() if not k.startswith('ads.') and k not in ['ssaiflag', 'aws.adSignalingEnabled']}
                        clean_query = urlparse.urlencode(clean_params, doseq=True)
                        
                        # Force domain to cdn7 (bypasses Akamai 504 timeouts and strict SSAI enforcement)
                        netloc = "vod-dash-cdn7-vp.cdn.viaplay.tv"
                        path = re.sub(r'/cdn\d+-', '/cdn7-', parsed.path)
                            
                        clean_url = urlparse.urlunparse(parsed._replace(netloc=netloc, path=path, query=clean_query))
                        
                        result["manifest_url"] = clean_url
                        UI.print_step("Cleaned manifest URL and forced cdn7 routing.", "success")
                        
                        # Try to extract PSSH directly from the intercepted manifest body
                        try:
                            # Use a helper or direct regex since we already have the body in the browser's buffer
                            content = response.text()
                            # Extract ALL PSSH elements from DASH manifest
                            # IMPORTANT: Filter for Widevine System ID to avoid sending PlayReady PSSH
                            # Widevine System ID: edef8ba9-79d6-4ace-a3c8-27dcd51d21ed
                            widevine_psshs = []
                            
                            # Find all ContentProtection blocks with their PSSH children
                            # Strategy 1: Look for Widevine-specific ContentProtection + pssh
                            cp_blocks = re.findall(
                                r'<ContentProtection[^>]*schemeIdUri="urn:uuid:edef8ba9[^"]*"[^>]*>(.*?)</ContentProtection>',
                                content, re.I | re.S
                            )
                            for block in cp_blocks:
                                pssh_match = re.search(r'<(?:\w+:)?pssh[^>]*>(.*?)</(?:\w+:)?pssh>', block, re.I | re.S)
                                if pssh_match:
                                    p = pssh_match.group(1).strip()
                                    if p and p not in widevine_psshs:
                                        widevine_psshs.append(p)
                            
                            # Strategy 2: If no ContentProtection wrapper, check all PSSH boxes
                            # and identify Widevine by decoding the base64 and checking system ID bytes
                            if not widevine_psshs:
                                all_psshs = re.findall(r'<(?:\w+:)?pssh[^>]*>(.*?)</(?:\w+:)?pssh>', content, re.I | re.S)
                                for candidate in all_psshs:
                                    candidate = candidate.strip()
                                    if not candidate:
                                        continue
                                    try:
                                        decoded = base64.b64decode(candidate)
                                        widevine_bytes = bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed")
                                        if widevine_bytes in decoded:
                                            if candidate not in widevine_psshs:
                                                widevine_psshs.append(candidate)
                                    except:
                                        pass
                                
                                # Strategy 3: If still nothing, take the last PSSH (often Widevine comes after PlayReady)
                                if not widevine_psshs and all_psshs:
                                    widevine_psshs.append(all_psshs[-1].strip())
                            
                            # Strategy 4: Fallback to pssh= attribute
                            if not widevine_psshs:
                                pssh_attr = re.search(r'pssh="?([^"\s>]+)"?', content, re.I)
                                if pssh_attr:
                                    widevine_psshs.append(pssh_attr.group(1).strip())
                            
                            for p in widevine_psshs:
                                if p and p not in result["psshs"]:
                                    result["psshs"].append(p)
                                    
                            if widevine_psshs:
                                UI.print_step(f"Extracted {len(widevine_psshs)} PSSH(s) from manifest traffic.", "success")
                        except: pass

            page.on("response", handle_response)
            
            # Navigate directly to the player to avoid "Resume Watching" buttons playing wrong episodes
            player_url = f"https://viaplay.fi/player/default/{slug}" if slug and "/player/" not in url else url
            UI.print_step(f"Navigating directly to player: {player_url}", "info")
            page.goto(player_url, wait_until="domcontentloaded", timeout=60000)

            # Check for "Too many streams" error and retry
            for retry in range(3):
                # Wait for player to load or error to appear
                page.wait_for_timeout(5000)
                
                error_texts = [
                    "Liian monet käyttävät tiliäsi",
                    "samanaikaisten striimausten rajan",
                    "Too many are using your account",
                    "simultaneous streams"
                ]
                
                has_error = False
                for text in error_texts:
                    if page.locator(f"text='{text}'").count() > 0:
                        has_error = True
                        break
                
                if has_error:
                    UI.print_step(f"Viaplay stream limit reached (retry {retry+1}/3). Waiting 60s for sessions to clear...", "warn")
                    page.goto("about:blank")
                    time.sleep(60)
                    UI.print_step("Retrying extraction...", "running")
                    page.goto(player_url, wait_until="domcontentloaded", timeout=60000)
                    continue
                else:
                    break

            # Interactive Play / Consent handling
            try:
                # Cookie Banner: "Hyväksy" (Accept)
                for sel in ["#accept-all-button", "button:has-text('Hyväksy')", "button:has-text('Hyväksy kaikki')", "button:has-text('Accept')", ".accept-all", "button:has-text('OK')"]:
                    if page.locator(sel).count() > 0:
                        UI.print_step("Closing cookie consent...", "info")
                        page.locator(sel).first.click()
                        page.wait_for_timeout(1000)
                        break

                # If we're on a series page (not an episode page), try to click the first episode to enter the player
                current_path = page.evaluate("() => window.location.pathname")
                is_episode_page = bool(current_path and (re.search(r'/(jakso|episode)-\d+', current_path) or re.search(r'/\d+$', current_path.rstrip('/'))))
                if not is_episode_page:
                    # Likely a series listing page: find any episode link and click it
                    UI.print_step("Detected series listing page, navigating to first episode...", "info")
                    clicked_episode = page.evaluate("""() => {
                        // Try various selectors for episode links
                        const selectors = [
                            'a[href*="/sarjat/"]:not([href$="/'+window.location.pathname.split('/').pop()+'"])',
                            'a[href*="/tv/"]:not([href$="/'+window.location.pathname.split('/').pop()+'"])',
                            '[data-testid*="episode"] a',
                            'a[href*="jakso"]',
                            'a[href*="/kausi-"]'
                        ];
                        for (const s of selectors) {
                            const el = document.querySelector(s);
                            if (el) { el.scrollIntoView({block:'center'}); el.click(); return el.getAttribute('href'); }
                        }
                        return null;
                    }""")
                    if clicked_episode:
                        page.wait_for_timeout(3000)
                        # Update url var to point to the episode now
                        new_path = page.evaluate("() => window.location.pathname")
                        if new_path and new_path != current_path:
                            url = "https://viaplay.fi" + new_path
                            UI.print_step(f"Navigated to episode: {url}", "info")

                # Try all play button selectors
                play_clicked = False
                for sel in ["a[data-test-id='play-link']", "button:has-text('Katso')", "button:has-text('Toista')", "button:has-text('Watch')", ".PlayButton", ".Viaplay-Player", "[data-testid='play-button']"]:
                    if page.locator(sel).count() > 0:
                        UI.print_step(f"Triggering playback via {sel}...", "info")
                        page.locator(sel).first.click()
                        page.wait_for_timeout(2000)
                        play_clicked = True
                        break

                # If no play button found, try clicking the video element directly
                if not play_clicked:
                    if page.locator("video").count() > 0:
                        UI.print_step("Clicking video element directly...", "info")
                        page.locator("video").first.click()
                        page.wait_for_timeout(2000)
                    else:
                        # Final fallback: click anywhere on the body to dismiss overlays and trigger player
                        page.mouse.click(100, 100)
                        page.wait_for_timeout(1000)
            except: pass

            # Extract Title from page meta if still missing
            if not result["title"]:
                try:
                    og_title = page.locator('meta[property="og:title"]').get_attribute('content')
                    result["title"] = og_title or page.title()
                except: pass

            if not result["title"]:
                # Fallback to URL slug
                slug = url.rstrip("/").split("/")[-1]
                if slug: result["title"] = slug

            if result["title"]:
                result["title"] = re.sub(r'[^\w\s-]', '', result["title"]).strip().replace(" ", "_")

            # Wait for data
            # CRITICAL: We must wait for the BROWSER to make an actual Widevine POST
            # so we can capture auth headers. API metadata license_url alone won't work
            # because it lacks the browser-specific token/query params.
            UI.print_step("Waiting for browser Widevine license request... (Login now if needed)", "running")
            start = time.time()
            max_wait = 120 
            
            while time.time() - start < max_wait:
                # Success: we have manifest AND browser-captured license with headers
                if result["manifest_url"] and result["license_url"] and result["license_headers"]:
                    UI.print_step("Got all required playback data from browser.", "success")
                    page.wait_for_timeout(3000)
                    break
                
                # If we have manifest but no browser license after 60s, try to trigger playback harder
                elapsed = time.time() - start
                if result["manifest_url"] and not result["license_url"] and elapsed > 30:
                    UI.print_step("Manifest found but no license POST yet, forcing playback...", "running")
                    page.evaluate("""
                        var v = document.querySelector('video');
                        if(v) { v.muted = true; v.play().catch(e => {}); }
                    """)
                    # Try clicking the play button again
                    for sel in ["button:has-text('Katso')", "button:has-text('Toista')", "[data-testid='play-button']", ".PlayButton", "a[data-test-id='play-link']"]:
                        try:
                            if page.locator(sel).count() > 0:
                                page.locator(sel).first.click()
                                break
                        except: pass

                # Periodic status update
                if int(elapsed) % 15 == 0 and int(elapsed) > 0:
                    status = []
                    if result["manifest_url"]: status.append("Manifest [green]OK[/green]")
                    else: status.append("Manifest [red]Missing[/red]")
                    if result["license_url"]: status.append("License [green]OK[/green]")
                    else: status.append("License [red]Missing[/red]")
                    if result["license_headers"]: status.append("Headers [green]OK[/green]")
                    else: status.append("Headers [red]Missing[/red]")
                    UI.print_step(f"Still waiting... ({', '.join(status)})", "running")

                # Early playback trigger
                if elapsed > 15 and not result["manifest_url"]:
                    page.evaluate("""
                        var v = document.querySelector('video');
                        if(v && v.paused && !v.ended) { 
                            v.muted = true; 
                            v.play().catch(e => {}); 
                        }
                    """)
                    try: page.mouse.click(10, 10)
                    except: pass
                    
                page.wait_for_timeout(2000)

            # Fallback: if browser never made a Widevine POST, use API license_url
            if not result["license_url"] and result.get("_api_license_url"):
                UI.print_step("Browser did not trigger Widevine POST, using API license URL as fallback.", "warn")
                result["license_url"] = result["_api_license_url"]

            # Final PSSH check from manifest if needed
            if not result["psshs"] and result["manifest_url"]:
                UI.print_step("PSSH missing, deep scanning manifest...", "info")
                cur_cookies = {c['name']: c['value'] for c in context.cookies()}
                pssh = self.get_pssh_from_manifest(result["manifest_url"], cur_cookies, result["license_headers"])
                if pssh:
                    result["psshs"].append(pssh)

            result["cookies"] = {c['name']: c['value'] for c in context.cookies()}
            result["pssh"] = result["psshs"][0] if result["psshs"] else None

            # Debug log captured license headers
            if result["license_headers"]:
                safe = {k: (v[:25] + '...' if len(v) > 30 else v) for k, v in result["license_headers"].items()}
                logging.info(f"[VIAPLAY] Captured license headers: {safe}")
            else:
                logging.warning(f"[VIAPLAY] No license headers were captured.")

            # Clean up internal fields
            result.pop("_api_license_url", None)

            # Gracefully stop the stream to release the simultaneous stream slot
            UI.print_step("Releasing stream session slot...", "info")
            try:
                # Try to find a 'close' or 'back' button in the player to trigger teardown
                for close_sel in [".Player-close", "[data-testid='close-button']", "button[aria-label='Close']"]:
                    if page.locator(close_sel).count() > 0:
                        page.locator(close_sel).first.click()
                        break
                
                page.evaluate("""() => {
                    if(window.viaplayPlayer && window.viaplayPlayer.stop) window.viaplayPlayer.stop();
                    // Force pause all videos
                    document.querySelectorAll('video').forEach(v => v.pause());
                }""")
                page.goto("about:blank")
                page.wait_for_timeout(5000) # Increased wait to ensure heartbeats are sent
            except: pass

            context.close()
            return result

