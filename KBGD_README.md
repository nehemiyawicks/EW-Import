# KBGD Scraper — Kithu Bathi Gee Dahana Hymn Scraper

Fetches Sinhala hymn lyrics from [Kithu Bathi Gee Dahana](https://www.kithubathigeedahana.lk/) (668 hymns), strips guitar chords, and outputs `.txt` files compatible with `ew_tool.py`.

## Source

- **Website**: https://www.kithubathigeedahana.lk/
- **API**: `/api/songs?limit=1000` (public, no auth required)
- **Content**: 668 Sinhala hymns with ChordPro chord notation
- **Titles**: 662/668 songs include both Sinhala and singlish titles

## Requirements

None — uses only Python standard library (`urllib`, `json`, `re`).

## Usage

```bash
# Fetch and process all hymns
python kbgd_scraper.py

# Force fresh API fetch (ignore cache)
python kbgd_scraper.py --no-cache

# Test mode: process first N songs with detailed output
python kbgd_scraper.py --test 5

# Custom output directory
python kbgd_scraper.py --output /path/to/output
```

## Output

- Files are written to `output/kbgd/` (one `.txt` per hymn)
- API response cached in `cache/kbgd/songs.json`
- **658 songs processed, 0 errors** (10 skipped — no lyrics)

### Output Format

```
---
title: Adahillen Enna
title_sinhala: ඇදහිල්ලෙන් එන්න
author: ගෞ . චාල්ස් ලුචව්
copyright:
ccli:
book_ref:
source: kbgd
---

ඇදහිල්ලෙන් එන්න - සමිඳූ වෙතට
හාස්කමක් කරයි සමිඳූ වෙත එන අයට

[SLIDE]

ඔබේ සිතේ දුකක් තිබේද සමිඳූ එය දකී
```

## Chord Stripping

The scraper removes all chord notation from lyrics:

| Type | Example | Action |
|------|---------|--------|
| Bracketed chords | `[Am]`, `[G7]`, `[D/F#]` | Removed |
| ChordPro directives | `{start_of_chorus}`, `{end_of_chorus}` | Converted to `[SLIDE]` |
| ChordPro metadata | `{composer: ...}`, `{title: ...}`, `{key: G}` | Removed |
| Chord metadata lines | `කෝඩ් සැකසුම : සමින්ද සිල්වා` | Removed |
| Chord-only lines | `Am  G  C  D` | Removed |

### Before (raw from API):
```
{start_of_chorus}
[G]ඇදහිල්ලෙන් එන්[G]න - [D]සමිඳූ වෙත[G]ට
[Em]හාස්කමක් ක[Am]රයි සමිඳූ [D]වෙත එන අය[G]ට
{end_of_chorus}
කෝඩ් සැකසුම : සමින්ද සිල්වා
{composer: ගෞ . චාල්ස් ලුචව්}
```

### After (clean lyrics):
```
ඇදහිල්ලෙන් එන්න - සමිඳූ වෙතට
හාස්කමක් කරයි සමිඳූ වෙත එන අයට
```

## API Details

| Endpoint | Description |
|----------|-------------|
| `GET /api/songs?limit=1000` | All songs with lyrics, chords, metadata |
| `GET /api/categories` | Song categories (නමස්කාරය, ස්තූති ගීතිකා, etc.) |

Song object fields: `id`, `song_name`, `artist`, `key`, `beat`, `lyrics_chords`, `category`, `youtube_link`, `like_count`

## Importing to EasyWorship 7

Use the main tool on the `main` branch:

```bash
python ew_tool.py
# Then: Import Songs → select the output/kbgd/ folder
```
