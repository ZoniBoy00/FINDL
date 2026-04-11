import os
import click
import logging
import re
import time
from rich.logging import RichHandler
from rich.table import Table
from rich.box import ROUNDED

from findl.services.base import sanitize_path_name

def format_series_title(info, ep=None):
    """
    Format title for series episodes: SeriesName_SxxExx_EpisodeTitle
    For movies: just the title
    """
    series = info.get("series")
    season = info.get("season")
    episode_num = info.get("episode")
    title = info.get("title", "Video")
    
    original_title = info.get("title", "Video")
    
    season_num_in_field = re.search(r'\d+', str(season)) if season else None
    season_num_in_field_val = int(season_num_in_field.group()) if season_num_in_field else None
    
    season_from_title = None
    season_in_title_match = re.search(r'Kausi\s*(\d+)|Season\s*(\d+)', original_title, re.I)
    if season_in_title_match:
        season_from_title = int(season_in_title_match.group(1) or season_in_title_match.group(2))
    
    if season_from_title and season_num_in_field_val and season_from_title != season_num_in_field_val:
        season_from_title = None
    
    if season_from_title:
        season = f"Kausi {season_from_title}"
    
    if not episode_num:
        episode_match = re.search(r'Jakso\s*(\d+)|Episode\s*(\d+)', original_title, re.I)
        if episode_match:
            episode_num = int(episode_match.group(1) or episode_match.group(2))
    
    title = re.sub(r'[^\w\s-]', '', title).strip().replace(" ", "_")
    
    title = re.sub(r'[-_\s]*Jakso[-_\s]*\d+[-_\s]*', '', title, flags=re.I)
    title = re.sub(r'[-_\s]*Kausi[-_\s]*\d+[-_\s]*', '', title, flags=re.I)
    title = re.sub(r'[-_\s]*Season[-_\s]*\d+[-_\s]*', '', title, flags=re.I)
    title = re.sub(r'[-_\s]*Episode[-_\s]*\d+[-_\s]*', '', title, flags=re.I)
    title = re.sub(r'[-_]+', '_', title).strip('_-')
    
    if series:
        series_clean = sanitize_path_name(series)
        title = re.sub(rf'^{re.escape(series_clean)}[-_\s]*', '', title, flags=re.I).strip('_-')
        title = re.sub(r'^The_[Rr]ookie[-_\s]*', '', title).strip('_-')
    
    if not title or len(title) < 2:
        title = f"Episode_{episode_num:02d}" if episode_num else "Episode"
    
    if series:
        season_str = ""
        if season:
            season_match = re.search(r'\d+', str(season))
            if season_match:
                season_str = f"_S{int(season_match.group()):02d}"
        
        episode_str = ""
        if episode_num:
            episode_str = f"E{int(episode_num):02d}"
        elif ep and ep.get('episode'):
            episode_str = f"E{int(ep.get('episode')):02d}"
        
        series_name = sanitize_path_name(series)
        return f"{series_name}{season_str}{episode_str}_{title}"
    
    return title

def get_folder_structure(info, ep=None):
    """
    Determine folder structure based on content type.
    Movies: just movie title
    Series: Series Name / Season X
    """
    series = info.get("series")
    season = info.get("season")
    
    if series:
        series_name = sanitize_path_name(series)
        season_name = sanitize_path_name(season) if season else "Season 1"
        return os.path.join(series_name, season_name)
    
    return None

# Local Imports
from findl import KatsomoExtractor, RuutuExtractor, YleExtractor, ViaplayExtractor, DRMHandler, Downloader
from findl.ui.display import UI, console
from findl.config import LOG_DIR

# Setup Logging
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"findl_{time.strftime('%Y%m%d')}.log")

logging.basicConfig(
    level="INFO",
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RichHandler(rich_tracebacks=True, show_path=False),
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)

