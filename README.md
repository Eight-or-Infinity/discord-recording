# Bridge Recording Processor

Processes Craig Discord bot audio recordings, combining multiple parts into single mixed audio files.

## Requirements

- **Python 3.8+**
- **ffmpeg** — must be installed and in PATH
- **Playwright** — install with:
  ```bash
  pip install playwright && playwright install chromium
  ```

## Scripts

### 1. download_files.py

Downloads OGG Vorbis audio files from Craig Discord bot links using Playwright.

```bash
python download_files.py <url> [-o output_dir] [--skip-avatars]
```

**Arguments:**
- `url` — Craig bot URL (supports up to 4 URLs)
- `-o, --output-dir` — Output directory (default: current directory)
- `--skip-avatars` — Skip downloading avatar files

**Features:**
- Handles "Previous Download" detection to resume interrupted downloads
- Supports multiple URLs in a single session
- Normalizes audio automatically
- Downloads avatars separately if present

---

### 2. mixdown.py

Combines multiple OGG files from Craig recordings into single mixed tracks.

```bash
python mixdown.py <zip_file>
```

**Arguments:**
- `zip_file` — Path to a Craig recording ZIP file

**Features:**
- Groups related parts by timestamp (within 6-hour window)
- Creates two mixdowns:
  - One with Minerea tracks removed
  - One with Minerea tracks at -30dB
- Removes `raw.dat` files automatically
- Supports `-partN` suffix pattern for legacy grouping

---

## Installation

1. Ensure Python 3.8+ is installed
2. Install FFmpeg and add it to PATH
3. Install Playwright:
   ```bash
   pip install playwright && playwright install chromium
   ```

## Workflow

1. **Download** — Use `download_files.py` to fetch recordings from Craig bot links
2. **Mix** — Use `mixdown.py` to combine OGG files into mixed tracks