# FINDL - Finnish Stream Downloader

Unified video downloader for Finnish streaming services, specializing in **MTV Katsomo**, **Ruutu**, **Yle Areena**, **SF Anytime**, and **Viaplay**.

Built with **Python**, utilizing **Playwright** for intelligent extraction and **N_m3u8DL-RE** for high-performance downloading.

**Version: 0.0.3**

This development version includes runtime validation, safer logging, resumable temporary downloads, and consistent metadata-based filenames across supported services.

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

#### Viaplay
- Full video & audio in highest quality
- DRM handling via thePlatform/Widevine (multi-strategy key acquisition)
- Series & season support via Viaplay Content API
- Batch episode downloading with smart sequencing
- SAMI to SRT subtitle conversion
- CDN routing optimization (cdn7)
- Concurrent stream slot management
- Smart metadata extraction (title, season, episode) from API

#### SF Anytime
- Movie archiving with Axinom DRM
- Automatic license token interception
- WidevineProxy2-style response logic
- High-quality DASH/MPD stream support

## Project Structure

```
findl/
├── __init__.py                  # Main module exports
├── config.py                    # Centralized configuration
├── config/
│   └── __init__.py              # Centralized configuration (alt)
├── core/
│   ├── config.py                # DRM settings
│   ├── downloader_config.py     # Download settings
│   ├── drm.py                   # Widevine DRM handling
│   ├── downloader.py            # Download logic (N_m3u8DL-RE)
│   └── subtitles.py             # Subtitle management & conversion
├── services/
│   ├── base.py                  # BaseExtractor with common helpers
│   ├── katsomo/
│   │   ├── config.py            # Service-specific settings
│   │   └── extractor.py         # Katsomo extraction logic
│   ├── ruutu/
│   │   ├── config.py
│   │   └── extractor.py
│   ├── yle/
│   │   ├── config.py
│   │   └── extractor.py
│   ├── viaplay/
│   │   ├── config.py
│   │   └── extractor.py
│   └── sfanytime/
│       ├── config.py
│       └── extractor.py
├── ui/
│   └── display.py               # Rich UI components
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

### Runtime checks

FINDL checks its Python modules and required external tools before starting a download. Configure paths in `.env` when the binaries are not located in `bin/`:

```env
OUTPUT_DIR=downloads
WVD_PATH=device.wvd
NM3U8DL_RE_PATH=bin/N_m3u8DL-RE.exe
SHAKA_PACKAGER_PATH=bin/packager-win-x64.exe
```

Run commands from any directory; project-relative paths are resolved from the FINDL installation directory. If a download fails, temporary files are retained so the downloader can resume using the same title on the next attempt.

FINDL resolves media names in this order: service metadata title, page/extractor title, and finally the URL slug. Generic provider titles such as `Viaplay`, `Ruutu`, `Yle Areena`, and `Video` are ignored. Decryption keys, cookies, bearer tokens and license tokens are hidden from the console and application logs.

### Tests

Install the development test runner and run:

```bash
pip install pytest
pytest -q
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
| `--keys` | Manual DRM keys (format: `kid:key`, repeatable) |
| `--key-file` | File containing DRM keys (one `kid:key` per line) |

### Naming Examples

| Type | Output |
|------|--------|
| Series Episode | `downloads/SeriesName/Season 1/SeriesName_S05E03_EpisodeTitle.mkv` |
| Movie | `downloads/MovieTitle.mkv` |
| Bulk Download | `downloads/SeriesName/Season 4/` |

### Download Speed
- **Optimized**: Uses 16 concurrent threads for maximum speed
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
┌──────────────────────────────────────────────────┐
│                    main.py                       │
│              (CLI & orchestration)                │
└──────────────────────┬───────────────────────────┘
                       │
     ┌─────────┬───────┼───────┬──────────┐
     ▼         ▼       ▼       ▼          ▼
┌────────┐┌───────┐┌──────┐┌────────┐┌──────────┐
│Katsomo ││ Ruutu ││ Yle  ││Viaplay ││SF Anytime│
└───┬────┘└───┬───┘└──┬───┘└───┬────┘└────┬─────┘
    └─────────┴───────┴────────┴──────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
   BaseExtractor            SubtitleManager
   (shared helpers)         (VTT/SAMI→SRT)
          │
    ┌─────┼──────────┐
    ▼     ▼          ▼
┌────────┐┌─────────┐┌──────────┐
│  DRM   ││Download ││    UI    │
│Handler ││  er     ││ Display  │
│(WV/TP) ││(N_m3u8) ││ (Rich)   │
└────────┘└─────────┘└──────────┘
```

## Disclaimer
This tool is for educational and personal use only. The author is not responsible for any misuse. Respect the Terms of Service of streaming providers and copyright laws.

---
*Created for the Finnish streaming community.*