@click.command()
@click.argument('url', required=False)
@click.option('--output', default='downloads', help='Output directory')
@click.option('--title', help='Video title')
@click.option('--pssh', help='Manual PSSH override')
@click.option('--no-subs', is_flag=True, help='Skip downloading subtitles')
def main(url, output, title, pssh, no_subs):
    """FINDL - Ultimate Video Downloader for Finnish Services"""
    
    UI.banner()
    
    if not url:
        UI.error("Please provide a URL to download.")
        return

    # Select Extractor
    extractor = None
    if "mtv.fi" in url or "katsomo.fi" in url:
        extractor = KatsomoExtractor()
    elif "ruutu.fi" in url:
        extractor = RuutuExtractor()
    elif "areena.yle.fi" in url:
        extractor = YleExtractor()
    elif "viaplay." in url:
        extractor = ViaplayExtractor()
        UI.print_step("Viaplay support is currently WORK IN PROGRESS and may not work.", "warning")
    else:
        UI.error("Unsupported service. Supported: Katsomo, Ruutu, Yle Areena, Viaplay.")
        return

    UI.print_step(f"Service: [bold green]{extractor.get_service_name()}[/bold green]", "info")
    UI.print_step(f"Extracting info from [underline]{url}[/underline]", "running")
    
    # Check if it's a series
    if extractor.is_series(url):
        with UI.status("Scraping series metadata...") as status:
            episodes = extractor.get_episodes(url)
        
        if episodes:
            UI.print_step(f"Found [bold cyan]{len(episodes)}[/bold cyan] episodes.", "success")
            
            season_counts = {}
            for ep in episodes:
                s = ep.get('season', 'Season 1')
                season_counts[s] = season_counts.get(s, 0) + 1
            
            console.print("\n")
            console.print("[bold]Available Seasons:[/bold]")
            for s, count in sorted(season_counts.items(), key=lambda x: int(re.search(r'\d+', x[0]).group()) if re.search(r'\d+', x[0]) else 0):
                console.print(f"  {s}: [cyan]{count}[/cyan] episodes")
            
            table = Table(title=f"Episode List", box=ROUNDED, show_header=True, header_style="bold magenta")
            table.add_column("#", style="dim", justify="right", width=4)
            table.add_column("Season", style="cyan", width=10)
            table.add_column("Episode Title", style="white", width=50)
            
            last_season = None
            for i, ep in enumerate(episodes):
                current_season = ep.get('season', 'Season 1')
                if last_season and current_season != last_season:
                    table.add_section()
                
                table.add_row(
                    str(i+1),
                    current_season,
                    ep['title'][:48] + '...' if len(ep['title']) > 48 else ep['title']
                )
                last_season = current_season
            
            console.print(table)
            
            console.print("\n[bold]Download Options:[/bold]")
            console.print("[cyan]  S1       [/cyan] Season 1 only")
            console.print("[cyan]  S1,S3     [/cyan] Seasons 1 & 3")
            console.print("[cyan]  S1-3      [/cyan] Seasons 1-3")
            console.print("[cyan]  S1:1-5    [/cyan] Episodes 1-5 from S1")
            console.print("[cyan]  S1:1,3,5  [/cyan] Episodes 1,3,5 from S1")
            console.print("[cyan]  S1-3:10   [/cyan] Episode 10 from S1-3")
            console.print("[cyan]  1-5       [/cyan] Episodes 1-5 from list")
            console.print("[cyan]  1,3,5     [/cyan] Episodes 1,3,5 from list")
            console.print("[cyan]  all       [/cyan] Download all")
            console.print("[dim]  (Separate multiple with space: S1:1 S2:1 S3:1)[/dim]")
            
            selection = input("\nSelection [all]: ").strip() or "all"
            
            to_download = []
            selections = selection.lower().strip().split()
            
            season_pattern = re.compile(r'(?:s|kausi)\s*(\d+)(?:-(\d+))?(?::(\d+(?:-\d+)?(?:,\d+)*))?')
            episode_index_pattern = re.compile(r'^(\d+)(?:-(\d+))?(?:,(\d+))*$')
            
            for sel in selections:
                season_match = season_pattern.match(sel)
                
                if sel == 'all':
                    to_download = episodes
                    break
                elif season_match:
                    start_season = int(season_match.group(1))
                    end_season = int(season_match.group(2)) if season_match.group(2) else start_season
                    episodes_part = season_match.group(3)
                    
                    for ep in episodes:
                        ep_season_num = int(re.search(r'\d+', str(ep.get('season', 'Kausi 1'))).group()) if re.search(r'\d+', str(ep.get('season', 'Kausi 1'))) else 1
                        
                        if start_season <= ep_season_num <= end_season:
                            if episodes_part:
                                ep_match = re.search(r'(\d+)(?:-(\d+))?', episodes_part)
                                if ep_match:
                                    ep_start = int(ep_match.group(1))
                                    ep_end = int(ep_match.group(2)) if ep_match.group(2) else ep_start
                                    season_episodes = [e for e in episodes if e.get('season') == ep.get('season')]
                                    ep_index = season_episodes.index(ep) + 1 if ep in season_episodes else 0
                                    if ep_start <= ep_index <= ep_end:
                                        if ep not in to_download:
                                            to_download.append(ep)
                            else:
                                if ep not in to_download:
                                    to_download.append(ep)
                elif episode_index_pattern.match(sel):
                    try:
                        parts = sel.split(',')
                        for p in parts:
                            p = p.strip()
                            if '-' in p:
                                start, end = map(int, p.split('-'))
                                for ep in episodes[start-1:end]:
                                    if ep not in to_download:
                                        to_download.append(ep)
                            else:
                                ep = episodes[int(p)-1]
                                if ep not in to_download:
                                    to_download.append(ep)
                    except:
                        pass
                elif sel.isdigit():
                    count = int(sel)
                    for ep in episodes[:count]:
                        if ep not in to_download:
                            to_download.append(ep)
            
            if not to_download:
                UI.error("No episodes selected.")
                return

            # Summary of what will be downloaded
            found_seasons = sorted(list(set(ep.get('season', 'Season 1') for ep in to_download)))
            UI.print_step(f"Queued [bold cyan]{len(to_download)}[/bold cyan] episodes from [bold]{len(found_seasons)}[/bold] season(s).", "info")
            
            for ep in to_download:
                UI.print_step(f"Next: [bold]{ep.get('season', '?')}[/bold] - [bold white]{ep['title']}[/bold white]", "running")
                
                season_episodes = [e for e in episodes if e.get('season') == ep.get('season')]
                try:
                    episode_num = season_episodes.index(ep) + 1
                except ValueError:
                    episode_num = 1
                
                ep_info = {
                    "series": ep.get("series"),
                    "season": ep.get("season"),
                    "episode": episode_num,
                    "title": ep.get("title")
                }
                
                ep_title = format_series_title(ep_info, ep)
                
                subfolder = get_folder_structure(ep_info, ep)
                
                process_single_url(ep['url'], extractor, output, ep_title, pssh, no_subs, subfolder=subfolder, ep_info=ep_info)
            
            return

    process_single_url(url, extractor, output, title, pssh, no_subs)

