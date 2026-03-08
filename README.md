# EasyWorship 7 Song Import/Export Tool

A Python GUI tool for importing and exporting songs from EasyWorship 7 databases. Built for managing Sinhala Christian hymn lyrics, but works with any language.

## Features

- **Export** all songs from EW7 to plain text files (one per song or all-in-one)
- **Import** songs from `.txt` files back into EW7 with duplicate detection
- **RTF parsing** — handles EW7's custom RTF format with full Unicode/Sinhala support
- **Search index rebuild** — automatically updates SongKeys.db after import
- **Auto-detect** EW7 database location (supports multiple profiles)
- **Backup** — creates timestamped backups before any write operation
- **tkinter GUI** — no external dependencies, runs on any Python 3.x

## Requirements

- Python 3.6+
- Windows (for EW7 database access)
- No pip dependencies — uses only Python standard library

## Usage

```bash
python ew_tool.py
```

The GUI will open with:
1. **Database path** — auto-detects your EW7 installation, or browse manually
2. **Export Songs** — exports all songs to `.txt` files
3. **Import Songs** — imports from `.txt` files or folders
4. **Backup Databases** — creates timestamped backups

### EW7 Database Location

The tool searches these paths automatically:
```
C:\Users\Public\Documents\Softouch\EasyWorship\{Profile}\v6.1\Databases\Data\
C:\Users\Public\Documents\Softouch\EasyWorship\{Profile}\Databases\Data\
```

You can also browse to any folder containing `SongHistory.db`, `SongWords.db`, and `SongKeys.db`.

## Text File Format

Songs are stored as UTF-8 `.txt` files:

```
---
title: Song Title In Singlish
title_sinhala: සිංහල මාතෘකාව
author: Artist Name
copyright: Copyright Info
ccli:
book_ref: #B164
source: ew7_export
---

First verse line 1
First verse line 2

[SLIDE]

Second verse / chorus
```

- `---` wraps the metadata header
- `[SLIDE]` marks slide breaks (maps to `\sdslidemarker` in EW7 RTF)
- `===` separates multiple hymns in a single file
- UTF-8 encoding throughout

## Related Tools

These scrapers generate `.txt` files in the same format for import:

| Branch | Tool | Source |
|--------|------|--------|
| `feature/kgp-scraper` | `kgp_scraper.py` | [Kithunu Gee Potha](http://chamathwebs.com/kgp/) (~770 hymns) |
| `feature/kbgd-scraper` | `kbgd_scraper.py` | [Kithu Bathi Gee Dahana](https://kithubathigeedahana.lk/) (668 hymns) |

## Database Schema

See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for full EW7 database documentation.
