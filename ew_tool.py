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
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk


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

SONG_HISTORY_DB = "SongHistory.db"
SONG_WORDS_DB = "SongWords.db"
SONG_KEYS_DB = "SongKeys.db"

SLIDE_MARKER = "[SLIDE]"
HYMN_SEPARATOR = "==="
META_FENCE = "---"

# RTF template matching EW7's format
RTF_HEADER = (
    r"{\rtf1\ansi\deff0\sdeasyworship2" "\n"
    r"{\fonttbl{\f0 Tahoma;}}" "\n"
    r"{\colortbl ;}" "\n"
)
RTF_FOOTER = "}"

# RTF paragraph template for a slide's first line (with sdasfactor 1)
RTF_FIRST_PARA = (
    r"{\pard\sdlistlevel0\qc\qdef\sdewparatemplatestyle101"
    r"{\*\sdasfactor 1}{\*\sdasbaseline 90}\sdastextstyle101"
    r"\plain\sdewtemplatestyle101\fs180"
    r"{\*\sdfsreal 90}{\*\sdfsdef 90}\sdfsauto"
)
# RTF paragraph for subsequent lines
RTF_PARA = (
    r"{\pard\qc\qdef\sdewparatemplatestyle101"
    r"\plain\sdewtemplatestyle101\fs180"
    r"{\*\sdfsreal 90}{\*\sdfsdef 90}\sdfsauto"
)
# RTF slide marker paragraph
RTF_SLIDE_MARKER = (
    r"{\pard\sdslidemarker\qc\qdef\sdewparatemplatestyle101"
    r"\plain\sdewtemplatestyle101\fs180"
    r"{\*\sdfsreal 90}{\*\sdfsdef 90}\sdfsauto\par}"
)

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

    result = '\n'.join(text_parts).strip('\n')
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
    """
    lines = text.split('\n')
    rtf_parts = [RTF_HEADER]
    slide_count = 0
    is_first_line = True
    first_line_of_slide = True

    for line in lines:
        stripped = line.strip()

        if stripped == SLIDE_MARKER:
            # Insert slide marker
            rtf_parts.append(RTF_SLIDE_MARKER + "\n")
            slide_count += 1
            first_line_of_slide = True
            continue

        # Encode the line content
        encoded = encode_unicode_rtf(stripped)

        if is_first_line or first_line_of_slide:
            # First line uses the sdasfactor template
            para_start = RTF_FIRST_PARA if is_first_line else (
                r"{\pard\qc\qdef\sdewparatemplatestyle101"
                r"{\*\sdasfactor 1}{\*\sdasbaseline 90}\sdastextstyle101"
                r"\plain\sdewtemplatestyle101\fs180"
                r"{\*\sdfsreal 90}{\*\sdfsdef 90}\sdfsauto"
            )
            rtf_parts.append(f"{para_start}{encoded}\\par}}\n")
            is_first_line = False
            first_line_of_slide = False
        else:
            rtf_parts.append(f"{RTF_PARA}{encoded}\\par}}\n")

    rtf_parts.append(RTF_FOOTER)
    return ''.join(rtf_parts), slide_count + 1  # +1 for last slide


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
    """Manages connections to the three EW7 song databases."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn_history = None
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
        """Open connections to all three databases."""
        self.conn_history = self._connect(SONG_HISTORY_DB)
        self.conn_words = self._connect(SONG_WORDS_DB)
        self.conn_keys = self._connect(SONG_KEYS_DB)

    def close(self):
        """Close all database connections."""
        for conn in (self.conn_history, self.conn_words, self.conn_keys):
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        self.conn_history = None
        self.conn_words = None
        self.conn_keys = None

    def get_all_songs(self):
        """
        Get all songs with their metadata and lyrics.
        Returns list of dicts.
        """
        cur_h = self.conn_history.cursor()
        cur_w = self.conn_words.cursor()

        # Get all songs from history
        cur_h.execute(
            "SELECT rowid, song_uid, title, author, copyright, "
            "administrator, reference_number FROM song ORDER BY rowid"
        )
        songs = []

        for row in cur_h.fetchall():
            rowid, song_uid, title, author, copyright_, admin, ref_num = row

            song = {
                'rowid': rowid,
                'song_uid': song_uid,
                'title': title or '',
                'author': author or '',
                'copyright': copyright_ or '',
                'administrator': admin or '',
                'reference_number': ref_num or '',
                'lyrics': '',
                'slide_uids': '',
            }

            # Try to find matching words entry
            # Strategy: try multiple approaches to find the lyrics
            words_found = False

            # Approach 1: Calculate offset from first entries
            cur_w.execute("SELECT MIN(song_id) FROM word")
            min_word_id = cur_w.fetchone()[0]
            if min_word_id is not None:
                offset = min_word_id - 1  # Assumes first song rowid is 1
                expected_song_id = rowid + offset
                cur_w.execute(
                    "SELECT words, slide_uids FROM word WHERE song_id = ?",
                    (expected_song_id,)
                )
                result = cur_w.fetchone()
                if result:
                    song['lyrics_rtf'] = result[0]
                    song['slide_uids'] = result[1] or ''
                    song['word_song_id'] = expected_song_id
                    words_found = True

            if not words_found:
                song['lyrics_rtf'] = ''
                song['word_song_id'] = None

            songs.append(song)

        return songs

    def get_resource_offset(self):
        """
        Detect the resource offset between SongHistory.rowid and SongWords.song_id.
        EasyWorship uses a global resource ID system where:
            SongWords.song_id = SongHistory.rowid + resource_offset
        The offset is typically 223 (resources 1-223 are used by themes, layouts, etc.).
        """
        cur_h = self.conn_history.cursor()
        cur_w = self.conn_words.cursor()

        # Find matching pairs to detect the offset
        cur_h.execute("SELECT rowid FROM song ORDER BY rowid LIMIT 1")
        first_history = cur_h.fetchone()
        cur_w.execute("SELECT song_id FROM word ORDER BY song_id LIMIT 1")
        first_words = cur_w.fetchone()

        if first_history and first_words:
            return first_words[0] - first_history[0]

        # Default EW7 offset if no existing data
        return 223

    def get_next_song_id(self):
        """Get the next available song_id for SongWords."""
        cur = self.conn_words.cursor()
        cur.execute("SELECT MAX(song_id) FROM word")
        max_id = cur.fetchone()[0]
        return (max_id or 0) + 1

    def get_next_history_rowid(self):
        """Get the next available rowid for SongHistory."""
        cur = self.conn_history.cursor()
        cur.execute("SELECT MAX(rowid) FROM song")
        max_id = cur.fetchone()[0]
        return (max_id or 0) + 1

    def song_exists(self, title):
        """Check if a song with the given title already exists."""
        cur = self.conn_history.cursor()
        cur.execute(
            "SELECT rowid, song_uid FROM song WHERE title = ? COLLATE UTF8_U_CI",
            (title,)
        )
        return cur.fetchone()

    def import_song(self, hymn, resource_offset=None):
        """
        Import a single hymn into the database.
        Returns (song_id, song_uid) where song_id is the global resource ID
        used in SongWords and SongKeys.

        EasyWorship links SongHistory and SongWords via:
            SongWords.song_id = SongHistory.rowid + resource_offset
        """
        if resource_offset is None:
            resource_offset = self.get_resource_offset()

        title = hymn.get('title', '') or 'Untitled'
        author = hymn.get('author', '')
        copyright_ = hymn.get('copyright', '')
        ref_num = hymn.get('book_ref', '')
        lyrics = hymn.get('lyrics', '')

        # Generate UIDs
        song_uid = f"1-{str(uuid.uuid4()).upper()}"

        # Convert lyrics to RTF
        rtf_text, slide_count = text_to_rtf(lyrics)

        # Generate slide UIDs
        slide_uids = ','.join(
            f"1-{str(uuid.uuid4()).upper()}" for _ in range(slide_count)
        )

        # Insert into SongHistory first to get the rowid
        cur_h = self.conn_history.cursor()
        cur_h.execute(
            "INSERT INTO song (song_uid, title, author, copyright, "
            "administrator, reference_number) VALUES (?, ?, ?, ?, ?, ?)",
            (song_uid, title, author, copyright_, '', ref_num)
        )
        song_rowid = cur_h.lastrowid

        # Derive global resource ID from rowid + offset
        song_id = song_rowid + resource_offset

        # Record creation action
        now_ticks = int(
            (datetime.datetime.now() - datetime.datetime(1, 1, 1)).total_seconds()
            * 10_000_000
        )
        cur_h.execute(
            "INSERT INTO action (song_id, date, action_type) VALUES (?, ?, ?)",
            (song_rowid, now_ticks, 0)
        )
        self.conn_history.commit()

        # Insert into SongWords with the correct global resource ID
        cur_w = self.conn_words.cursor()
        slide_layout_revs = ','.join(['1'] * slide_count)
        slide_revs = ','.join(['1'] * slide_count)
        cur_w.execute(
            "INSERT INTO word (song_id, words, slide_uids, "
            "slide_layout_revisions, slide_revisions) VALUES (?, ?, ?, ?, ?)",
            (song_id, rtf_text, slide_uids, slide_layout_revs, slide_revs)
        )
        self.conn_words.commit()

        return song_id, song_uid

    def rebuild_search_index(self, song_id, title, lyrics_text):
        """
        Rebuild the search index in SongKeys.db for a given song.
        """
        cur = self.conn_keys.cursor()

        # Remove existing entries for this song
        cur.execute("DELETE FROM word_key WHERE link_id = ?", (song_id,))

        # Extract words from title and lyrics
        def extract_words(text):
            """Extract searchable words from text."""
            # Remove [SLIDE] markers
            text = text.replace(SLIDE_MARKER, ' ')
            # Split on whitespace and punctuation
            words = re.findall(r'[\w\u0D80-\u0DFF]+', text.lower(), re.UNICODE)
            return set(words)

        title_words = extract_words(title)
        lyrics_words = extract_words(lyrics_text)

        for word in title_words | lyrics_words:
            if not word:
                continue

            # Check if word exists in word_list
            cur.execute("SELECT rowid FROM word_list WHERE word = ?", (word,))
            row = cur.fetchone()
            if row:
                word_list_id = row[0]
            else:
                cur.execute("INSERT INTO word_list (word) VALUES (?)", (word,))
                word_list_id = cur.lastrowid

            # Combine field flags with bitwise OR into a single value
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

    db_files = [SONG_HISTORY_DB, SONG_WORDS_DB, SONG_KEYS_DB]
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
    resource_offset = db.get_resource_offset()
    log(f"Resource offset: {resource_offset} "
        f"(SongWords.song_id = SongHistory.rowid + {resource_offset})")

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
                song_id, song_uid = db.import_song(hymn, resource_offset)

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
            has_history = os.path.exists(os.path.join(path, SONG_HISTORY_DB))
            has_words = os.path.exists(os.path.join(path, SONG_WORDS_DB))
            if has_history and has_words:
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
            text="EW7 Database Location (folder containing SongHistory.db)",
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

        history_path = os.path.join(path, SONG_HISTORY_DB)
        words_path = os.path.join(path, SONG_WORDS_DB)

        if not os.path.exists(history_path):
            self.db_info.set("SongHistory.db not found in this folder")
            return

        try:
            conn = sqlite3.connect(history_path)
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
                f"Found: {song_count} songs in history, "
                f"{words_count} with lyrics"
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
            title="Select folder containing EW7 database files (SongHistory.db, etc.)",
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

        for db_name in [SONG_HISTORY_DB, SONG_WORDS_DB, SONG_KEYS_DB]:
            if not os.path.exists(os.path.join(path, db_name)):
                messagebox.showerror(
                    "Error",
                    f"Required database file not found: {db_name}\n"
                    f"in folder: {path}\n\n"
                    f"The folder should contain SongHistory.db, SongWords.db, "
                    f"and SongKeys.db.\n"
                    f"Typical path: C:\\Users\\Public\\Documents\\Softouch\\"
                    f"EasyWorship\\Default\\Databases\\Data\\"
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

  # Launch the GUI (default, no arguments)
  python ew_tool.py
        """
    )
    subparsers = parser.add_subparsers(dest='command')

    # Import subcommand
    imp = subparsers.add_parser('import', help='Import songs from .txt files')
    imp.add_argument('--db', required=True,
                     help='Path to EW7 database folder (containing SongHistory.db)')
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

    args = parser.parse_args()

    if args.command is None:
        # No subcommand — launch GUI
        root = tk.Tk()
        app = EWToolApp(root)
        root.mainloop()
        return

    if args.command == 'import':
        db = EWDatabase(args.db)
        try:
            imported, skipped, errors = import_songs(
                db, args.input,
                skip_duplicates=not args.allow_duplicates,
                log_callback=print
            )
            print(f"\nDone: {imported} imported, {skipped} skipped, {errors} errors")
        finally:
            db.close()

    elif args.command == 'export':
        db = EWDatabase(args.db)
        try:
            songs = db.get_all_songs()
            os.makedirs(args.output, exist_ok=True)
            count = export_songs(db, songs, args.output, log_callback=print)
            print(f"\nDone: exported {count} songs to {args.output}")
        finally:
            db.close()

    elif args.command == 'backup':
        result = backup_databases(args.db, args.output)
        print(f"Backup created: {result}")


if __name__ == '__main__':
    main()
