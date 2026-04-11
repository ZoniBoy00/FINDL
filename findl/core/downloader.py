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

from findl.config import NM3U8DL_RE_PATH, SHAKA_PACKAGER_PATH, TEMP_DIR, CHROME_UA, DEFAULT_HEADERS
from findl.ui.display import UI, console
from findl.core.subtitles import SubtitleManager

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
        ruutu_headers = []
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
            "--thread-count", "64",
            "--concurrent-download", "True",
            "--download-retry-count", "30",
            "--http-request-timeout", "120",
            "--decryption-engine", "SHAKA_PACKAGER",
            "--decryption-binary-path", self.packager,
            "--select-video", "best",
            "--select-audio", "best",
            "-M", "format=mkv",
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
            f"Referer: {origin}/",
            "Accept-Encoding: gzip, deflate",
            "Cache-Control: no-cache"
        ]
        if cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            header_list.append(f"Cookie: {cookie_str}")

        if is_ruutu:
            # High-stealth browser imitation for Ruutu (Nelonen)
            # Add token first to ruutu_headers (before the duplicate check later)
            if token:
                ruutu_headers.append(f"X-AxDRM-Message: {token}")
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
        
        ydl_headers = {}
        if cookies or license_headers:
            for k, v in (license_headers or {}).items():
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
            'extractor_args': {'generic': {'impersonate': 'chrome'}},
            'socket_timeout': 60,
            'retries': 10,
            'http_headers': ydl_headers,
            'noprogress': True,
            'overwrites': True,
            'nopart': True,
            'updatetime': False,
            'windowsfilenames': True,
            'http_header_overrides': {
                'hls': {
                    'User-Agent': CHROME_UA,
                    'Referer': 'https://areena.yle.fi/',
                    'Origin': 'https://areena.yle.fi'
                } if 'yle' in (original_url or url).lower() else {}
            }
        }
        
        if not skip_subs:
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = ['fi', 'sv', 'en', 'und']
            ydl_opts['subtitlesformat'] = 'srt'
        
        # Pass cookies if available
        if cookies:
            # Determine domain: if URL has 'yle', use .yle.fi
            target_domain = ".yle.fi" if "yle.fi" in (original_url or url).lower() else ".mtv.fi"
            ydl_opts['cookiefile'] = self._write_temp_cookies(cookies, domain=target_domain)

        try:
            console.log(f"[bold cyan]INFO[/bold cyan]     [DOWNLOADER] Engaging yt-dlp engine...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Filename detection (yt-dlp might change extension or name)
            temp_video = os.path.join(work_dir, "video.mkv")
            if not os.path.exists(temp_video):
                # Try to find any mkv in work dir
                for f in os.listdir(work_dir):
                    if f.endswith('.mkv'):
                        temp_video = os.path.join(work_dir, f)
                        break
            
            if os.path.exists(temp_video):
                # Move to final destination
                if os.path.exists(final_dest):
                    os.remove(final_dest)
                shutil.move(temp_video, final_dest)
                
                # Copy subtitle files if they exist
                if not skip_subs:
                    for sub_file in os.listdir(work_dir):
                        if sub_file.endswith(('.srt', '.vtt')):
                            sub_ext = '.srt' if sub_file.endswith('.srt') else '.vtt'
                            sub_lang = sub_file.replace('video.', '').replace('.srt', '').replace('.vtt', '')
                            dest_sub = os.path.join(self.output_dir, f"{clean_title}.{sub_lang}{sub_ext}")
                            if not os.path.exists(dest_sub):
                                try:
                                    shutil.copy(os.path.join(work_dir, sub_file), dest_sub)
                                except: pass
                
                console.log(f"[bold cyan]INFO[/bold cyan]     [DOWNLOADER] Saved to: {final_dest}")
                return True
            else:
                console.log(f"[bold red]ERROR[/bold red]     [DOWNLOADER] yt-dlp strategy failed: No output file found")
                return False
                
        except Exception as e:
            console.log(f"[bold red]ERROR[/bold red]     [DOWNLOADER] yt-dlp strategy failed: {e}")
            return False
        finally:
            # Cleanup
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except: pass

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
