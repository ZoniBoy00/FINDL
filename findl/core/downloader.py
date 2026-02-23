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

    def download(self, manifest_url, keys, title="video", subtitles=None, origin="https://www.mtv.fi", skip_subs=False, use_ytdlp=False, original_url=None):
        """
        Main entry point for downloading. Routes to the appropriate strategy.
        """
        if use_ytdlp:
            # yt-dlp works best with the original page URL for Yle
            download_url = original_url if original_url else manifest_url
            return self.download_ytdlp(download_url, title, origin, skip_subs)
        
        return self.download_re(manifest_url, keys, title, subtitles, origin, skip_subs)

    def download_re(self, manifest_url, keys, title, subtitles, origin, skip_subs):
        """Standard download strategy using N_m3u8DL-RE."""
        ts = int(time.time())
        temp_title = f"fndl_{ts}"
        
        rel_output = os.path.relpath(self.output_dir)
        download_tmp = os.path.join(TEMP_DIR, f"t_{ts}")
        if not os.path.exists(download_tmp): os.makedirs(download_tmp)

        cmd = [
            self.exe, manifest_url,
            "-mt",
            "-H", f"User-Agent: {CHROME_UA}",
            "-H", f"Origin: {origin}",
            "-H", f"Referer: {origin}/",
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
            "--log-level", "INFO"
        ]

        # Handle Subtitles
        if skip_subs:
            cmd.extend(["--drop-subtitle", ".*"])
        else:
            cmd.extend(["--select-subtitle", "lang=fi|suomi|und"])
            cmd.extend(["--sub-format", "SRT"])
            
            # Manual processing for special tracks (qag/CC)
            manager_subs = [s for s in (subtitles or []) if self._is_special_track(s)]
            if manager_subs:
                try:
                    sm = SubtitleManager(output_dir=self.output_dir)
                    sub_args, _ = sm.process_subtitles(manager_subs, ts)
                    if sub_args: cmd.extend(sub_args)
                except Exception as e:
                    logging.warning(f"[DOWNLOADER] Manual subtitle download failed: {e}")

        # Add Decryption Keys
        if keys:
            for k in keys: cmd.extend(["--key", k])

        logging.info(f"[DOWNLOADER] Running N_m3u8DL-RE engine...")
        try:
            subprocess.run(cmd, check=False)
            
            clean_title = self._sanitize_title(title)
            final_path = os.path.join(self.output_dir, f"{clean_title}.mkv")
            
            temp_file = os.path.join(self.output_dir, f"{temp_title}.mkv")
            if not os.path.exists(temp_file):
                temp_file = os.path.join(self.output_dir, f"{temp_title}.MUX.mkv")

            if os.path.exists(temp_file):
                if os.path.exists(final_path): os.remove(final_path)
                shutil.move(temp_file, final_path)
                logging.info(f"[DOWNLOADER] Saved to: {final_path}")
                self._extract_subs_from_folder(temp_title, clean_title)
                return True
            return False
        except Exception as e:
            logging.error(f"[DOWNLOADER] RE Strategy failed: {e}")
            return False
        finally:
            shutil.rmtree(download_tmp, ignore_errors=True)

    def download_ytdlp(self, url, title, origin, skip_subs=False):
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

            ydl_opts = {
                'outtmpl': work_tmpl,
                'format': 'bestvideo+bestaudio/best',
                'merge_output_format': 'mkv',
                'quiet': True,
                'noprogress': True,
                'no_warnings': True,
                'overwrites': True,
                'nopart': True,              
                'updatetime': False,         
                'windowsfilenames': True,    
                'writesubtitles': True,      
                'writeautomaticsub': True,   
                'subtitleslangs': ['all'],   
                'subtitlesformat': 'srt/vtt/best',
                'concurrent_fragment_downloads': 5,
                'add_metadata': True,
                'progress_hooks': [ytdlp_progress_hook],
                'postprocessor_hooks': [ytdlp_post_hook],
                'postprocessors': [
                    {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
                    {'key': 'FFmpegEmbedSubtitle'}
                ]
            }

            try:
                progress.console.log(f"[bold cyan]INFO[/bold cyan]     [DOWNLOADER] Engaging yt-dlp engine...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Assembly
                out_files = [f for f in os.listdir(work_dir) if f.endswith(".mkv") or f.endswith(".mp4")]
                if not out_files: return False
                
                temp_mkv = os.path.join(work_dir, out_files[0])
                if os.path.exists(temp_mkv):
                    if os.path.exists(final_dest): os.remove(final_dest)
                    # Retry loop for Windows IO locks
                    for i in range(5):
                        try:
                            shutil.move(temp_mkv, final_dest)
                            progress.console.log(f"[bold green]INFO[/bold green]     [DOWNLOADER] Saved to: {final_dest}")
                            return True
                        except PermissionError: time.sleep(1)
                    
                    # Last ditch effort
                    shutil.copy2(temp_mkv, final_dest)
                    os.remove(temp_mkv)
                    return True
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
