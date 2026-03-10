#!/usr/bin/env python3
"""
EWB Bible Builder — Creates EasyWorship 7 .ewb Bible files (SQLite format)
from the Holy-Bible-XML-Format (Beblia) XML files.

Usage:
    python ewb_builder.py --xml SinhalaSROVBible.xml --output SROV.ewb --name SROV

EW7 .ewb files are SQLite databases with tables:
  - header:  translation metadata
  - books:   book metadata with binary book_info and verse_info blobs
  - streams: zlib-compressed verse text per book
  - words:   word lookup table for searching
"""

import os
import re
import sys
import struct
import zlib
import sqlite3
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Standard Bible book names & abbreviations
# ---------------------------------------------------------------------------

BOOKS = [
    # (name, abbreviation)
    # Old Testament (39 books)
    ("Genesis", "Gn"), ("Exodus", "Ex"), ("Leviticus", "Lv"),
    ("Numbers", "Nm"), ("Deuteronomy", "Dt"), ("Joshua", "Jos"),
    ("Judges", "Jgs"), ("Ruth", "Ru"), ("1 Samuel", "1 Sm"),
    ("2 Samuel", "2 Sm"), ("1 Kings", "1 Kgs"), ("2 Kings", "2 Kgs"),
    ("1 Chronicles", "1 Chr"), ("2 Chronicles", "2 Chr"), ("Ezra", "Ezr"),
    ("Nehemiah", "Neh"), ("Esther", "Est"), ("Job", "Jb"),
    ("Psalms", "Ps"), ("Proverbs", "Prv"), ("Ecclesiastes", "Eccl"),
    ("Song of Solomon", "Sg"), ("Isaiah", "Is"), ("Jeremiah", "Jer"),
    ("Lamentations", "Lam"), ("Ezekiel", "Ez"), ("Daniel", "Dn"),
    ("Hosea", "Hos"), ("Joel", "Jl"), ("Amos", "Am"),
    ("Obadiah", "Ob"), ("Jonah", "Jon"), ("Micah", "Mi"),
    ("Nahum", "Na"), ("Habakkuk", "Hb"), ("Zephaniah", "Zep"),
    ("Haggai", "Hg"), ("Zechariah", "Zec"), ("Malachi", "Mal"),
    # New Testament (27 books)
    ("Matthew", "Mt"), ("Mark", "Mk"), ("Luke", "Lk"),
    ("John", "Jn"), ("Acts", "Acts"), ("Romans", "Rom"),
    ("1 Corinthians", "1 Cor"), ("2 Corinthians", "2 Cor"),
    ("Galatians", "Gal"), ("Ephesians", "Eph"), ("Philippians", "Phil"),
    ("Colossians", "Col"), ("1 Thessalonians", "1 Thes"),
    ("2 Thessalonians", "2 Thes"), ("1 Timothy", "1 Tm"),
    ("2 Timothy", "2 Tm"), ("Titus", "Ti"), ("Philemon", "Phlm"),
    ("Hebrews", "Heb"), ("James", "Jas"), ("1 Peter", "1 Pt"),
    ("2 Peter", "2 Pt"), ("1 John", "1 Jn"), ("2 John", "2 Jn"),
    ("3 John", "3 Jn"), ("Jude", "Jude"), ("Revelation", "Rv"),
]


# ---------------------------------------------------------------------------
# XML Parser
# ---------------------------------------------------------------------------

