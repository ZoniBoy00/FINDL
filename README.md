# FINDL - Finnish Stream Downloader

Unified video downloader for Finnish streaming services, specializing in **MTV Katsomo**, **Ruutu**, **Yle Areena**, and **Viaplay**.

Built with **Python**, utilizing **Playwright** for intelligent extraction, **N_m3u8DL-RE** for high-performance downloading, and **yt-dlp** for specialized HLS/DASH services.

**Version: 0.0.3**

## Features

### Smart Naming Convention
- **Series Episodes**: `SeriesName_S05E03_EpisodeTitle.mkv`
- **Movies**: `MovieTitle.mkv` (no season/episode info)
- **Organized Folders**: `Downloads / Series Name / Season X /`
- **Auto-cleaning**: Removes Finnish words like "Jakso", "Kausi" from episode titles
- **Season detection**: Properly detects season from episode titles (e.g., "Jakso 1 - Kausi 6")

### Series & Season Support
- **Automatic Crawling**: Provide a series URL, FINDL finds all seasons and episodes.
- **Smart Episode Selection**: Download episodes with flexible selection:
  - `S1` - Season 1 only
  - `S1,S3` - Seasons 1 and 3
  - `S5-7` - Seasons 5 through 7
  - `S5:1-5` - Episodes 1-5 from Season 5
  - `S5:1,3,5` - Episodes 1, 3, 5 from Season 5
  - `S5:1 S6:1 S7:1` - Episode 1 from multiple seasons
  - `1-5` - Episodes 1-5 from list
  - `all` - All episodes
- **Sorted Display**: Episodes properly sorted by season and episode number
- **Smart Metadata**: Extracts series titles, season numbers, and episode names.

### Automatic Organization
- **Smart Folders**: `Downloads / [Series Name] / [Season X] / [Episode].mkv`
- **Sanitized Paths**: Cleans illegal characters from titles.

### Comprehensive Logging
- **File Logging**: Logs saved to `bin/Logs/findl_YYYYMMDD.log`
- **Console Display**: Rich-formatted output with progress indicators
- **Debug Info**: Detailed logs for debugging extraction issues

### Anti-Detection & Automation
- **Browser Automation**: Built-in anti-detection scripts for Playwright.
- **BaseExtractor Helpers**: Reusable methods for browser setup, consent handling, and play buttons.

### Supported Services

#### MTV Katsomo
- Full Video & Audio in highest quality
- Advanced Subtitles (Finnish + Program Subtitles)
- DRM Handling via DRMToday
- Smart season detection from episode titles
- Proper episode sorting

#### Ruutu
- Series Archiving for Ruutu+
- Axinom DRM with strict header validation
- Automatic subtitle parsing and labeling
- Smart season detection from episode titles
- Proper episode sorting

#### Yle Areena
- Single Videos & Series support
- Windows-optimized "Temp-and-Move" strategy
- yt-dlp integration for HLS/DASH

#### Viaplay (WIP)
- Experimental support
- SAMI to SRT subtitle conversion
- Series discovery via Playwright

## Project Structure

```
findl/
├── __init__.py                  # Main module exports
├── config/
│   └── __init__.py              # Centralized configuration
├── core/
│   ├── config.py                # DRM settings
│   ├── downloader_config.py     # Download settings
│   ├── drm.py                   # Widevine DRM handling
│   ├── downloader.py            # Download logic (N_m3u8DL-RE, yt-dlp)
│   └── subtitles.py             # Subtitle management & conversion
├── services/
│   ├── base.py                  # BaseExtractor with common helpers
│   ├── katsomo/
│   │   ├── config.py            # Service-specific settings
│   │   └── extractor.py        # Katsomo extraction logic
│   ├── ruutu/
│   │   ├── config.py
│   │   └── extractor.py
│   ├── yle/
│   │   ├── config.py
│   │   └── extractor.py
│   └── viaplay/
│       ├── config.py
│       └── extractor.py
└── ui/
    └── display.py               # Rich UI components
```

### BaseExtractor Features

The `BaseExtractor` class provides reusable methods for all services:

```python
# Initialize browser with anti-detection
browser, page = self._init_playwright_browser(headless=False)

# Add anti-detection scripts
self._add_anti_detection(page)

# Click common consent buttons
self._click_consent_buttons(page)

# Click play buttons
self._click_play_button(page)

# Extract PSSH from manifest
pssh = self.get_pssh_from_manifest(url, cookies, headers)
```

