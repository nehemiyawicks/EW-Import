#!/usr/bin/env python3
"""
EasyWorship 7 Song Import/Export Tool
Imports/exports songs between EW7 SQLite databases and plain text files.
Supports Sinhala (Unicode) text, RTF parsing, and search index rebuilding.
"""

import os
import re
import sys
import uuid
import shutil
import sqlite3
import datetime

# Defer tkinter import — only needed for GUI mode, not CLI
tk = None
filedialog = None
scrolledtext = None
messagebox = None
ttk = None


def _import_tkinter():
    """Import tkinter lazily so CLI mode works without it."""
    global tk, filedialog, scrolledtext, messagebox, ttk
    if tk is not None:
        return
    import tkinter as _tk
    from tkinter import filedialog as _fd, scrolledtext as _st, messagebox as _mb, ttk as _ttk
    tk = _tk
    filedialog = _fd
    scrolledtext = _st
    messagebox = _mb
    ttk = _ttk


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Common EW7 database locations (searched in order for auto-detection)
# EW7 typically stores databases under:
#   C:\Users\Public\Documents\Softouch\EasyWorship\{Profile}\v6.1\Databases\Data\
# The "v6.1" subfolder is used by EW7 for backward compatibility with EW6.
# Some installs may omit the v6.1 folder. We check both variants.
EW7_SEARCH_PATHS = [
    # Windows default (with v6.1 — most common for EW7)
    r"C:\Users\Public\Documents\Softouch\EasyWorship\Default\v6.1\Databases\Data",
    # Windows default (without v6.1 — older installs or EW 2009)
    r"C:\Users\Public\Documents\Softouch\EasyWorship\Default\Databases\Data",
    # ProgramData variants
    r"C:\ProgramData\Softouch\EasyWorship\Default\v6.1\Databases\Data",
    r"C:\ProgramData\Softouch\EasyWorship\Default\Databases\Data",
    # Relative to current working directory (for portable/testing setups)
    os.path.abspath("."),
]

DEFAULT_DB_PATH = ""  # Will be auto-detected on startup

SONGS_DB = "Songs.db"
SONG_WORDS_DB = "SongWords.db"
SONG_KEYS_DB = "SongKeys.db"
SONG_HISTORY_DB = "SongHistory.db"

SLIDE_MARKER = "[SLIDE]"
HYMN_SEPARATOR = "==="
META_FENCE = "---"

# RTF template matching EW7's native format (from built-in songs)
# Uses Verdana font, standard color table, \fntnamaut control word.
# Slide boundaries are blank \par lines (NO \sdslidemarker).
RTF_HEADER = (
    r"{\rtf1\ansi\deff0\deftab254"
    r"{\fonttbl{\f0\fnil\fcharset0 Arial;}{\f1\fnil\fcharset0 Verdana;}}"
    r"{\colortbl"
    r"\red0\green0\blue0;"
    r"\red255\green0\blue0;"
    r"\red0\green128\blue0;"
    r"\red0\green0\blue255;"
    r"\red255\green255\blue0;"
    r"\red255\green0\blue255;"
    r"\red128\green0\blue128;"
    r"\red128\green0\blue0;"
    r"\red0\green255\blue0;"
    r"\red0\green255\blue255;"
    r"\red0\green128\blue128;"
    r"\red0\green0\blue128;"
    r"\red255\green255\blue255;"
    r"\red192\green192\blue192;"
    r"\red128\green128\blue128;"
    r"\red255\green255\blue255;}"
    r"\paperw12240\paperh15840\margl1880\margr1880\margt1440\margb1440"
    r"{\*\pnseclvl1\pnucrm\pnstart1\pnhang\pnindent720{\pntxtb}{\pntxta{.}}}" "\r\n"
    r"{\*\pnseclvl2\pnucltr\pnstart1\pnhang\pnindent720{\pntxtb}{\pntxta{.}}}" "\r\n"
    r"{\*\pnseclvl3\pndec\pnstart1\pnhang\pnindent720{\pntxtb}{\pntxta{.}}}" "\r\n"
    r"{\*\pnseclvl4\pnlcltr\pnstart1\pnhang\pnindent720{\pntxtb}{\pntxta{)}}}" "\r\n"
    r"{\*\pnseclvl5\pndec\pnstart1\pnhang\pnindent720{\pntxtb{(}}{\pntxta{)}}}" "\r\n"
    r"{\*\pnseclvl6\pnlcltr\pnstart1\pnhang\pnindent720{\pntxtb{(}}{\pntxta{)}}}" "\r\n"
    r"{\*\pnseclvl7\pnlcrm\pnstart1\pnhang\pnindent720{\pntxtb{(}}{\pntxta{)}}}" "\r\n"
    r"{\*\pnseclvl8\pnlcltr\pnstart1\pnhang\pnindent720{\pntxtb{(}}{\pntxta{)}}}" "\r\n"
    r"{\*\pnseclvl9\pndec\pnstart1\pnhang\pnindent720{\pntxtb{(}}{\pntxta{)}}}" "\r\n"
)
RTF_FOOTER = "}"

# Line format for lyrics (matches EW7 built-in songs)
RTF_LINE_PREFIX = r"\li0\fi0\ri0\sb0\sl\sa0 \plain\f1\fntnamaut "
# Empty line to mark slide boundary
RTF_EMPTY_LINE = r"\li0\fi0\ri0\sb0\sl\sa0 \par" "\r\n"

