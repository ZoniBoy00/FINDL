import os
import re
import requests
import logging
import subprocess
import shutil
from ..config import NM3U8DL_RE_PATH, CHROME_UA

class SubtitleManager:
    def __init__(self, output_dir="downloads", languages=["fi", "fin", "suomi", "qag"]):
        self.output_dir = output_dir
        self.languages = languages
        self.exe = NM3U8DL_RE_PATH
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def process_subtitles(self, subtitles, timestamp=None):
        mux_args = []
        downloaded_files = []
        
        if not subtitles:
            return mux_args, downloaded_files

        if not timestamp:
            import time
            timestamp = int(time.time())

        logging.info(f"[SUBS] Processing {len(subtitles)} subtitle tracks...")

        for idx, sub in enumerate(subtitles):
            try:
                lang = sub.get('language', 'unknown').lower()
                url = sub.get('url')
                label = sub.get('label') or lang
                
                if not url: continue

                # Hyväksytään fi, qag tai labelit joissa lukee ohjelma/CC
                is_target = any(l in lang for l in self.languages)
                is_hoh = label and any(h in label.lower() for h in ["ohjelma", "program", "hoh", "cc"])
                
                if not is_target and not is_hoh:
                    continue

                lang_clean = re.sub(r'[^\w]', '', lang)
                safe_label = re.sub(r'[^\w]', '', str(label))
                
                # Asetetaan lopullinen SRT-polku
                filename_base = f"extsub_{idx}_{lang_clean}_{safe_label}_{timestamp}"
                filepath_srt = os.path.abspath(os.path.join(self.output_dir, filename_base + ".srt"))

                # Tunnistetaan onko kyseessä segmentoitu tekstitys (m3u8) by checking extension or content
                is_segmented = ".m3u8" in url
                if not is_segmented:
                     try:
                        # Quick check if it's a playlist
                        is_segmented = self._is_hls(url)
                     except: pass

                if is_segmented:
                    logging.info(f"[SUBS] Segmented subtitle detected, using N_m3u8DL-RE for '{label}'")
                    if self._download_with_tool(url, filepath_srt):
                        downloaded_files.append(filepath_srt)
                    else:
                        logging.warning(f"[SUBS] Tool download failed for {url}")
                        continue
                else:
                    # Tavallinen VTT-tiedosto
                    temp_vtt = os.path.join(self.output_dir, filename_base + ".vtt")
                    if self._download_file(url, temp_vtt):
                        if self._convert_vtt_to_srt(temp_vtt, filepath_srt):
                            downloaded_files.append(filepath_srt)
                            try: os.remove(temp_vtt)
                            except: pass
                        else:
                            # Conversion failed, maybe keep VTT
                            downloaded_files.append(temp_vtt)
                            filepath_srt = temp_vtt
                    else:
                        continue

                if not os.path.exists(filepath_srt) or os.path.getsize(filepath_srt) < 10:
                    logging.warning(f"[SUBS] Skipping empty/missing subtitle: {filepath_srt}")
                    continue

                # Valmistellaan mux-argumentit
                # Ohjelmatekstitys (qag) merkataan fi-koodilla, jotta soittimet tunnistavat sen
                lang_code = "fi" if ("fi" in lang or "qag" in lang) else lang_clean[:3]
                rel_path = os.path.relpath(filepath_srt)
                
                # Check for characters invalid in command line for mux-import if needed, but relative path is usually safe
                # Note: N_m3u8DL-RE uses ':' as separator in mux-import, so paths cannot have ':' (except drive letter which we handled by rel_path)
                
                mux_args.extend(["--mux-import", f'path={rel_path}:lang={lang_code}:name={label}'])
            
            except Exception as e:
                logging.warning(f"[SUBS] Failed to process subtitle: {e}")

        return mux_args, downloaded_files

    def _is_hls(self, url):
        try:
            r = requests.get(url, stream=True, timeout=5)
            first_line = next(r.iter_lines()).decode()
            return first_line.startswith("#EXTM3U")
        except: return False

    def _download_with_tool(self, url, output_path):
        """Käyttää m3u8dl-re:tä lataamaan ja muuntamaan SRT:ksi"""
        import time
        ts = int(time.time()*1000)
        temp_name = f"sub_dl_tmp_{ts}"
        cmd = [
            self.exe, url,
            "--save-name", temp_name,
            "--save-dir", self.output_dir,
            "--sub-format", "SRT",
            "--log-level", "OFF"
        ]
        try:
            subprocess.run(cmd, check=False)
            # Etsitään lopputulos (lataaja voi lisätä kielikoodeja nimeen)
            # N_m3u8DL-RE might name it temp_name.en.srt or just temp_name.srt
            found_file = None
            for f in os.listdir(self.output_dir):
                if f.startswith(temp_name) and f.endswith(".srt"):
                    found_file = os.path.join(self.output_dir, f)
                    break
            
            if found_file:
                if os.path.exists(output_path): os.remove(output_path)
                shutil.move(found_file, output_path)
                
                # Clean up other temp files from this batch
                for f in os.listdir(self.output_dir):
                    if f.startswith(temp_name):
                        try:
                            os.remove(os.path.join(self.output_dir, f))
                        except: pass
                # Also remove the _tmp folder created by RE if it exists
                tmp_dir = os.path.join(self.output_dir, "_tmp_" + temp_name) 
                # Note: N_m3u8DL-RE default tmp dir structure might differ based on config
                # We passed --save-dir self.output_dir, so it might create artifacts there.
                
                return True
        except Exception as e: 
            logging.warning(f"[SUBS] Tool execution error: {e}")
        return False

    def _convert_vtt_to_srt(self, vtt_path, srt_path):
        try:
            if os.path.getsize(vtt_path) == 0:
                return False

            with open(vtt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            srt_lines = []
            counter = 1
            i = 0
            
            # Skip header
            while i < len(lines):
                line = lines[i].strip()
                if "-->" in line: break
                if i+1 < len(lines) and lines[i+1].strip() and "-->" in lines[i+1]: break # Cue number
                i += 1
                
            for j in range(i, len(lines)):
                line = lines[j].strip()
                if "-->" in line:
                    srt_lines.append(f"{counter}")
                    srt_lines.append(line.replace('.', ','))
                    counter += 1
                elif line:
                    # Remove tags
                    clean = re.sub(r'<[^>]+>', '', line)
                    srt_lines.append(clean)
                else:
                    srt_lines.append("")
            
            if not srt_lines: return False
            
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(srt_lines))
            return True
        except: return False

    def _download_file(self, url, filepath):
        try:
            res = requests.get(url, timeout=30)
            if res.ok:
                with open(filepath, "wb") as f: f.write(res.content)
                return True
        except: return False

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python -m findl.core.subtitles <URL> [LANG]")
    else:
        url = sys.argv[1]
        lang = sys.argv[2] if len(sys.argv) > 2 else "fi"
        sm = SubtitleManager()
        sm.process_subtitles([{"url": url, "language": lang}])
