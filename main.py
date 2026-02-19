import os
import click
import logging
import time
from rich.logging import RichHandler

# Local Imports
from findl import KatsomoExtractor, RuutuExtractor, YleExtractor, DRMHandler, Downloader
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
    else:
        UI.error("Unsupported service. Only Katsomo, Ruutu, and Yle Areena are supported.")
        return

    UI.print_step(f"Service: [bold green]{extractor.get_service_name()}[/bold green]", "info")
    UI.print_step(f"Extracting info from [underline]{url}[/underline]", "running")
    
    with UI.status("Analyzing target...") as status:
        info = extractor.extract(url)
    
    if not info or not info.get("manifest_url"):
        UI.error("Extraction failed. Could not find video manifest.")
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
                    pssh = extractor.get_pssh_from_manifest(info["manifest_url"], info.get("cookies"), info.get("license_headers"))
                    if pssh: all_psshs = [pssh]

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
    if not title:
        title = info.get("title") or url.split('/')[-1].split('?')[0].replace('-', '_') or f"Video_{int(time.time())}"

    UI.download_session(title, output, keys, subtitles)
    
    downloader = Downloader(output_dir=output)
    start_time = time.time()
    
    UI.print_step(f"Starting downloader for {title}", "running")
    use_ytdlp = "areena.yle.fi" in url
    
    success = downloader.download(
        info["manifest_url"], 
        keys, 
        title=title, 
        subtitles=subtitles,
        origin=info.get("origin", "https://www.mtv.fi"),
        skip_subs=no_subs,
        use_ytdlp=use_ytdlp,
        original_url=url
    )
    
    if success:
        UI.success_panel(title, output, time.time() - start_time)
    else:
        UI.error("Download failed.")

if __name__ == "__main__":
    main()
