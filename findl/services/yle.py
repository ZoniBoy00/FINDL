import os
import yt_dlp
import logging
import re
import requests
from playwright.sync_api import sync_playwright
from .base import BaseExtractor
from ..config import CHROME_UA, SESSION_DIR
from ..ui.display import UI

class YleExtractor(BaseExtractor):
    def get_service_name(self):
        return "Yle Areena"

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

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'user_agent': CHROME_UA,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            if not info:
                return None

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
                "cookies": {},
                "license_url": None,
                "license_headers": {},
                "psshs": [],
                "pssh": None,
                "origin": "https://areena.yle.fi"
            }

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
            logging.error(f"[YLE] Extraction error: {e}")
            return None
