# FINDL - Finnish Stream Downloader

Unified video downloader for Finnish streaming services, specializing in **MTV Katsomo**, **Ruutu**, and **Yle Areena**.

Built with **Python**, utilizing **Playwright** for intelligent extraction, **N_m3u8DL-RE** for high-performance downloading, and **yt-dlp** for specialized HLS/DASH services.

## 🚀 Features

### MTV Katsomo
- **Full Video & Audio**: Downloads highest quality video and audio streams.
- **Advanced Subtitles**: 
  - Automatically fetches standard Finnish subtitles.
  - **Program Subtitles (Ohjelmatekstitys)**: Specialized support for tracks often missed by other tools (`qag` streams).
- **DRM Handling**: Automatically extracts PSSH and acquires Widevine L3 keys via header emulation.

### Ruutu
- **Free & Premium**: Supports downloading free and Ruutu+ content (requires valid cookies/session).
- **Ultra-Strict DRM**: Bypasses Axinom's strict header checks and session validation (CMCD) using specialized logic.
- **Subtitle Extraction**: Automatically parses and labels program subtitles from HLS/DASH streams.

### Yle Areena
- **yt-dlp Engine**: Uses a specialized high-performance engine for Yle-specific HLS/DASH streams.
- **Parallel Downloading**: Optimized fragment downloads for maximum speed.
- **Metadata**: Automatically embeds chapters and rich metadata.
- **Windows Optimized**: Custom "Temp-and-Move" strategy to prevent file locking issues (`WinError 32`).

## 🛠️ Tech Stack & Architecture

1.  **Extractors (`findl/services/`)**: Playwright navigates to the content, handles consent/cookies, and extracts manifests and PSSH data.
2.  **DRM Handler (`findl/core/drm.py`)**: Interacts with license servers using the Widevine L3 device.
3.  **Downloader (`findl/core/downloader.py`)**: 
    - **N_m3u8DL-RE Strategy**: Default for DRM-protected content (MTV, Ruutu).
    - **yt-dlp Strategy**: Default for Yle Areena, featuring beautiful `rich` progress bars and ETA.
4.  **Subtitle Manager**: Orchestrates the conversion of multiple formats (WebVTT, HLS-segments) into standard SRT.

## 📋 Prerequisites

### 1. Python
- **Python 3.10+** is required.

### 2. Required Binaries
The project relies on these excellent external tools. Please ensure they are in your system PATH or placed in the `bin/` directory:
- [**N_m3u8DL-RE**](https://github.com/nilaoda/N_m3u8DL-RE): Stream downloader and muxer.
- [**Shaka Packager**](https://github.com/shaka-project/shaka-packager): Required for DRM decryption.
- [**ffmpeg**](https://ffmpeg.org/): Essential for muxing and subtitle conversion.

### 3. Widevine Device
A valid Widevine L3 device file (`.wvd`) is required for DRM decryption. 
- Place your `device.wvd` in the project root.
- See `.env.example` for manual configuration options.

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

## ⚙️ Configuration
The tool can be configured via environment variables or a `.env` file. Copy the example to get started:
```bash
cp .env.example .env
```
Key settings:
- `WVD_PATH`: Path to your `.wvd` file.
- `OUTPUT_DIR`: Default downloads folder.

## ❓ Troubleshooting

- **WinError 32 (File in use)**: 
  - The tool uses a temporary directory to avoid this. If it persists, ensure your video player or Antivirus isn't locking files in `downloads` or `_tmp_findl`.
- **403 Forbidden (Yle Areena)**: The tool uses `yt-dlp` which handles Akamai tokens automatically. Ensure your `yt-dlp` is up to date (`pip install -U yt-dlp`).
- **DRM License Failure**: Indicates expired cookies or a blacklisted WVD. Clear the `findl_sessions` directory and ensure your `device.wvd` is fresh.

## ⚠️ Disclaimer
This tool is for educational and personal use only. The author is not responsible for any misuse. Respect the Terms of Service of the streaming providers and copyright laws.

---
*Created with ❤️ for the Finnish streaming community.*
