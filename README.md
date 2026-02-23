# FINDL - Finnish Stream Downloader

Unified video downloader for Finnish streaming services, specializing in **MTV Katsomo**, **Ruutu**, **Yle Areena**, and **Viaplay**.

Built with **Python**, utilizing **Playwright** for intelligent extraction, **N_m3u8DL-RE** for high-performance downloading, and **yt-dlp** for specialized HLS/DASH services.

## 🚀 Key Features

### 📺 Series & Season Support
- **Automatic Crawling**: Provide a series URL, and FINDL will find all seasons and episodes.
- **Bulk Selection**: Choose to download individual episodes, ranges (e.g., `1-5`), or the entire series at once.
- **Smart Metadata**: Automatically extracts series titles, season numbers, and episode names.
- **Clean Naming**: Enforces a standard naming convention (`01 - Episode Name.mkv`) for perfect media server compatibility (Plex/Kodi).

### 📂 Automatic Organization
- **Smart Folders**: Automatically creates a directory structure: `Downloads / [Series Name] / [Season X] / [Episode].mkv`.
- **Sanitized Paths**: Automatically cleans titles of system-illegal characters.

### 🇫🇮 Supported Services

#### MTV Katsomo
- **Full Video & Audio**: Downloads highest quality video and audio streams.
- **Advanced Subtitles**: Automatically fetches standard Finnish subtitles and **Program Subtitles**.
- **DRM Handling**: Automatically extracts PSSH and acquires Widevine L3 keys.

#### Ruutu
- **Series Archiving**: Supports full series and season downloads for Ruutu+.
- **Ultra-Strict DRM**: Bypasses Axinom's strict header checks and session validation (CMCD).
- **Subtitle Extraction**: Automatically parses and labels program subtitles.

#### Yle Areena
- **Single Videos & Series**: Handles both movie URLs and series pages interchangeably.
- **Windows Optimized**: Custom "Temp-and-Move" strategy to prevent file locking issues (`WinError 32`).
- **Clean Lists**: Intelligently filters out recommendations and language selectors.

#### Viaplay (Beta)
- **Metadata Extraction**: Extracts rich metadata including production year and synopsis.
- **SAMI Subtitles**: Custom converter for Viaplay's SAMI subtitle format to standard SRT.
- **Series Discovery**: Crawls seasons and episodes using Playwright.

## 📋 Prerequisites

### 1. Python
- **Python 3.10+** is required.

### 2. Required Binaries
The project relies on these external tools. Please ensure they are in your system PATH or placed in the `bin/` directory:
- [**N_m3u8DL-RE**](https://github.com/nilaoda/N_m3u8DL-RE): Stream downloader and muxer.
- [**Shaka Packager**](https://github.com/shaka-project/shaka-packager): Required for DRM decryption.
- [**ffmpeg**](https://ffmpeg.org/): Essential for muxing and subtitle conversion.

### 3. Widevine Device
A valid Widevine L3 device file (`.wvd`) is required for DRM decryption. 
- Place your `device.wvd` in the project root.

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/ZoniBoy00/FINDL.git
cd FINDL

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## ▶️ Usage

Basic download:
```bash
python main.py "URL_TO_VIDEO"
```

### Advanced Options:
- `--output <path>`: Change the download directory (default: `downloads`).
- `--title "<name>"`: Manually set the output filename.
- `--no-subs`: Skip subtitle processing.
- `--pssh <pssh>`: Manually provide PSSH if extraction fails.

## ⚠️ Disclaimer
This tool is for educational and personal use only. The author is not responsible for any misuse. Respect the Terms of Service of the streaming providers and copyright laws.

---
*Created with ❤️ for the Finnish streaming community.*
