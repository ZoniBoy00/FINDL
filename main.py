import os
import click
import logging
import time
from rich.logging import RichHandler
from rich.table import Table
from rich.box import ROUNDED

# Local Imports
from findl import KatsomoExtractor, RuutuExtractor, YleExtractor, ViaplayExtractor, DRMHandler, Downloader
from findl.ui.display import UI, console

# Setup Logging
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)]
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
            
            # Show selection menu
            # Show selection menu
            table = Table(title=f"Sarjan [bold cyan]{episodes[0].get('series', 'Sarja')}[/bold cyan] jaksot", box=ROUNDED, show_header=True, header_style="bold magenta")
            table.add_column("No.", style="dim", justify="right")
            table.add_column("Kausi", style="cyan")
            table.add_column("Jakso", style="bold white")
            table.add_column("URL", style="dim", no_wrap=True)
            
            last_season = None
            for i, ep in enumerate(episodes):
                current_season = ep.get('season', 'Kausi 1')
                # Add a divider if season changes
                if last_season and current_season != last_season:
                    table.add_section()
                
                table.add_row(
                    str(i+1), 
                    current_season,
                    ep['title'], 
                    ep['url']
                )
                last_season = current_season
            
            console.print(table)
            
            selection = click.prompt(
                "\nValitse ladattavat jaksot (esim. 'all', '5' ensimmäiset 5, '1-3' väli, tai '1,3,5')", 
                default="all"
            )
            
            to_download = []
            selection = selection.lower().strip()
            
            if selection == 'all':
                to_download = episodes
            elif selection.isdigit():
                # If it's just one number, treat it as "first N episodes"
                count = int(selection)
                to_download = episodes[:count]
            else:
                try:
                    # Handle 1,2,5 and 1-10 formats
                    parts = selection.split(',')
                    for p in parts:
                        p = p.strip()
                        if '-' in p:
                            start, end = map(int, p.split('-'))
                            to_download.extend(episodes[start-1:end])
                        else:
                            to_download.append(episodes[int(p)-1])
                except:
                    UI.error("Invalid selection format.")
                    return
            
            if not to_download:
                UI.error("No episodes selected.")
                return

            # Summary of what will be downloaded
            found_seasons = sorted(list(set(ep.get('season', 'Kausi 1') for ep in to_download)))
            UI.print_step(f"Jonossa [bold cyan]{len(to_download)}[/bold cyan] jaksoa [bold]{len(found_seasons)}[/bold] kaudelta.", "info")
            
            for ep in to_download:
                UI.print_step(f"Seuraavaksi: [bold]{ep.get('season', '?')}[/bold] - [bold white]{ep['title']}[/bold white]", "running")
                
                # Create subfolder path: "Series Name/Season X"
                series_name = ep.get("series", "Unknown Series").replace(":", "-").replace("/", "-").strip()
                season_name = ep.get("season", "Kausi 1").replace(":", "-").replace("/", "-").strip()
                subfolder = os.path.join(series_name, season_name)

                # Calculate episode number within its season for numbering
                season_episodes = [e for e in episodes if e.get('season') == ep.get('season')]
                try:
                    episode_num = season_episodes.index(ep) + 1
                except ValueError:
                    episode_num = 1
                    
                numbered_title = f"{episode_num:02d} - {ep['title']}"
                
                # Recursively call main_logic but for a single URL with subfolder and numbered title
                process_single_url(ep['url'], extractor, output, numbered_title, pssh, no_subs, subfolder=subfolder)
            
            return # Exit playlist flow

    # Standard Single Video Flow (handles non-series or series discovery that turned up empty)
    process_single_url(url, extractor, output, title, pssh, no_subs)

def process_single_url(url, extractor, output, title, pssh, no_subs, subfolder=None):
    with UI.status("Analyzing target...") as status:
        info = extractor.extract(url)
    
    if not info or not info.get("manifest_url"):
        UI.error(f"Extraction failed for {url}")
        return

    if pssh:
        info["pssh"] = pssh
        info["psshs"] = [pssh]

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
        final_title = info.get("title") or url.split('/')[-1].split('?')[0].replace('-', '_') or f"Video_{int(time.time())}"

    # Handle subfolder organization
    base_output = output or "."
    if subfolder:
        effective_output = os.path.join(base_output, subfolder)
        if not os.path.exists(effective_output):
            os.makedirs(effective_output, exist_ok=True)
    else:
        effective_output = base_output

    UI.download_session(final_title, effective_output, keys, subtitles)
    
    downloader = Downloader(output_dir=effective_output)
    start_time = time.time()
    
    UI.print_step(f"Starting downloader for {final_title}", "running")
    use_ytdlp = "areena.yle.fi" in url
    
    success = downloader.download(
        info["manifest_url"], 
        keys, 
        title=final_title, 
        subtitles=subtitles,
        origin=info.get("origin", "https://www.mtv.fi"),
        skip_subs=no_subs,
        use_ytdlp=use_ytdlp,
        original_url=url
    )
    
    if success:
        UI.success_panel(final_title, effective_output, time.time() - start_time)
    else:
        UI.error("Download failed.")

if __name__ == "__main__":
    main()
