import os
import re
import time
import subprocess
import logging
import requests
import shutil
import yt_dlp
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn, 
    DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
)

from ..config import NM3U8DL_RE_PATH, SHAKA_PACKAGER_PATH, TEMP_DIR, CHROME_UA, DEFAULT_HEADERS
from ..ui.display import UI, console
from .subtitles import SubtitleManager

class Downloader:
    """
    Handles file downloading using two strategies:
    1. N_m3u8DL-RE: Default for MTV & Ruutu (supports DRM/Multi-keys).
    2. yt-dlp: Specialized for Yle Areena and other complex HLS systems.
    """
    def __init__(self, output_dir="downloads"):
        """
        Initialize the downloader.
        
        Args:
            output_dir (str): Directory where downloaded files will be saved.
        """
        self.exe = NM3U8DL_RE_PATH
        self.packager = SHAKA_PACKAGER_PATH
        self.output_dir = output_dir
        
        # Ensure directories exist
        for d in [self.output_dir, TEMP_DIR]:
            if not os.path.exists(d):
                os.makedirs(d)

    def download(self, url, keys=None, title="video", subtitles=None, origin="https://www.mtv.fi", skip_subs=False, use_ytdlp=False, original_url=None, cookies=None, token=None, license_headers=None):
        # Yle Areena works better with N_m3u8DL-RE for stability if unencrypted/AES-128
        # but yt-dlp is kept for specific cases or explicit requests.
        if use_ytdlp:
            # When using yt-dlp with force_generic, we MUST use the manifest URL
            return self.download_ytdlp(url, title, origin, skip_subs, cookies, license_headers, original_url)
        
        # Override origin for Yle if needed
        actual_origin = origin
        if "yle.fi" in (original_url or url).lower():
            actual_origin = "https://areena.yle.fi"
            
        return self.download_re(url, keys, title, subtitles, actual_origin, skip_subs, cookies, token, license_headers, original_url=original_url)

    def _write_temp_cookies(self, cookies, domain=".mtv.fi"):
        """Write cookies to a temporary Netscape formatted file for yt-dlp."""
        if not cookies: return None
        cookie_path = os.path.join(TEMP_DIR, f"cookies_{int(time.time())}.txt")
        with open(cookie_path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for name, value in cookies.items():
                f.write(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}\n")
        return cookie_path

    def download_re(self, manifest_url, keys, title, subtitles, origin, skip_subs, cookies=None, token=None, license_headers=None, original_url=None):
        """Standard download strategy using N_m3u8DL-RE."""
        clean_title = self._sanitize_title(title)
        ts = int(time.time())
        temp_title = f"fndl_{ts}"
        
        # Determine service-specific origin & referer
        is_ruutu = "ruutu.fi" in manifest_url.lower() or "nelonenmedia" in manifest_url.lower()
        effective_origin = "https://www.ruutu.fi" if is_ruutu else origin
        effective_referer = (original_url if original_url else f"{effective_origin}/")

        # Build headers for the download command
        if is_ruutu:
            # High-stealth browser imitation for Ruutu (Nelonen)
            ruutu_headers = [
                f"User-Agent: {CHROME_UA}",
                "Origin: https://www.ruutu.fi",
                "Referer: https://www.ruutu.fi/",
                "Accept: */*",
                "Accept-Language: fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding: gzip, deflate, br",
                "Connection: keep-alive",
                "Sec-Fetch-Dest: empty",
                "Sec-Fetch-Mode: cors",
                "Sec-Fetch-Site: cross-site"
            ]
            if cookies:
                cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
                ruutu_headers.append(f"Cookie: {cookie_str}")
            
            if token:
                ruutu_headers.append(f"X-AxDRM-Message: {token}")
        else:
            # Katsomo/Other RE based headers often need the pipe format for .NET stability
            header_str = f"User-Agent: {CHROME_UA}"
            if effective_origin: header_str += f"|Origin: {effective_origin}"
            if effective_referer: header_str += f"|Referer: {effective_referer}"
            if cookies:
                c_clean = "; ".join([f"{k}={v}" for k, v in cookies.items()]).replace("{", "%7B").replace("}", "%7D")
                header_str += f"|Cookie: {c_clean}"
            if token:
                t_clean = str(token).replace("{", "%7B").replace("}", "%7D")
                header_str += f"|Authorization: Bearer {t_clean}"

        # Final command construction
        rel_output = os.path.relpath(self.output_dir)
        download_tmp = os.path.join(TEMP_DIR, f"t_{ts}")
        if not os.path.exists(download_tmp): os.makedirs(download_tmp)

        cmd = [
            self.exe, manifest_url,
            "-mt",
            "--thread-count", "8", # Reduced for stealth (avoid 401 rate limits)
            "--concurrent-download", "True",
            "--download-retry-count", "30",
            "--decryption-engine", "SHAKA_PACKAGER",
            "--decryption-binary-path", self.packager,
            "--select-video", "best",
            "--select-audio", "best",
            "--mux-after-done", "format=mkv",
            "--save-name", temp_title,
            "--save-dir", rel_output,
            "--tmp-dir", download_tmp,
            "--del-after-done",
            "--auto-subtitle-fix", "True",
            "--no-log",
            "--check-segments-count", "False"
        ]

        header_list = [
            f"User-Agent: {CHROME_UA}",
            f"Origin: {origin}",
            f"Referer: {origin}/"
        ]
        if cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            header_list.append(f"Cookie: {cookie_str}")

        if is_ruutu:
            # FORCE standard referer for Ruutu, otherwise Nelonen CDN rejects with 401 (Unauthorized)
            ruutu_headers.append("Referer: https://www.ruutu.fi/")
            for h in ruutu_headers:
                cmd.extend(["-H", h])
        else:
            for h in header_list:
                cmd.extend(["-H", h])

        # Handle Subtitles
        if skip_subs:
            cmd.extend(["--drop-subtitle", ".*"])
        else:
            cmd.extend(["--select-subtitle", "lang=fi|suo|swe|en.*", "--sub-format", "SRT"])
            
            # Manual processing for special tracks (qag/CC)
            manager_subs = [s for s in (subtitles or []) if self._is_special_track(s)]
            if manager_subs:
                try:
                    sm = SubtitleManager(output_dir=self.output_dir)
                    sub_args, _ = sm.process_subtitles(manager_subs, ts)
                    if sub_args: cmd.extend(sub_args)
                except: pass

        # Add Decryption Keys
        if keys:
            for k in keys: cmd.extend(["--key", k])

        # Final execution
        logging.info(f"[DOWNLOADER] Running N_m3u8DL-RE engine...")
        try:
            subprocess.run(cmd, check=False)
            
            final_path = os.path.join(self.output_dir, f"{clean_title}.mkv")
            temp_file = os.path.join(self.output_dir, f"{temp_title}.mkv")
            if not os.path.exists(temp_file):
                temp_file = os.path.join(self.output_dir, f"{temp_title}.MUX.mkv")

            if os.path.exists(temp_file):
                if os.path.exists(final_path): os.remove(final_path)
                shutil.move(temp_file, final_path)
                logging.info(f"[DOWNLOADER] Saved to: {final_path}")
                # Optional: extra cleanup or post-processing could go here
                return True
            return False
        except Exception as e:
            logging.error(f"[DOWNLOADER] RE Strategy failed: {e}")
            return False
        finally:
            shutil.rmtree(download_tmp, ignore_errors=True)

    def download_ytdlp(self, url, title, origin, skip_subs=False, cookies=None, license_headers=None, original_url=None):
        """
        Specialized strategy using yt-dlp with "Temp-and-Move" to avoid WinError 32.
        Processes in an isolated temp dir, then moves to downloads.
        """
        ts = int(time.time())
        work_dir = os.path.join(TEMP_DIR, f"work_{ts}")
        if not os.path.exists(work_dir): os.makedirs(work_dir)
        
        clean_title = self._sanitize_title(title)
        work_tmpl = os.path.join(work_dir, "video.%(ext)s")
        final_dest = os.path.join(self.output_dir, f"{clean_title}.mkv")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=45),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=console,
            transient=True
        ) as progress:
            
            dl_task = progress.add_task("Downloading", total=None)
            pp_task = progress.add_task("Post-processing", total=None, visible=False)

            def ytdlp_progress_hook(d):
                if d['status'] == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                    progress.update(dl_task, completed=downloaded, total=total, speed=d.get('speed'))
                elif d['status'] == 'finished':
                    downloaded = d.get('downloaded_bytes', 100)
                    progress.update(dl_task, completed=downloaded, total=downloaded, description="[bold green]Download Complete")

            def ytdlp_post_hook(d):
                if d['status'] == 'started':
                    pp_name = d.get('postprocessor', 'Processor')
                    desc_map = {"EmbedSubtitle": "Embedding Subtitles", "SubtitlesConvertor": "Converting to SRT", "Metadata": "Writing Metadata"}
                    for key, val in desc_map.items():
                        if key in pp_name:
                            pp_name = val
                            break
                    progress.update(pp_task, visible=True, description=f"[bold yellow]{pp_name}")
                elif d['status'] == 'finished':
                    progress.update(pp_task, completed=1, total=1, description="[bold green]Finished")

            # Mix headers and cookies into ydl_opts
            ydl_headers = {
                'User-Agent': CHROME_UA,
                'Referer': original_url or "https://areena.yle.fi/",
                'Origin': 'https://areena.yle.fi'
            }
            if license_headers:
                for k, v in license_headers.items():
                    if k.lower() not in ['user-agent', 'referer', 'origin']:
                        ydl_headers[k] = v

            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'outtmpl': work_tmpl,
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'nocheckcertificate': True,
                'merge_output_format': 'mkv',
                'noplaylist': True,
                'force_generic_extractor': True, # Bypass broken/blocked Ruutu-specific extractor
                'extractor_args': {'generic': {'impersonate': 'chrome'}},
                'socket_timeout': 30,
                'retries': 10,
                'http_headers': ydl_headers,
                'noprogress': True,
                'overwrites': True,
                'nopart': True,              
                'updatetime': False,         
                'windowsfilenames': True,    
                'writesubtitles': not skip_subs,      
                'writeautomaticsub': not skip_subs,   
                'subtitleslangs': ['fi.*', 'suo.*', 'en.*', 'und.*'],   
                'subtitlesformat': 'srt/vtt/best',
                'concurrent_fragment_downloads': 8, # Reduced for stability on Akamai
                'fragment_retries': 15,
                'skip_unavailable_fragments': True,
                'socket_timeout': 60,
                'add_metadata': True,
                'progress_hooks': [ytdlp_progress_hook],
                'postprocessor_hooks': [ytdlp_post_hook],
                'postprocessors': [
                    {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
                    {'key': 'FFmpegEmbedSubtitle'}
                ]
            }
            
            # Pass cookies if available
            if cookies:
                # Determine domain: if URL has 'yle', use .yle.fi
                target_domain = ".yle.fi" if "yle.fi" in (original_url or url).lower() else ".mtv.fi"
                ydl_opts['cookiefile'] = self._write_temp_cookies(cookies, domain=target_domain)

            try:
                progress.console.log(f"[bold cyan]INFO[/bold cyan]     [DOWNLOADER] Engaging yt-dlp engine...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Filename detection (yt-dlp might change extension or name)
                out_files = [f for f in os.listdir(work_dir) if f.endswith(".mkv") or f.endswith(".mp4") or f.endswith(".ts")]
                if not out_files:
                    progress.console.log(f"[bold red]ERROR[/bold red]    [DOWNLOADER] No output file found in {work_dir}")
                    return False
                
                temp_mkv = os.path.join(work_dir, out_files[0])
                if os.path.exists(temp_mkv):
                    if os.path.exists(final_dest): os.remove(final_dest)
                    
                    # Retry loop for Windows IO locks
                    for i in range(5):
                        try:
                            shutil.move(temp_mkv, final_dest)
                            progress.console.log(f"[bold green]INFO[/bold green]     [DOWNLOADER] Saved to: {final_dest}")
                            return True
                        except PermissionError: 
                            time.sleep(2) # Give it 2s for file release
                    
                    # Last ditch effort
                    try:
                        shutil.copy2(temp_mkv, final_dest)
                        os.remove(temp_mkv)
                        return True
                    except: pass
                return False
            except Exception as e:
                logging.error(f"[DOWNLOADER] yt-dlp strategy failed: {e}")
                return False
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

    def _sanitize_title(self, title):
        """Clean title for file system."""
        return re.sub(r'[^\w\s-]', '', str(title)).strip().replace(" ", "_")

    def _is_special_track(self, sub):
        """Identify program/CC tracks that need extra attention."""
        lbl = (sub.get('label') or "").lower()
        lang = (sub.get('language') or "").lower()
        # "ohjelma" = program, "hoh" = hard of hearing
        return any(x in lang for x in ["qag"]) or any(x in lbl for x in ["ohjelma", "program", "hoh", "cc"])

    def _extract_subs_from_folder(self, temp_title, clean_title):
        """Post-download cleanup for SRT files left by N_m3u8DL-RE."""
        for f in os.listdir(self.output_dir):
            if f.startswith(temp_title) and f.endswith(".srt"):
                suffix = "fi"
                if "qag" in f.lower() or "ohjelma" in f.lower():
                    suffix = "fi.program_subtitles"
                elif "fi" not in f.split("."):
                     parts = f.replace(temp_title, "").strip(".").split(".")
                     if parts: suffix = f"fi.{parts[0]}"
                
                new_p = os.path.join(self.output_dir, f"{clean_title}.{suffix}.srt")
                # Handle duplicates
                c = 1
                while os.path.exists(new_p):
                    new_p = os.path.join(self.output_dir, f"{clean_title}.{suffix}.{c}.srt")
                    c += 1
                
                try: shutil.move(os.path.join(self.output_dir, f), new_p)
                except: pass