# Field flags for SongKeys
FIELD_FLAG_TITLE = 1
FIELD_FLAG_WORDS = 2


# ---------------------------------------------------------------------------
# UTF8_U_CI Collation (required by EW7 databases)
# ---------------------------------------------------------------------------

def utf8_u_ci_collation(a, b):
    """Case-insensitive Unicode collation for EW7 databases."""
    a_lower = a.lower() if a else ""
    b_lower = b.lower() if b else ""
    if a_lower == b_lower:
        return 0
    return -1 if a_lower < b_lower else 1


# ---------------------------------------------------------------------------
# RTF Parser — converts EW7 RTF to plain text
# ---------------------------------------------------------------------------

def rtf_to_text(rtf_data):
    """
    Parse EW7 RTF and extract plain text with [SLIDE] markers.
    Handles \\uNNNN? Unicode escapes and \\sdslidemarker.
    """
    if not rtf_data:
        return ""

    text_parts = []
    current_line = []
    i = 0
    length = len(rtf_data)
    group_depth = 0
    # Track groups that should be skipped entirely:
    # fonttbl, colortbl, {\*\...} destination groups
    skip_depths = []
    found_slide_marker = False

    # Known destination groups whose content should be skipped
    SKIP_DESTINATIONS = {
        'fonttbl', 'colortbl', 'stylesheet', 'info', 'header', 'footer',
        'pict', 'object', 'datafield',
    }

    while i < length:
        ch = rtf_data[i]

        if ch == '{':
            group_depth += 1

            # Look ahead: is this a {\* destination} or {\fonttbl ...}?
            rest = rtf_data[i+1:i+40]

            # {\*\destination ...} — always skip
            if rest.startswith('\\*\\') or rest.startswith('\\*\r') or rest.startswith('\\*\n'):
                skip_depths.append(group_depth)
                i += 1
                continue

            # {\fonttbl, {\colortbl, etc — skip known destinations
            m = re.match(r'\\([a-z]+)', rest)
            if m and m.group(1) in SKIP_DESTINATIONS:
                skip_depths.append(group_depth)
                i += 1
                continue

            i += 1
            continue

        if ch == '}':
            if skip_depths and group_depth == skip_depths[-1]:
                skip_depths.pop()
            group_depth -= 1
            i += 1
            continue

        # If inside a skipped group, skip all content
        if skip_depths:
            i += 1
            continue

        if ch == '\\':
            i += 1
            if i >= length:
                break

            next_ch = rtf_data[i]

            # Escaped special characters
            if next_ch == '\\':
                current_line.append('\\')
                i += 1
                continue
            if next_ch == '{':
                current_line.append('{')
                i += 1
                continue
            if next_ch == '}':
                current_line.append('}')
                i += 1
                continue
            if next_ch == '~':
                current_line.append('\u00a0')  # non-breaking space
                i += 1
                continue
            if next_ch == '-':
                i += 1  # optional hyphen, skip
                continue
            if next_ch == '\n' or next_ch == '\r':
                i += 1
                continue

            # Read control word
            word_start = i
            while i < length and rtf_data[i].isalpha():
                i += 1
            control_word = rtf_data[word_start:i]

            # Read optional numeric parameter
            param_start = i
            if i < length and (rtf_data[i] == '-' or rtf_data[i].isdigit()):
                if rtf_data[i] == '-':
                    i += 1
                while i < length and rtf_data[i].isdigit():
                    i += 1
            param_str = rtf_data[param_start:i]
            param = int(param_str) if param_str else None

            # Skip trailing delimiter space
            if i < length and rtf_data[i] == ' ':
                i += 1

            # Handle specific control words
            if control_word == 'par':
                line = ''.join(current_line).rstrip()
                current_line = []
                if found_slide_marker:
                    text_parts.append(SLIDE_MARKER)
                    found_slide_marker = False
                else:
                    text_parts.append(line)
            elif control_word == 'sdslidemarker':
                found_slide_marker = True
            elif control_word == 'u' and param is not None:
                code_point = param if param >= 0 else param + 65536
                current_line.append(chr(code_point))
                # Skip the replacement character (usually '?')
                if i < length and rtf_data[i] not in ('\\', '{', '}'):
                    i += 1
            elif control_word == 'line':
                current_line.append('\n')
            elif control_word == 'tab':
                current_line.append('\t')
            # All other control words (formatting) are ignored
            continue

        # Skip raw newlines in RTF source
        if ch == '\n' or ch == '\r':
            i += 1
            continue

        # Regular text character
        current_line.append(ch)
        i += 1

    # Flush remaining text
    if current_line:
        line = ''.join(current_line).rstrip()
        if line:
            text_parts.append(line)

    # Post-process: convert blank lines between text to [SLIDE] markers.
    # EW7 native RTF uses empty \par lines as slide boundaries.
    cleaned = []
    for part in text_parts:
        if not part.strip():
            # Blank line — potential slide break
            if cleaned and cleaned[-1] != SLIDE_MARKER:
                cleaned.append(SLIDE_MARKER)
        else:
            cleaned.append(part)

    # Remove leading/trailing slide markers
    while cleaned and cleaned[0] == SLIDE_MARKER:
        cleaned.pop(0)
    while cleaned and cleaned[-1] == SLIDE_MARKER:
        cleaned.pop()

    result = '\n'.join(cleaned).strip('\n')
    return result