## Prerequisites

### 1. Python
- **Python 3.10+** required

### 2. Required Binaries
Place in `bin/` directory or system PATH:
- [**N_m3u8DL-RE**](https://github.com/nilaoda/N_m3u8DL-RE): Stream downloader
- [**Shaka Packager**](https://github.com/shaka-project/shaka-packager): DRM decryption
- [**ffmpeg**](https://ffmpeg.org/): Muxing and conversion

### 3. Widevine Device
- Place `device.wvd` in project root

## Installation

```bash
# Clone the repository
git clone https://github.com/ZoniBoy00/FINDL.git
cd FINDL

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Usage

### Basic Download
```bash
python main.py "https://www.mtv.fi/..."
```

### Series Download
```bash
# Shows episode list with season/episode info, select which to download
python main.py "https://www.mtv.fi/ohjelma/..."
```

### Episode Selection Examples

```
Download Options:
  S1        Season 1 only
  S1,S3     Seasons 1 & 3
  S1-3      Seasons 1-3
  S1:1-5    Episodes 1-5 from S1
  S1:1,3,5  Episodes 1,3,5 from S1
  S1-3:10   Episode 10 from S1-3
  1-5       Episodes 1-5 from list
  1,3,5     Episodes 1,3,5 from list
  all       Download all
  (Separate multiple with space: S5:1 S6:1 S7:1)

Selection [all]: 
```

### Options
| Option | Description |
|--------|-------------|
| `--output` | Output directory (default: `downloads`) |
| `--title` | Manual filename |
| `--pssh` | Manual PSSH override |
| `--no-subs` | Skip subtitles |

### Naming Examples

| Type | Output |
|------|--------|
| Series Episode | `downloads/SeriesName/Season 1/SeriesName_S05E03_EpisodeTitle.mkv` |
| Movie | `downloads/MovieTitle.mkv` |
| Bulk Download | `downloads/SeriesName/Season 4/` |

### Download Speed
- **Optimized**: Uses 64 concurrent threads for maximum speed
- **Typical**: 10-70 MB/s depending on network and CDN

## Configuration

### Service-Specific Config
Each service has config in `findl/services/<service>/config.py`:
- Service URLs and domains
- DRM type and license settings
- Playwright options
- Cookie domains

### Core Config
- `findl/config/__init__.py` - Main app config
- `findl/core/config.py` - DRM settings
- `findl/core/downloader_config.py` - Download settings

### Environment Variables
Create `.env` file:
```env
OUTPUT_DIR=downloads
WVD_PATH=./device.wvd
NM3U8DL_RE_PATH=bin/N_m3u8DL-RE.exe
SHAKA_PACKAGER_PATH=bin/packager-win-x64.exe
```

## Logging

### File Logging
Logs are saved to `bin/Logs/findl_YYYYMMDD.log` with timestamp format:
```
2026-04-09 19:32:15 | INFO | [KATSOMO] PSSH sniffed from manifest (HLS Key)
2026-04-09 19:32:15 | INFO | [MAIN] Strategy select: N_m3u8DL-RE
```

### Console Display
- **Rich UI**: Formatted output with colors and progress bars
- **Levels**: INFO, DEBUG, WARNING, ERROR

Run with verbose logging:
```bash
# Set log level via Python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Architecture

```
┌─────────────────────────────────────────┐
│              main.py                    │
│         (CLI & orchestration)           │
└──────────────┬──────────────────────────┘
              │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
┌───────┐ ┌───────┐ ┌────────┐
│Katsomo│ │ Ruutu │ │  Yle   │ ... Extractors
│   │   │ │   │   │ │   │    │
│ └──┬──┘ │ └──┬──┘ │ └──┬───┘
│    ▼    │    ▼    ▼    │
│  BaseExtractor (shared helpers)          │
└────┬────┴────┬────┴─────┬────────────────┘
     ▼         ▼          ▼
┌────────┐ ┌────────┐ ┌─────────┐
│DRMHandler│ │Downloader│ │UI Display│
│(Widevine)│ │(N_m3u8DL)│ │ (Rich)   │
└─────────┘ └─────────┘ └──────────┘
```

## Disclaimer
This tool is for educational and personal use only. The author is not responsible for any misuse. Respect the Terms of Service of streaming providers and copyright laws.

---
*Created for the Finnish streaming community.*