def process_single_url(url, extractor, output, title, pssh, no_subs, subfolder=None, ep_info=None):
    with UI.status("Analyzing target...") as status:
        info = extractor.extract(url)
    
    if not info or not info.get("manifest_url"):
        UI.error(f"Extraction failed for {url}")
        if info and "error" in info: UI.error(info["error"])
        return

    if pssh:
        info["pssh"] = pssh
        info["psshs"] = [pssh]

    base_output = output or "downloads"
    effective_subfolder = subfolder
    
    if ep_info:
        info.update(ep_info)
    
    if not effective_subfolder and info.get("series"):
        effective_subfolder = get_folder_structure(info)
    
    if effective_subfolder:
        # Sanitize each part of the subfolder path
        parts = [sanitize_path_name(p) for p in effective_subfolder.split(os.sep)]
        effective_subfolder = os.path.join(*parts)
        effective_output = os.path.join(base_output, effective_subfolder)
        os.makedirs(effective_output, exist_ok=True)
    else:
        effective_output = base_output

    # Handle --no-subs
    subtitles = [] if no_subs else info.get("subtitles", [])
    if no_subs:
        info["subtitles"] = []

    UI.playback_table(info)

    # DRM Keys
    keys = []
    if info.get("license_url"):
        UI.print_step("Acquiring Decryption Keys", "running")
        
        all_psshs = info.get("psshs", [])
        if not all_psshs and info.get("pssh"):
            all_psshs = [info["pssh"]]

        # Fallback: Scan manifest if PSSH is still missing
        if not all_psshs and info.get("manifest_url"):
            with UI.status("Deep scanning manifest for PSSH...") as status:
                if hasattr(extractor, "get_pssh_from_manifest"):
                    pssh_found = extractor.get_pssh_from_manifest(info["manifest_url"], info.get("cookies"), info.get("license_headers"))
                    if pssh_found: all_psshs = [pssh_found]

        if all_psshs:
            try:
                drm = DRMHandler()
                with UI.status("Engaging DRM Strategy...") as status:
                    keys = drm.get_keys(
                        psshs=all_psshs,
                        license_url=info["license_url"],
                        drm_token=info.get("drm_token"),
                        headers=info.get("license_headers"),
                        cookies=info.get("cookies")
                    )
            except Exception as e:
                import traceback
                UI.error(f"DRM Error: {e}")
                UI.print_step(traceback.format_exc(), "debug")
                return
        else:
            UI.error("No PSSH found. Cannot acquire decryption keys.")
            return

    if keys:
        UI.key_panel(keys)
    elif info.get("psshs") or info.get("pssh"):
        UI.error("Content is encrypted but no keys were acquired.")
        if not info.get("license_url"):
            UI.print_step("License URL was not found. Please try again and ensure you are logged in.", "error")
        return

    # Download Setup
    final_title = title
    if not final_title:
        final_title = format_series_title(info)

    UI.download_session(final_title, effective_output, keys, subtitles)
    
    downloader = Downloader(output_dir=effective_output)
    start_time = time.time()
    
    UI.print_step(f"Starting downloader for {final_title}", "running")
    # Select best engine for the service/encryption
    is_yle = "areena.yle.fi" in url.lower()
    use_ytdlp = False  # Use N_m3u8DL-RE for all services

    logging.info(f"[MAIN] Strategy select: {'yt-dlp' if use_ytdlp else 'N_m3u8DL-RE'}")
    
    success = downloader.download(
        info["manifest_url"], 
        keys, 
        title=final_title, 
        subtitles=subtitles,
        origin=info.get("origin", "https://www.mtv.fi"),
        skip_subs=no_subs,
        use_ytdlp=use_ytdlp,
        original_url=url,
        cookies=info.get("cookies"),
        token=info.get("drm_token"),
        license_headers=info.get("license_headers")
    )
    
    if success:
        UI.success_panel(final_title, effective_output, time.time() - start_time)
    else:
        UI.error("Download failed.")

if __name__ == "__main__":
    main()