# ---------------------------------------------------------------------------
# RTF Generator — converts plain text to EW7-compatible RTF
# ---------------------------------------------------------------------------

def encode_unicode_rtf(text):
    """Encode text as RTF with Unicode escapes for non-ASCII characters."""
    result = []
    for ch in text:
        code = ord(ch)
        if code < 128:
            # Escape RTF special characters
            if ch in ('\\', '{', '}'):
                result.append('\\' + ch)
            else:
                result.append(ch)
        else:
            # Unicode escape: \uNNNN?
            if code > 32767:
                code -= 65536
            result.append(f'\\u{code}?')
    return ''.join(result)


def text_to_rtf(text):
    """
    Convert plain text (with [SLIDE] markers) to EW7-compatible RTF.
    Returns (rtf_string, slide_count).
    Matches the RTF format used by EW7's built-in songs:
    - Verdana font with \\fntnamaut control word
    - Slides separated by blank \\par lines (no \\sdslidemarker)
    - \\r\\n line endings for Windows
    """
    # Split text into slides on [SLIDE] markers
    slides = re.split(r'\n?\[SLIDE\]\n?', text)
    # Remove empty slides
    slides = [s.strip() for s in slides if s.strip()]

    rtf_parts = [RTF_HEADER]

    # First line uses {\pard ...} wrapper
    first_line = True

    for slide_idx, slide in enumerate(slides):
        if slide_idx > 0:
            # Blank line to separate slides
            rtf_parts.append(RTF_EMPTY_LINE)

        for line in slide.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            encoded = encode_unicode_rtf(stripped)

            if first_line:
                rtf_parts.append(
                    r"{\pard" + RTF_LINE_PREFIX + encoded + r"\par" + "\r\n"
                )
                first_line = False
            else:
                rtf_parts.append(
                    RTF_LINE_PREFIX + encoded + r"\par" + "\r\n"
                )

    rtf_parts.append(RTF_FOOTER + "\r\n}")
    return ''.join(rtf_parts), len(slides)


# ---------------------------------------------------------------------------
# TXT File Parser / Writer
# ---------------------------------------------------------------------------

def parse_txt_file(filepath):
    """
    Parse a .txt file containing one or more hymns.
    Returns list of dicts with keys: title, title_sinhala, author, copyright,
    ccli, book_ref, source, lyrics.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    hymns = []
    # Split by hymn separator
    sections = re.split(r'^===\s*$', content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        hymn = {
            'title': '',
            'title_sinhala': '',
            'author': '',
            'copyright': '',
            'ccli': '',
            'book_ref': '',
            'source': '',
            'lyrics': '',
        }

        # Check for metadata header
        if section.startswith(META_FENCE):
            # Find closing fence
            rest = section[len(META_FENCE):].lstrip('\n')
            close_idx = rest.find('\n' + META_FENCE)
            if close_idx >= 0:
                header = rest[:close_idx]
                body = rest[close_idx + len(META_FENCE) + 1:].strip('\n')
            else:
                # No closing fence, treat entire section as header
                header = rest
                body = ''

            # Parse header fields
            for line in header.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, _, value = line.partition(':')
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip()
                    if key in hymn:
                        hymn[key] = value

            hymn['lyrics'] = body.strip()
        else:
            hymn['lyrics'] = section.strip()

        if hymn['lyrics'] or hymn['title']:
            hymns.append(hymn)

    return hymns


def write_txt_file(filepath, hymns):
    """Write hymns to a .txt file in the standard format."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for i, hymn in enumerate(hymns):
            if i > 0:
                f.write('\n===\n\n')

            f.write(f'{META_FENCE}\n')
            f.write(f'title: {hymn.get("title", "")}\n')
            f.write(f'title_sinhala: {hymn.get("title_sinhala", "")}\n')
            f.write(f'author: {hymn.get("author", "")}\n')
            f.write(f'copyright: {hymn.get("copyright", "")}\n')
            f.write(f'ccli: {hymn.get("ccli", "")}\n')
            f.write(f'book_ref: {hymn.get("book_ref", "")}\n')
            f.write(f'source: {hymn.get("source", "")}\n')
            f.write(f'{META_FENCE}\n\n')

            f.write(hymn.get('lyrics', ''))
            f.write('\n')


# ---------------------------------------------------------------------------
# EW7 Database Class
# ---------------------------------------------------------------------------