def parse_bible_xml(xml_path):
    """
    Parse a Beblia Holy-Bible-XML-Format file.
    Returns list of book dicts with:
        - name: English book name
        - abbrev: Abbreviation
        - chapters: list of lists of verse strings
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    books = []
    book_index = 0

    for testament in root.findall('testament'):
        for book_el in testament.findall('book'):
            chapters = []
            for chapter_el in book_el.findall('chapter'):
                verses = []
                for verse_el in chapter_el.findall('verse'):
                    text = verse_el.text or ''
                    text = text.strip()
                    verses.append(text)
                chapters.append(verses)

            if book_index < len(BOOKS):
                name, abbrev = BOOKS[book_index]
            else:
                name, abbrev = f"Book {book_index + 1}", f"Bk{book_index + 1}"

            books.append({
                'name': name,
                'abbrev': abbrev,
                'chapters': chapters,
            })
            book_index += 1

    return books


# ---------------------------------------------------------------------------
# Binary encoding helpers
# ---------------------------------------------------------------------------

def encode_book_info(chapters):
    """
    Encode book_info blob: 1 byte chapter count + 1 byte per chapter (verse count).
    """
    num_chapters = len(chapters)
    data = bytearray()
    data.append(num_chapters & 0xFF)
    for chapter in chapters:
        data.append(len(chapter) & 0xFF)
    return bytes(data)


def encode_verse_data(verse_length, stream_position):
    """
    Encode 4 bytes of verse location data:
      Byte 0: verse_length (low 8 bits)
      Bytes 1-3: stream_position (24-bit little-endian)
    With overflow: if verse_length > 255, overflow adds to byte 1.
    """
    b0 = verse_length & 0xFF
    overflow = (verse_length >> 8) & 0xFF
    pos = stream_position + overflow  # overflow cascades into position
    b1 = pos & 0xFF
    b2 = (pos >> 8) & 0xFF
    b3 = (pos >> 16) & 0xFF
    # Actually, the overflow mechanism works differently:
    # byte0 = verse_length % 256
    # carry = verse_length // 256
    # The 3-byte position field = stream_position + carry
    # But let's keep it simple - most verses are < 256 bytes in UTF-8 stream offset
    # For Sinhala, verses can be long, but the position is the important part
    return struct.pack('<I', (stream_position << 8) | (verse_length & 0xFF))


def encode_verse_id(verse_no, chapter_no, book_no, translation_id):
    """
    Encode 4 bytes of verse identification:
      Byte 0: verse_no * 4 (low byte, overflow cascades)
      Byte 1: chapter_no * 4 (low byte, overflow cascades)
      Byte 2: book_no * 4 (low byte, overflow cascades)
      Byte 3: translation_id * 2
    """
    v = verse_no * 4
    c = chapter_no * 4
    b = book_no * 4
    t = translation_id * 2

    b0 = v & 0xFF
    carry = v >> 8
    c += carry
    b1 = c & 0xFF
    carry = c >> 8
    b += carry
    b2 = b & 0xFF
    carry = b >> 8
    t += carry
    b3 = t & 0xFF

    return bytes([b0, b1, b2, b3])


def build_verse_info(book, book_index, translation_id):
    """
    Build the verse_info blob for a book.
    Each verse gets 8 bytes: 4 bytes location + 4 bytes identification.
    """
    # First, build the full text stream to calculate positions
    text_parts = []
    for chapter in book['chapters']:
        for verse_text in chapter:
            text_parts.append(verse_text)

    # Calculate stream positions (byte offsets in the uncompressed text stream)
    stream_text = ""
    verse_entries = []
    for ch_idx, chapter in enumerate(book['chapters']):
        for v_idx, verse_text in enumerate(chapter):
            stream_pos = len(stream_text.encode('utf-8'))
            verse_len = len(verse_text.encode('utf-8'))

            verse_entries.append((
                verse_len, stream_pos,
                v_idx + 1, ch_idx + 1, book_index + 1, translation_id
            ))
            stream_text += verse_text

    # Encode all verse entries
    data = bytearray()
    for verse_len, stream_pos, v_no, ch_no, bk_no, trans_id in verse_entries:
        # Location data: 4 bytes
        loc = bytearray(4)
        loc[0] = verse_len & 0xFF
        carry = verse_len >> 8
        pos_with_carry = stream_pos + carry
        loc[1] = pos_with_carry & 0xFF
        loc[2] = (pos_with_carry >> 8) & 0xFF
        loc[3] = (pos_with_carry >> 16) & 0xFF
        data += loc

        # ID data: 4 bytes
        data += encode_verse_id(v_no, ch_no, bk_no, trans_id)

    return bytes(data)


def build_stream_text(book):
    """Build the raw text for a book (all verses concatenated, no separators)."""
    parts = []
    for chapter in book['chapters']:
        for verse_text in chapter:
            parts.append(verse_text)
    return ''.join(parts)


def compress_stream(text):
    """
    Compress book text into streams format:
      2-byte dummy prefix + zlib data + 10-byte trailer
    Trailer: QK\x03\x04 + u32(uncompressed_length) + \x08\x00
    """
    text_bytes = text.encode('utf-8')
    compressed = zlib.compress(text_bytes)
    uncompressed_len = len(text_bytes)

    stream = bytearray()
    # 2-byte dummy prefix (ignored by EW)
    stream += b'\x00\x00'
    # zlib compressed data
    stream += compressed
    # 10-byte trailer
    stream += b'\x51\x4b\x03\x04'  # QK magic
    stream += struct.pack('<I', uncompressed_len)
    stream += b'\x08\x00'

    return bytes(stream)


def extract_words(book, book_index, translation_id, spaced=True):
    """
    Extract words from a book for the words table.
    Returns dict: word -> list of verse_info entries (8 bytes each).
    """
    words = {}

    for ch_idx, chapter in enumerate(book['chapters']):
        for v_idx, verse_text in enumerate(chapter):
            verse_len = len(verse_text.encode('utf-8'))
            stream_pos = 0  # We don't need exact position for word search

            # Calculate stream position
            pos = 0
            for ci in range(ch_idx):
                for vi in range(len(book['chapters'][ci])):
                    pos += len(book['chapters'][ci][vi].encode('utf-8'))
            for vi in range(v_idx):
                pos += len(book['chapters'][ch_idx][vi].encode('utf-8'))
            stream_pos = pos

            v_no = v_idx + 1
            ch_no = ch_idx + 1
            bk_no = book_index + 1

            # Verse ID bytes
            id_bytes = encode_verse_id(v_no, ch_no, bk_no, translation_id)

            # Location bytes
            loc = bytearray(4)
            loc[0] = verse_len & 0xFF
            carry = verse_len >> 8
            pos_with_carry = stream_pos + carry
            loc[1] = pos_with_carry & 0xFF
            loc[2] = (pos_with_carry >> 8) & 0xFF
            loc[3] = (pos_with_carry >> 16) & 0xFF

            entry = bytes(loc) + id_bytes

            if spaced:
                # Split on word boundaries
                word_list = re.findall(r'[\w]+', verse_text, re.UNICODE)
            else:
                # Character-by-character for CJK-like languages
                word_list = list(verse_text.replace(' ', ''))

            for w in word_list:
                w_lower = w.lower()
                if w_lower not in words:
                    words[w_lower] = bytearray()
                words[w_lower] += entry

    return words


# ---------------------------------------------------------------------------
# EWB File Builder
# ---------------------------------------------------------------------------

def build_ewb(books, bible_id, bible_name, bible_abbrev, lang_code,
              output_path, copyright_text="", spaced=True):
    """
    Build an EasyWorship .ewb bible file (SQLite format).
    """
    translation_id = bible_id

    # Remove existing file
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    cur = conn.cursor()

    # Create tables
    cur.execute("""
        CREATE TABLE header (
            id INTEGER,
            name TEXT,
            abbrev_name TEXT,
            lang_code TEXT,
            copyright TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE books (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            abbrev_name TEXT,
            alt_name TEXT,
            book_info BLOB,
            verse_info BLOB
        )
    """)

    cur.execute("""
        CREATE TABLE streams (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            stream BLOB
        )
    """)

    cur.execute("""
        CREATE TABLE words (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            verse_info BLOB
        )
    """)

    # Insert header
    cur.execute(
        "INSERT INTO header (id, name, abbrev_name, lang_code, copyright) "
        "VALUES (?, ?, ?, ?, ?)",
        (translation_id, bible_name, bible_abbrev, lang_code, copyright_text)
    )

    # Process each book
    total_verses = 0
    all_words = {}

    for i, book in enumerate(books):
        # book_info blob
        book_info = encode_book_info(book['chapters'])

        # verse_info blob
        verse_info = build_verse_info(book, i, translation_id)

        # Stream text and compression
        text = build_stream_text(book)
        stream = compress_stream(text)

        # Count verses
        num_verses = sum(len(ch) for ch in book['chapters'])
        total_verses += num_verses

        # Insert book record
        cur.execute(
            "INSERT INTO books (name, abbrev_name, alt_name, book_info, verse_info) "
            "VALUES (?, ?, ?, ?, ?)",
            (book['name'], book['abbrev'], book['name'], book_info, verse_info)
        )

        # Insert stream (rowid matches book rowid)
        cur.execute(
            "INSERT INTO streams (stream) VALUES (?)",
            (stream,)
        )

        # Extract words for search
        book_words = extract_words(book, i, translation_id, spaced=spaced)
        for word, entries in book_words.items():
            if word in all_words:
                all_words[word] += entries
            else:
                all_words[word] = bytearray(entries)

        print(f"  [{i+1:2d}/{len(books)}] {book['name']:20s} "
              f"{len(book['chapters']):3d} chapters, {num_verses:4d} verses")

    # Insert words
    print(f"  Building word index ({len(all_words)} unique words)...")
    for word, verse_data in sorted(all_words.items()):
        cur.execute(
            "INSERT INTO words (word, verse_info) VALUES (?, ?)",
            (word, bytes(verse_data))
        )

    conn.commit()
    conn.close()

    file_size = os.path.getsize(output_path)
    print(f"\nCreated: {output_path}")
    print(f"  {len(books)} books, {total_verses} verses")
    print(f"  {len(all_words)} searchable words")
    print(f"  File size: {file_size:,} bytes")
    print(f"  Bible ID: {translation_id}, Name: {bible_name} ({bible_abbrev})")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_ewb(ewb_path):
    """Read back an .ewb file and verify it can be parsed."""
    conn = sqlite3.connect(ewb_path)
    cur = conn.cursor()

    # Check header
    cur.execute("SELECT id, name, abbrev_name, lang_code FROM header")
    row = cur.fetchone()
    if not row:
        print("ERROR: No header record found")
        return False
    print(f"Verified: {ewb_path}")
    print(f"  Translation: {row[1]} ({row[2]}), Lang: {row[3]}, ID: {row[0]}")

    # Check books
    cur.execute("SELECT COUNT(*) FROM books")
    num_books = cur.fetchone()[0]
    print(f"  Books: {num_books}")

    # Check streams
    cur.execute("SELECT COUNT(*) FROM streams")
    num_streams = cur.fetchone()[0]
    print(f"  Streams: {num_streams}")

    # Check words
    cur.execute("SELECT COUNT(*) FROM words")
    num_words = cur.fetchone()[0]
    print(f"  Words: {num_words}")

    # Decompress first book
    cur.execute("SELECT stream FROM streams WHERE rowid = 1")
    stream_row = cur.fetchone()
    if stream_row:
        stream = stream_row[0]
        # Skip 2-byte dummy prefix, decompress up to trailer
        # Find the QK trailer
        qk_pos = stream.rfind(b'\x51\x4b\x03\x04')
        if qk_pos > 2:
            compressed = stream[2:qk_pos]
            text = zlib.decompress(compressed).decode('utf-8')
            print(f"  First book sample: {text[:120]}...")
        else:
            print("  WARNING: Could not find QK trailer in stream")

    # Verify book_info for first book
    cur.execute("SELECT name, book_info FROM books WHERE rowid = 1")
    brow = cur.fetchone()
    if brow:
        bi = brow[1]
        num_ch = bi[0]
        total_v = sum(bi[1:1+num_ch])
        print(f"  {brow[0]}: {num_ch} chapters, {total_v} verses")

    conn.close()
    print("  OK")
    return True


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Build EasyWorship .ewb Bible files (SQLite format) from XML"
    )
    parser.add_argument('--xml', required=True,
                        help="Path to Beblia XML bible file")
    parser.add_argument('--output', '-o', default=None,
                        help="Output .ewb file path")
    parser.add_argument('--name', default='SROV',
                        help="Bible display name (default: SROV)")
    parser.add_argument('--abbrev', default=None,
                        help="Bible abbreviation (default: same as --name)")
    parser.add_argument('--lang', default='SI',
                        help="Language code (default: SI)")
    parser.add_argument('--id', type=int, default=127,
                        help="Bible ID 1-127 (default: 127)")
    parser.add_argument('--copyright', default='',
                        help="Copyright text")
    parser.add_argument('--no-spaced', action='store_true',
                        help="Use character-level word extraction (for CJK)")
    parser.add_argument('--verify', action='store_true',
                        help="Verify the output file after creation")

    args = parser.parse_args()

    if not os.path.exists(args.xml):
        print(f"Error: XML file not found: {args.xml}")
        sys.exit(1)

    output = args.output or os.path.splitext(args.xml)[0] + '.ewb'
    abbrev = args.abbrev or args.name

    print(f"Parsing XML: {args.xml}")
    books = parse_bible_xml(args.xml)
    print(f"  Found {len(books)} books")

    print(f"Building EWB (SQLite): {output}")
    build_ewb(
        books,
        bible_id=args.id,
        bible_name=args.name,
        bible_abbrev=abbrev,
        lang_code=args.lang,
        output_path=output,
        copyright_text=args.copyright,
        spaced=not args.no_spaced,
    )

    if args.verify:
        print()
        verify_ewb(output)
