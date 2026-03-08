# EasyWorship 7 Database Import/Export Tool — Implementation Plan

## Overview
A Python GUI application (tkinter) that can export songs from EW7 databases to `.txt` files and bulk import `.txt` files back into EW7 databases, with full RTF and Unicode support.

## Architecture

### Single-file approach: `ew_tool.py`
One self-contained Python file with no external dependencies (only stdlib: `tkinter`, `sqlite3`, `re`, `os`, `shutil`, `uuid`, `datetime`, `time`).

### GUI Layout (tkinter)

```
┌─────────────────────────────────────────────────────┐
│  EasyWorship 7 Song Manager                    [—][×]│
├─────────────────────────────────────────────────────┤
│  Database Folder: [________________________] [Browse]│
├────────────┬────────────────────────────────────────┤
│  Song List │   Song Preview                         │
│  ┌───────┐ │   ┌──────────────────────────────────┐ │
│  │ Song1 │ │   │  Title: Uswu usaswu              │ │
│  │ Song2 │ │   │  Author:                          │ │
│  │ Song3 │ │   │  Copyright: SMC Media             │ │
│  │ Song4 │ │   │  CCLI:                            │ │
│  │  ...  │ │   │──────────────────────────────────│ │
│  │       │ │   │  [Lyrics plain text preview]      │ │
│  │       │ │   │                                    │ │
│  └───────┘ │   └──────────────────────────────────┘ │
├────────────┴────────────────────────────────────────┤
│  [Export All]  [Export Selected]  [Import Songs]     │
│  Status: Ready                                       │
└─────────────────────────────────────────────────────┘
```

### Core Modules (within the single file)

1. **Database Layer** — `EWDatabase` class
   - Connects to SongHistory.db + SongWords.db + SongKeys.db
   - Registers `UTF8_U_CI` collation
   - Read songs, read lyrics, write songs, write lyrics
   - Rebuild search index in SongKeys.db after import

2. **RTF Parser** — `rtf_to_text()` function
   - Stack-based RTF parser (inspired by ew61-export)
   - Handles `\uNNNN?` Unicode escapes
   - Recognizes EW-specific control words (`\sdslidemarker` → slide break)
   - Strips formatting, preserves text and structure

3. **RTF Generator** — `text_to_rtf()` function
   - Converts plain text back to EW-compatible RTF
   - Encodes non-ASCII as `\uNNNN?`
   - Adds EW-specific headers and slide markers
   - Preserves font/style template defaults from existing songs

4. **Export Module** — `export_songs()`
   - Exports to `.txt` with metadata header block:
     ```
     ---
     title: Song Title
     author: Author Name
     copyright: Copyright Info
     ccli: 12345
     ---

     Verse lyrics line 1
     Verse lyrics line 2

     [SLIDE]

     Chorus lyrics line 1
     ...
     ```

5. **Import Module** — `import_songs()`
   - Parses `.txt` files with metadata header
   - Generates `song_uid` in EW format: `1-{UUID}`
   - Inserts into SongHistory.db and SongWords.db
   - Rebuilds SongKeys.db search index
   - Duplicate detection by title

6. **Backup Module** — `backup_databases()`
   - Creates timestamped backup copies before any write
   - Format: `SongHistory.db.bak.20260308_120000`
   - Validates backup integrity with `PRAGMA integrity_check`

### Import Flow
1. User selects folder with `.txt` files → Browse dialog
2. Tool shows preview list of songs to import
3. User clicks "Import" → backup created → songs inserted
4. Search index rebuilt → status shown

### Export Flow
1. User browses to EW database folder
2. Song list populates with all songs
3. User selects songs (or "Export All")
4. User chooses output folder → `.txt` files created

## Key Technical Decisions

- **tkinter**: Built into Python, no pip install needed — important since this runs on church computers
- **Single file**: Easy to distribute, just copy `ew_tool.py`
- **SongHistory.db as metadata source**: This is where EW7 stores song metadata (not a separate Songs.db)
- **`[SLIDE]` marker in .txt**: Maps to `\sdslidemarker` in RTF, preserves slide boundaries
- **YAML-style header in .txt**: Simple, human-readable metadata block
- **Search index rebuild**: After import, tokenize song text and rebuild SongKeys.db word_key/word_list tables

## File Output
- `ew_tool.py` — the complete GUI application
- `DATABASE_SCHEMA.md` — full database documentation