class EWDatabase:
    """Manages connections to the EW7 song databases.

    EW7 uses these databases for songs:
    - Songs.db: song metadata (title, author, etc.)
    - SongWords.db: lyrics in RTF format
    - SongKeys.db: full-text search index

    Song linkage: SongWords.song_id == Songs.rowid (direct, no offset).
    SongHistory.db is only for usage tracking, NOT the song list.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn_songs = None
        self.conn_words = None
        self.conn_keys = None

    def _connect(self, db_name):
        """Create a connection with UTF8_U_CI collation registered."""
        db_file = os.path.join(self.db_path, db_name)
        if not os.path.exists(db_file):
            raise FileNotFoundError(f"Database not found: {db_file}")
        conn = sqlite3.connect(db_file)
        conn.create_collation("UTF8_U_CI", utf8_u_ci_collation)
        return conn

    def connect(self):
        """Open connections to all song databases."""
        self.conn_songs = self._connect(SONGS_DB)
        self.conn_words = self._connect(SONG_WORDS_DB)
        self.conn_keys = self._connect(SONG_KEYS_DB)

    def close(self):
        """Close all database connections."""
        for conn in (self.conn_songs, self.conn_words, self.conn_keys):
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        self.conn_songs = None
        self.conn_words = None
        self.conn_keys = None

    def get_all_songs(self):
        """
        Get all songs with their metadata and lyrics.
        Returns list of dicts.
        """
        cur_s = self.conn_songs.cursor()
        cur_w = self.conn_words.cursor()

        cur_s.execute(
            "SELECT rowid, song_uid, title, author, copyright, "
            "administrator, reference_number FROM song ORDER BY rowid"
        )
        songs = []

        for row in cur_s.fetchall():
            rowid, song_uid, title, author, copyright_, admin, ref_num = row

            song = {
                'rowid': rowid,
                'song_uid': song_uid,
                'title': title or '',
                'author': author or '',
                'copyright': copyright_ or '',
                'administrator': admin or '',
                'reference_number': ref_num or '',
                'lyrics_rtf': '',
                'slide_uids': '',
                'word_song_id': None,
            }

            # SongWords.song_id == Songs.rowid (direct match, no offset)
            cur_w.execute(
                "SELECT words, slide_uids FROM word WHERE song_id = ?",
                (rowid,)
            )
            result = cur_w.fetchone()
            if result:
                song['lyrics_rtf'] = result[0]
                song['slide_uids'] = result[1] or ''
                song['word_song_id'] = rowid

            songs.append(song)

        return songs

    def song_exists(self, title):
        """Check if a song with the given title already exists."""
        cur = self.conn_songs.cursor()
        cur.execute(
            "SELECT rowid, song_uid FROM song WHERE title = ? COLLATE UTF8_U_CI",
            (title,)
        )
        return cur.fetchone()

    def import_song(self, hymn):
        """
        Import a single hymn into the database.
        Returns (song_id, song_uid).

        Inserts into Songs.db (metadata) and SongWords.db (lyrics).
        song_id in SongWords == rowid in Songs (no offset).
        """
        title = hymn.get('title', '') or 'Untitled'
        author = hymn.get('author', '')
        copyright_ = hymn.get('copyright', '')
        ref_num = hymn.get('book_ref', '')
        lyrics = hymn.get('lyrics', '')

        # Generate UIDs matching EW7 format
        item_uid = f"1-{str(uuid.uuid4()).upper()}"
        rev_uid = f"1-{str(uuid.uuid4()).upper()}"

        # Convert lyrics to RTF
        rtf_text, slide_count = text_to_rtf(lyrics)

        # Generate slide UIDs
        slide_uids = ','.join(
            f"1-{str(uuid.uuid4()).upper()}" for _ in range(slide_count)
        )

        # Insert into Songs.db
        cur_s = self.conn_songs.cursor()
        cur_s.execute(
            "INSERT INTO song (song_item_uid, song_rev_uid, song_uid, "
            "title, author, copyright, administrator, description, tags, "
            "reference_number, provider_id, vendor_id, presentation_id, "
            "layout_revision, revision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_uid, rev_uid, item_uid,
             title, author, copyright_, '', '', '',
             ref_num, -1, 0, 0, 1, 1)
        )
        song_rowid = cur_s.lastrowid

        # Update revision table
        cur_s.execute(
            "UPDATE revision SET revision_num = revision_num + 1 "
            "WHERE tablename = 'song'"
        )
        self.conn_songs.commit()

        # Insert into SongWords.db (song_id == Songs.rowid, no offset)
        cur_w = self.conn_words.cursor()
        slide_layout_revs = ','.join(['1'] * slide_count)
        slide_revs = ','.join(['1'] * slide_count)
        cur_w.execute(
            "INSERT INTO word (song_id, words, slide_uids, "
            "slide_layout_revisions, slide_revisions) VALUES (?, ?, ?, ?, ?)",
            (song_rowid, rtf_text, slide_uids, slide_layout_revs, slide_revs)
        )
        self.conn_words.commit()

        return song_rowid, item_uid

    def rebuild_search_index(self, song_id, title, lyrics_text):
        """
        Rebuild the search index in SongKeys.db for a given song.
        link_id in SongKeys == rowid in Songs (no offset).
        """
        cur = self.conn_keys.cursor()

        # Remove existing entries for this song
        cur.execute("DELETE FROM word_key WHERE link_id = ?", (song_id,))

        # Extract words from title and lyrics
        def extract_words(text):
            """Extract searchable words from text."""
            text = text.replace(SLIDE_MARKER, ' ')
            words = re.findall(r'[\w\u0D80-\u0DFF]+', text.lower(), re.UNICODE)
            return set(words)

        title_words = extract_words(title)
        lyrics_words = extract_words(lyrics_text)

        for word in title_words | lyrics_words:
            if not word:
                continue

            cur.execute("SELECT rowid FROM word_list WHERE word = ?", (word,))
            row = cur.fetchone()
            if row:
                word_list_id = row[0]
            else:
                cur.execute("INSERT INTO word_list (word) VALUES (?)", (word,))
                word_list_id = cur.lastrowid

            flag = 0
            if word in title_words:
                flag |= FIELD_FLAG_TITLE
            if word in lyrics_words:
                flag |= FIELD_FLAG_WORDS

            cur.execute(
                "INSERT OR REPLACE INTO word_key (link_id, word_list_id, field_flag) "
                "VALUES (?, ?, ?)",
                (song_id, word_list_id, flag)
            )

        self.conn_keys.commit()

    def delete_search_index(self, song_id):
        """Remove all search index entries for a song."""
        cur = self.conn_keys.cursor()
        cur.execute("DELETE FROM word_key WHERE link_id = ?", (song_id,))
        self.conn_keys.commit()


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_databases(db_path, backup_dir=None):
    """
    Create timestamped backups of all three song databases.
    Returns the backup directory path.
    """
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(db_path) if db_path else '.', 'backups')

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_subdir = os.path.join(backup_dir, f'backup_{timestamp}')
    os.makedirs(backup_subdir, exist_ok=True)

    db_files = [SONGS_DB, SONG_WORDS_DB, SONG_KEYS_DB, SONG_HISTORY_DB]
    for db_file in db_files:
        src = os.path.join(db_path, db_file)
        if os.path.exists(src):
            dst = os.path.join(backup_subdir, db_file)
            shutil.copy2(src, dst)

            # Verify backup integrity
            try:
                conn = sqlite3.connect(dst)
                conn.create_collation("UTF8_U_CI", utf8_u_ci_collation)
                conn.execute("PRAGMA integrity_check")
                conn.close()
            except sqlite3.Error as e:
                raise RuntimeError(f"Backup integrity check failed for {db_file}: {e}")

    return backup_subdir


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_songs(db, output_dir, one_per_file=True, log_callback=None):
    """
    Export all songs from EW7 database to .txt files.
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)
    songs = db.get_all_songs()
    exported = 0
    skipped = 0

    if one_per_file:
        for song in songs:
            rtf = song.get('lyrics_rtf', '')
            if not rtf:
                skipped += 1
                continue

            lyrics = rtf_to_text(rtf)
            title = song['title'] or 'Untitled'

            # Sanitize filename
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
            safe_title = safe_title[:100]  # Limit length

            hymn_data = {
                'title': title,
                'title_sinhala': '',
                'author': song.get('author', ''),
                'copyright': song.get('copyright', ''),
                'ccli': '',
                'book_ref': song.get('reference_number', ''),
                'source': 'ew7_export',
                'lyrics': lyrics,
            }

            filepath = os.path.join(output_dir, f"{safe_title}.txt")
            # Handle duplicate filenames
            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(output_dir, f"{safe_title}_{counter}.txt")
                counter += 1

            write_txt_file(filepath, [hymn_data])
            exported += 1
            if exported % 10 == 0:
                log(f"Exported {exported} songs...")
    else:
        # All in one file
        hymns = []
        for song in songs:
            rtf = song.get('lyrics_rtf', '')
            if not rtf:
                skipped += 1
                continue

            lyrics = rtf_to_text(rtf)
            hymns.append({
                'title': song['title'] or 'Untitled',
                'title_sinhala': '',
                'author': song.get('author', ''),
                'copyright': song.get('copyright', ''),
                'ccli': '',
                'book_ref': song.get('reference_number', ''),
                'source': 'ew7_export',
                'lyrics': lyrics,
            })
            exported += 1

        filepath = os.path.join(output_dir, "all_songs.txt")
        write_txt_file(filepath, hymns)

    log(f"Export complete: {exported} songs exported, {skipped} skipped (no lyrics)")
    return exported, skipped


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_songs(db, input_path, skip_duplicates=True, log_callback=None):
    """
    Import songs from .txt file(s) into EW7 database.
    input_path can be a file or directory.
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    # Collect all txt files
    txt_files = []
    if os.path.isdir(input_path):
        for fname in sorted(os.listdir(input_path)):
            if fname.lower().endswith('.txt'):
                txt_files.append(os.path.join(input_path, fname))
    elif os.path.isfile(input_path):
        txt_files.append(input_path)
    else:
        raise FileNotFoundError(f"Path not found: {input_path}")

    if not txt_files:
        log("No .txt files found.")
        return 0, 0, 0

    imported = 0
    skipped = 0
    errors = 0

    for txt_file in txt_files:
        try:
            hymns = parse_txt_file(txt_file)
        except Exception as e:
            log(f"Error parsing {os.path.basename(txt_file)}: {e}")
            errors += 1
            continue

        for hymn in hymns:
            title = hymn.get('title', '').strip()
            if not title:
                # Try to use first line of lyrics as title
                lyrics = hymn.get('lyrics', '')
                first_line = lyrics.split('\n')[0].strip() if lyrics else ''
                if first_line and first_line != SLIDE_MARKER:
                    title = first_line[:100]
                else:
                    title = 'Untitled'
                hymn['title'] = title

            # Check for duplicates
            if skip_duplicates:
                existing = db.song_exists(title)
                if existing:
                    log(f"Skipped (duplicate): {title}")
                    skipped += 1
                    continue

            try:
                song_id, song_uid = db.import_song(hymn)

                # Rebuild search index
                lyrics_text = hymn.get('lyrics', '')
                db.rebuild_search_index(song_id, title, lyrics_text)

                log(f"Imported: {title} (id={song_id})")
                imported += 1
            except Exception as e:
                log(f"Error importing '{title}': {e}")
                errors += 1

    log(f"\nImport complete: {imported} imported, {skipped} skipped, {errors} errors")
    return imported, skipped, errors


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

def auto_detect_ew_path():
    """
    Auto-detect the EW7 database path by searching common locations.
    Also checks for EW profiles (EW can have multiple named profiles).
    Returns the first valid path found, or empty string.
    """
    # Standard EW7 paths on Windows
    candidates = list(EW7_SEARCH_PATHS)

    # Also check for EW profiles: each profile is a subfolder under
    # C:\Users\Public\Documents\Softouch\EasyWorship\
    # with structure: {ProfileName}\v6.1\Databases\Data\
    # or older:       {ProfileName}\Databases\Data\
    ew_base_dirs = [
        r"C:\Users\Public\Documents\Softouch\EasyWorship",
        r"C:\ProgramData\Softouch\EasyWorship",
    ]
    for base in ew_base_dirs:
        if os.path.isdir(base):
            try:
                for entry in os.listdir(base):
                    # Check with v6.1 subfolder first (EW7 standard)
                    profile_db_v61 = os.path.join(base, entry, "v6.1", "Databases", "Data")
                    if profile_db_v61 not in candidates:
                        candidates.append(profile_db_v61)
                    # Also check without v6.1 (older or custom installs)
                    profile_db = os.path.join(base, entry, "Databases", "Data")
                    if profile_db not in candidates:
                        candidates.append(profile_db)
            except OSError:
                pass

    # Check each candidate
    for path in candidates:
        if os.path.isdir(path):
            # Verify it contains the required DB files
            has_songs = os.path.exists(os.path.join(path, SONGS_DB))
            has_words = os.path.exists(os.path.join(path, SONG_WORDS_DB))
            if has_songs and has_words:
                return path

    return ""


class EWToolApp:
    """tkinter GUI for EW7 Song Import/Export."""

    def __init__(self, root):
        self.root = root
        self.root.title("EasyWorship 7 Song Import/Export Tool")
        self.root.geometry("780x650")
        self.root.minsize(600, 400)

        self.db_path = tk.StringVar(value="")
        self.db = None

        self._build_ui()
        self._auto_detect_path()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # --- Database path section ---
        path_frame = ttk.LabelFrame(
            main,
            text="EW7 Database Location (folder containing Songs.db)",
            padding=8
        )
        path_frame.pack(fill=tk.X, pady=(0, 10))

        # Path entry + browse + detect
        row1 = ttk.Frame(path_frame)
        row1.pack(fill=tk.X)

        path_entry = ttk.Entry(row1, textvariable=self.db_path, font=("Segoe UI", 9))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        ttk.Button(row1, text="Browse...", command=self._browse_db).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(row1, text="Auto-Detect", command=self._auto_detect_path).pack(
            side=tk.LEFT
        )

        # Database info label
        self.db_info = tk.StringVar(value="")
        ttk.Label(path_frame, textvariable=self.db_info, foreground="gray").pack(
            anchor=tk.W, pady=(4, 0)
        )

        # Update info when path changes
        self.db_path.trace_add("write", lambda *_: self._update_db_info())

        # --- Action buttons ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(btn_frame, text="Export Songs", command=self._export).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(btn_frame, text="Import Songs", command=self._import).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(btn_frame, text="Backup Databases", command=self._backup).pack(
            side=tk.LEFT, padx=(0, 5)
        )

        # --- Options ---
        opt_frame = ttk.Frame(main)
        opt_frame.pack(fill=tk.X, pady=(0, 10))

        self.export_one_per_file = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame, text="One file per song (export)",
            variable=self.export_one_per_file
        ).pack(side=tk.LEFT, padx=(0, 15))

        self.skip_dupes = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame, text="Skip duplicates (import)",
            variable=self.skip_dupes
        ).pack(side=tk.LEFT)

        # --- Log area ---
        log_frame = ttk.LabelFrame(main, text="Log", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Consolas", 9), state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # --- Status bar ---
        self.status = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status, relief=tk.SUNKEN).pack(
            fill=tk.X, pady=(5, 0)
        )

    def _auto_detect_path(self):
        """Try to auto-detect the EW7 database path."""
        path = auto_detect_ew_path()
        if path:
            self.db_path.set(path)
            self.log(f"Auto-detected EW7 database: {path}")
        else:
            self.log("Could not auto-detect EW7 database path. Please browse manually.")

    def _update_db_info(self):
        """Update the database info label when path changes."""
        path = self.db_path.get().strip()
        if not path:
            self.db_info.set("")
            return

        songs_path = os.path.join(path, SONGS_DB)
        words_path = os.path.join(path, SONG_WORDS_DB)

        if not os.path.exists(songs_path):
            self.db_info.set("Songs.db not found in this folder")
            return

        try:
            conn = sqlite3.connect(songs_path)
            conn.create_collation("UTF8_U_CI", utf8_u_ci_collation)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM song")
            song_count = cur.fetchone()[0]
            conn.close()

            words_count = 0
            if os.path.exists(words_path):
                conn = sqlite3.connect(words_path)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM word")
                words_count = cur.fetchone()[0]
                conn.close()

            self.db_info.set(
                f"Found: {song_count} songs, {words_count} with lyrics"
            )
        except Exception as e:
            self.db_info.set(f"Error reading database: {e}")

    def log(self, message):
        """Append a message to the log area."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def _browse_db(self):
        # Start in a sensible directory
        initial_dir = self.db_path.get().strip()
        if not initial_dir or not os.path.isdir(initial_dir):
            initial_dir = r"C:\Users\Public\Documents\Softouch\EasyWorship"
            if not os.path.isdir(initial_dir):
                initial_dir = None

        path = filedialog.askdirectory(
            title="Select folder containing EW7 database files (Songs.db, etc.)",
            initialdir=initial_dir
        )
        if path:
            self.db_path.set(path)

    def _connect_db(self):
        """Connect to the EW7 databases. Returns True on success."""
        path = self.db_path.get().strip()
        if not path:
            messagebox.showerror("Error", "Please select the EW7 database folder.")
            return False

        for db_name in [SONGS_DB, SONG_WORDS_DB, SONG_KEYS_DB]:
            if not os.path.exists(os.path.join(path, db_name)):
                messagebox.showerror(
                    "Error",
                    f"Required database file not found: {db_name}\n"
                    f"in folder: {path}\n\n"
                    f"The folder should contain Songs.db, SongWords.db, "
                    f"and SongKeys.db.\n"
                    f"Typical path: C:\\Users\\Public\\Documents\\Softouch\\"
                    f"EasyWorship\\Default\\v6.1\\Databases\\Data\\"
                )
                return False

        if self.db:
            self.db.close()

        self.db = EWDatabase(path)
        try:
            self.db.connect()
            return True
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.db = None
            return False

    def _export(self):
        if not self._connect_db():
            return

        output_dir = filedialog.askdirectory(title="Select Export Output Folder")
        if not output_dir:
            return

        self.status.set("Exporting...")
        self.log("Starting export...")

        try:
            exported, skipped = export_songs(
                self.db, output_dir,
                one_per_file=self.export_one_per_file.get(),
                log_callback=self.log
            )
            self.status.set(f"Export complete: {exported} songs")
        except Exception as e:
            self.log(f"Export error: {e}")
            self.status.set("Export failed")
            messagebox.showerror("Export Error", str(e))
        finally:
            if self.db:
                self.db.close()
                self.db = None

    def _import(self):
        if not self._connect_db():
            return

        # Ask: import file or folder?
        choice = messagebox.askyesnocancel(
            "Import Source",
            "Import from a folder of .txt files?\n\n"
            "Yes = Select folder\n"
            "No = Select individual file(s)\n"
            "Cancel = Cancel"
        )

        if choice is None:
            return

        if choice:
            input_path = filedialog.askdirectory(title="Select Folder with .txt Files")
        else:
            files = filedialog.askopenfilenames(
                title="Select .txt File(s)",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            if not files:
                return
            input_path = files[0] if len(files) == 1 else None
            if input_path is None:
                # Multiple files: import each one
                self.status.set("Importing...")
                self.log("Starting import...")
                try:
                    # Backup first
                    backup_dir = backup_databases(self.db_path.get())
                    self.log(f"Backup created: {backup_dir}")

                    total_imported = 0
                    total_skipped = 0
                    total_errors = 0
                    for f in files:
                        i, s, e = import_songs(
                            self.db, f,
                            skip_duplicates=self.skip_dupes.get(),
                            log_callback=self.log
                        )
                        total_imported += i
                        total_skipped += s
                        total_errors += e
                    self.status.set(
                        f"Import complete: {total_imported} imported, "
                        f"{total_skipped} skipped, {total_errors} errors"
                    )
                except Exception as e:
                    self.log(f"Import error: {e}")
                    self.status.set("Import failed")
                    messagebox.showerror("Import Error", str(e))
                finally:
                    if self.db:
                        self.db.close()
                        self.db = None
                return

        if not input_path:
            return

        self.status.set("Importing...")
        self.log("Starting import...")

        try:
            # Backup first
            backup_dir = backup_databases(self.db_path.get())
            self.log(f"Backup created: {backup_dir}")

            imported, skipped, errors = import_songs(
                self.db, input_path,
                skip_duplicates=self.skip_dupes.get(),
                log_callback=self.log
            )
            self.status.set(
                f"Import complete: {imported} imported, "
                f"{skipped} skipped, {errors} errors"
            )
        except Exception as e:
            self.log(f"Import error: {e}")
            self.status.set("Import failed")
            messagebox.showerror("Import Error", str(e))
        finally:
            if self.db:
                self.db.close()
                self.db = None

    def _backup(self):
        path = self.db_path.get().strip()
        if not path:
            messagebox.showerror("Error", "Please select the EW7 database folder.")
            return

        backup_dir = filedialog.askdirectory(title="Select Backup Destination Folder")
        if not backup_dir:
            return

        try:
            result = backup_databases(path, backup_dir)
            self.log(f"Backup created: {result}")
            self.status.set("Backup complete")
            messagebox.showinfo("Backup Complete", f"Databases backed up to:\n{result}")
        except Exception as e:
            self.log(f"Backup error: {e}")
            messagebox.showerror("Backup Error", str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="EasyWorship 7 Song Import/Export Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CLI examples:
  # Import songs from a folder into EW7 databases
  python ew_tool.py import --db /path/to/EW/Data --input /path/to/songs/

  # Export songs from EW7 databases to text files
  python ew_tool.py export --db /path/to/EW/Data --output /path/to/output/

  # Backup databases before making changes
  python ew_tool.py backup --db /path/to/EW/Data --output /path/to/backups/

  # Verify database integrity (find orphaned entries)
  python ew_tool.py verify --db /path/to/EW/Data

  # Launch the GUI (default, no arguments)
  python ew_tool.py
        """
    )
    subparsers = parser.add_subparsers(dest='command')

    # Import subcommand
    imp = subparsers.add_parser('import', help='Import songs from .txt files')
    imp.add_argument('--db', required=True,
                     help='Path to EW7 database folder (containing Songs.db)')
    imp.add_argument('--input', '-i', required=True,
                     help='Path to .txt file or folder of .txt files')
    imp.add_argument('--allow-duplicates', action='store_true',
                     help='Import even if a song with the same title exists')

    # Export subcommand
    exp = subparsers.add_parser('export', help='Export songs to .txt files')
    exp.add_argument('--db', required=True,
                     help='Path to EW7 database folder')
    exp.add_argument('--output', '-o', required=True,
                     help='Output directory for .txt files')

    # Backup subcommand
    bak = subparsers.add_parser('backup', help='Backup EW7 databases')
    bak.add_argument('--db', required=True,
                     help='Path to EW7 database folder')
    bak.add_argument('--output', '-o', required=True,
                     help='Backup destination directory')

    # Verify subcommand
    ver = subparsers.add_parser('verify', help='Verify database integrity')
    ver.add_argument('--db', required=True,
                     help='Path to EW7 database folder')
    ver.add_argument('--fix', action='store_true',
                     help='Remove orphaned entries (songs without lyrics)')

    args = parser.parse_args()

    if args.command is None:
        # No subcommand — launch GUI
        _import_tkinter()
        root = tk.Tk()
        app = EWToolApp(root)
        root.mainloop()
        return

    if args.command == 'import':
        print(f"Database folder: {args.db}")
        print(f"Input path: {args.input}")

        # Verify database files exist
        for db_name in [SONGS_DB, SONG_WORDS_DB, SONG_KEYS_DB]:
            db_file = os.path.join(args.db, db_name)
            if os.path.exists(db_file):
                size = os.path.getsize(db_file)
                print(f"  Found: {db_name} ({size:,} bytes)")
            else:
                print(f"  MISSING: {db_name}")
                sys.exit(1)

        db = EWDatabase(args.db)
        try:
            db.connect()

            # Show database state before import
            song_count = db.conn_songs.execute(
                "SELECT COUNT(*) FROM song"
            ).fetchone()[0]
            word_count = db.conn_words.execute(
                "SELECT COUNT(*) FROM word"
            ).fetchone()[0]
            print(f"\nBefore import:")
            print(f"  Songs in Songs.db: {song_count}")
            print(f"  Lyrics in SongWords.db: {word_count}")

            imported, skipped, errors = import_songs(
                db, args.input,
                skip_duplicates=not args.allow_duplicates,
                log_callback=print
            )

            # Show database state after import
            song_count_after = db.conn_songs.execute(
                "SELECT COUNT(*) FROM song"
            ).fetchone()[0]
            word_count_after = db.conn_words.execute(
                "SELECT COUNT(*) FROM word"
            ).fetchone()[0]
            print(f"\nAfter import:")
            print(f"  Songs in Songs.db: {song_count_after} (+{song_count_after - song_count})")
            print(f"  Lyrics in SongWords.db: {word_count_after} (+{word_count_after - word_count})")
            print(f"\nDone: {imported} imported, {skipped} skipped, {errors} errors")

            if imported > 0:
                print(f"\nIMPORTANT: Close and reopen EasyWorship to see the new songs.")
        finally:
            db.close()

    elif args.command == 'export':
        db = EWDatabase(args.db)
        try:
            db.connect()
            exported, skipped = export_songs(
                db, args.output, log_callback=print
            )
            print(f"\nDone: exported {exported} songs to {args.output}")
        finally:
            db.close()

    elif args.command == 'backup':
        result = backup_databases(args.db, args.output)
        print(f"Backup created: {result}")

    elif args.command == 'verify':
        db = EWDatabase(args.db)
        try:
            db.connect()

            # Find orphaned songs (in Songs.db but no SongWords entry)
            cur_s = db.conn_songs.cursor()
            cur_w = db.conn_words.cursor()

            all_songs = cur_s.execute(
                "SELECT rowid, title FROM song ORDER BY rowid"
            ).fetchall()
            word_ids = set(
                r[0] for r in cur_w.execute("SELECT song_id FROM word").fetchall()
            )

            orphans = []
            for rowid, title in all_songs:
                if rowid not in word_ids:
                    orphans.append((rowid, title))

            print(f"\nTotal songs in Songs.db: {len(all_songs)}")
            print(f"Total entries in SongWords.db: {len(word_ids)}")
            print(f"Orphaned songs (no lyrics): {len(orphans)}")

            if orphans:
                print("\nOrphaned entries:")
                for rowid, title in orphans:
                    print(f"  rowid={rowid}, title=\"{title}\"")

                if args.fix:
                    print("\nRemoving orphaned entries...")
                    for rowid, title in orphans:
                        cur_s.execute("DELETE FROM song WHERE rowid = ?", (rowid,))
                        db.delete_search_index(rowid)
                        print(f"  Removed: {title} (rowid={rowid})")
                    db.conn_songs.commit()
                    remaining = cur_s.execute("SELECT COUNT(*) FROM song").fetchone()[0]
                    print(f"\nDone. {len(orphans)} orphaned entries removed. "
                          f"{remaining} songs remaining.")
                else:
                    print("\nRun with --fix to remove orphaned entries.")
            else:
                print("\nAll songs have matching lyrics entries. Database is clean.")
        finally:
            db.close()


if __name__ == '__main__':
    main()
