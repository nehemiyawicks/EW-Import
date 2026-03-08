# KGP Scraper — Kithunu Gee Potha Hymn Lyrics

Scrapes Sinhala hymn lyrics from [Kithunu Gee Potha](http://www.chamathwebs.com/kgp/) (~770 hymns) and outputs `.txt` files compatible with `ew_tool.py`.

## Source

- **Website**: http://www.chamathwebs.com/kgp/index.asp
- **Content**: ~770 Sinhala Christian hymns with singlish transliterations
- **Format**: Static HTML pages, no chords
- **Status**: Site is currently down (as of March 2026). Scraper is ready for when it returns.

## Requirements

```bash
pip install requests beautifulsoup4
```

Falls back to stdlib `urllib` if not installed (limited parsing).

## Usage

```bash
# Scrape all hymns (with caching)
python kgp_scraper.py

# Force fresh fetch (ignore cache)
python kgp_scraper.py --no-cache

# Process only cached files (offline mode)
python kgp_scraper.py --cache-only

# Custom output directory
python kgp_scraper.py --output /path/to/output
```

## Output

- Files are written to `output/kgp/` (one `.txt` per hymn)
- Cached HTML stored in `cache/kgp/` for offline re-processing
- Rate limited: 1.5s between requests

### Output Format

```
---
title: Aa Haa Balanuva Ekamuthu Vemu
title_sinhala: ආ... හා... බලනුව (එකමුතු වෙමු)
author:
copyright:
ccli:
book_ref: #B164
source: kgp
---

සිංහල lyrics line 1
සිංහල lyrics line 2

[SLIDE]

සිංහල chorus line 1
```

## How It Works

1. Fetches the index page listing all hymns with metadata
2. Parses each entry for: hymn number, Sinhala title, singlish transliteration, book reference
3. Fetches individual hymn pages for properly formatted lyrics
4. Detects verse structure from HTML formatting → `[SLIDE]` markers
5. Writes `.txt` files in the common format

## Importing to EasyWorship 7

Use the main tool on the `main` branch:

```bash
python ew_tool.py
# Then: Import Songs → select the output/kgp/ folder
```
