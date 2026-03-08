# EasyWorship 7 Database Schema

## Overview

EW7 stores its data in multiple SQLite database files located at:
```
C:\Users\Public\Documents\Softouch\EasyWorship\{ProfileName}\Databases\Data\
```
Default profile name is `Default`. Users can have multiple profiles.

## Song-Related Databases (Used by this tool)

### SongHistory.db

Stores song metadata and usage history.

```sql
CREATE TABLE song (
    rowid           INTEGER PRIMARY KEY,  -- Auto-increment, local song ID
    song_uid        TEXT,                 -- Format: "1-{UUID}" e.g. "1-DB84EBC9-1450-473E-9ECA-81557D713D01"
    title           TEXT,                 -- Song title (singlish/English for Sinhala songs)
    author          TEXT,
    copyright       TEXT,
    administrator   TEXT,
    reference_number TEXT                 -- Hymn book reference (e.g. "#B164")
);

CREATE TABLE action (
    rowid       INTEGER PRIMARY KEY,
    song_id     INTEGER,     -- References song.rowid
    date        DATETIME,    -- .NET ticks (100ns intervals since 0001-01-01)
    action_type INT8         -- 0 = created, 2 = modified
);
```

### SongWords.db

Stores song lyrics as RTF blobs.

```sql
CREATE TABLE word (
    rowid                   INTEGER PRIMARY KEY,
    song_id                 INTEGER,     -- Global resource ID (NOT same as song.rowid!)
    words                   RTF,         -- RTF-formatted lyrics with Unicode escapes
    slide_uids              TEXT,        -- Comma-separated "1-{UUID}" per slide
    slide_layout_revisions  INT64A,      -- Comma-separated revision numbers
    slide_revisions         INT64A       -- Comma-separated revision numbers
);
```

**Important**: `word.song_id` is a global resource ID shared across all EW7 content types
(songs, presentations, media, themes). It does NOT directly match `song.rowid` in SongHistory.db.
The mapping is: `song_id = song.rowid + offset`, where offset depends on the total count of
other resource types. For a fresh database, this offset equals the number of built-in
presentation layouts + other resources.

### SongKeys.db

Full-text search index for songs.

```sql
CREATE TABLE word_list (
    rowid  INTEGER PRIMARY KEY,
    word   TEXT                   -- Individual searchable word (lowercase)
);

CREATE TABLE word_key (
    rowid        INTEGER PRIMARY KEY,
    link_id      INTEGER,         -- Same global resource ID as word.song_id
    word_list_id INTEGER,         -- References word_list.rowid
    field_flag   INT8             -- 1 = word from title, 2 = word from lyrics
);
```

## ID System

EW7 uses a global resource ID counter across all content types:
- PresentationLayouts: rowids 1-52 (built-in themes/layouts)
- Media: rowids up to ~21
- Songs: start at ~224 (after all other resources)

UIDs follow the format `1-{UPPERCASE-UUID}`, e.g. `1-DB84EBC9-1450-473E-9ECA-81557D713D01`.

## RTF Format

Lyrics are stored as RTF with EW-specific extensions:
- `\sdeasyworship2` — EW RTF version marker
- `\sdslidemarker` — Marks slide boundaries
- `\sdewparatemplatestyle101` — Paragraph template style
- `\sdasfactor`, `\sdasbaseline` — Auto-sizing parameters
- `\sdfsreal`, `\sdfsdef`, `\sdfsauto` — Font size parameters
- `\uNNNN?` — Unicode characters (Sinhala text uses this extensively)

## Collation

All TEXT columns use `UTF8_U_CI` collation (case-insensitive Unicode).
This must be registered when connecting: `conn.create_collation("UTF8_U_CI", ...)`

## Other Database Files (Not used by this tool)

| File | Purpose |
|------|---------|
| Presentations.db | PowerPoint/media presentations |
| PresentationLayouts.db | Slide layouts and themes (52 built-in) |
| Media.db | Media library metadata |
| MediaKeys.db | Media search index |
| Themes.db | Visual themes |
| ThemeKeys.db | Theme search index |
| PresentationKeys.db | Presentation search index |
| Live.Settings.db | Live presentation state and settings |
| Foldback.Settings.db | Stage display settings |
| Alerts.db | Alert messages |
| Users.db | User accounts |
| Packages.db | Package management |
| ServiceIntervals.db | Service scheduling |
| media.thumb.2.db | Media thumbnail cache |
