#!/usr/bin/env python3
"""
EWB Bible Builder — Creates EasyWorship 7 .ewb Bible files
from the Holy-Bible-XML-Format (Beblia) XML files.

Usage:
    python ewb_builder.py --xml SinhalaSROVBible.xml --output SROV.ewb --name SROV

The tool keeps English book names for searchability while using
Sinhala verse text from the SROV XML.
"""

import os
import re
import sys
import struct
import zlib
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Standard Bible book names (English, for EW search compatibility)
# ---------------------------------------------------------------------------

BOOK_NAMES = [
    # Old Testament (39 books)
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel",
    "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles",
    "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah",
    "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah",
    "Haggai", "Zechariah", "Malachi",
    # New Testament (27 books)
    "Matthew", "Mark", "Luke", "John", "Acts",
    "Romans", "1 Corinthians", "2 Corinthians", "Galatians",
    "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
    "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon",
    "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John",
    "3 John", "Jude", "Revelation",
]

# Block size for book header records
BLOCK_SIZE = 224

# QK header magic bytes
QK_MAGIC = b'\x51\x4b\x03\x04'
QK_FLAG = b'\x08\x00'

# File magic
FILE_MAGIC = b'EasyWorship Bible Text'
FILE_END_MAGIC = b'ezwBible'


# ---------------------------------------------------------------------------
# XML Parser
# ---------------------------------------------------------------------------

def parse_bible_xml(xml_path):
    """
    Parse a Beblia Holy-Bible-XML-Format file.
    Returns list of 66 book dicts with:
        - name: English book name
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

            name = BOOK_NAMES[book_index] if book_index < len(BOOK_NAMES) else f"Book {book_index + 1}"
            books.append({
                'name': name,
                'chapters': chapters,
            })
            book_index += 1

    return books


# ---------------------------------------------------------------------------
# Verse Text Formatter
# ---------------------------------------------------------------------------

def format_book_text(book):
    """
    Format a book's verses in the EWB verse text format:
        chapter:verse text\r\n\r\n
    """
    lines = []
    for ch_idx, chapter in enumerate(book['chapters']):
        ch_num = ch_idx + 1
        for v_idx, verse_text in enumerate(chapter):
            v_num = v_idx + 1
            lines.append(f"{ch_num}:{v_num} {verse_text}\r\n")
    return '\r\n'.join(lines)


# ---------------------------------------------------------------------------
# EWB File Writer
# ---------------------------------------------------------------------------

def build_ewb(books, bible_id, output_path):
    """
    Build an EasyWorship .ewb bible file.

    Format:
        1. 67 x 224-byte header blocks (66 books + 1 footer)
        2. Metadata zlib stream (bible identifier)
        3. 66 x (10-byte QK header + zlib compressed verse text)
        4. Trailer (QK header + offset + 'ezwBible')

    Block layout (224 bytes each):
        +0x00: File magic (block 0 only)
        +0x16: 0x1A, version=0x02 (block 0 only)
        +0x18: u16 ??? (block 0 only, set to 60)
        +0x1C: u32 block_size=224 (block 0 only)
        +0x48: u32 file_offset to previous book's QK+zlib data
        +0x50: u32 compressed_size (QK header + zlib) of previous book
        +0x54: u32 = 1 (block 0 only)
        +0x8B: u8 num_chapters, u8[] verse_counts_per_chapter
    """
    num_books = len(books)

    # --- Build book header blocks ---
    header_blocks = bytearray(BLOCK_SIZE * (num_books + 1))  # +1 for footer

    # Block 0: file header + book 0 verse counts
    header_blocks[0:len(FILE_MAGIC)] = FILE_MAGIC
    header_blocks[0x16] = 0x1A
    header_blocks[0x17] = 0x02
    struct.pack_into('<H', header_blocks, 0x18, 60)
    struct.pack_into('<I', header_blocks, 0x1C, BLOCK_SIZE)
    struct.pack_into('<I', header_blocks, 0x54, 1)

    # Write verse counts for each book into its block
    for i, book in enumerate(books):
        base = i * BLOCK_SIZE
        vc_offset = base + 0x8B
        num_chapters = len(book['chapters'])
        header_blocks[vc_offset] = num_chapters
        for ch_idx, chapter in enumerate(book['chapters']):
            header_blocks[vc_offset + 1 + ch_idx] = len(chapter)

    # --- Compress metadata and book data ---
    meta_compressed = zlib.compress(bible_id.encode('utf-8'))
    meta_decompressed_size = len(bible_id.encode('utf-8'))

    # Build data section: metadata QK + zlib, then per-book QK + zlib
    data_section = bytearray()

    # Metadata QK header + zlib
    data_section += QK_MAGIC
    struct.pack_into('<I', header_blocks, (num_books) * BLOCK_SIZE + 0x58,
                     len(data_section) + 6)  # not sure about this field

    # Actually the footer +0x58 field seems to just be 0x1B in the reference file
    # Let me keep it simple and match the reference format
    # The metadata is embedded right after footer block

    # Reset and rebuild properly
    data_section = bytearray()

    # Compress all books first to know sizes
    book_compressed = []
    book_decompressed_sizes = []
    for book in books:
        text = format_book_text(book)
        text_bytes = text.encode('utf-8')
        compressed = zlib.compress(text_bytes)
        book_compressed.append(compressed)
        book_decompressed_sizes.append(len(text_bytes))

    # Calculate data section start offset
    data_start = BLOCK_SIZE * (num_books + 1)

    # Build data section
    # 1. Metadata zlib
    meta_bytes = bible_id.encode('utf-8')
    meta_zlib = zlib.compress(meta_bytes)
    data_section += meta_zlib

    # 2. Per-book: QK header (10 bytes) + zlib data
    prev_decomp_size = len(meta_bytes)  # first QK header stores metadata decomp size
    book_file_offsets = []
    book_total_sizes = []

    for i in range(num_books):
        # QK header (10 bytes) sits before the zlib data
        qk_header = QK_MAGIC + struct.pack('<I', prev_decomp_size) + QK_FLAG
        data_section += qk_header

        # Record file offset to the ZLIB data (after QK header)
        book_zlib_offset = data_start + len(data_section)
        book_file_offsets.append(book_zlib_offset)

        data_section += book_compressed[i]

        # Size = just the zlib compressed data (without QK header)
        book_total_sizes.append(len(book_compressed[i]))

        prev_decomp_size = book_decompressed_sizes[i]

    # 3. Trailer: QK header + offset + padding + 'ezwBible'
    trailer_qk = QK_MAGIC + struct.pack('<I', prev_decomp_size) + QK_FLAG
    # u32: offset to metadata zlib (= data_start, or we match the reference)
    # The reference file had 0x3A18 which was data_start + some offset
    # Actually looking at reference: the trailer u32 was 0x3A18 = footer_block_start + 0x58
    # That's the absolute file offset right before the metadata zlib starts
    # Let me check: footer is at 66*224 = 14784 (0x39C0), +0x58 = 0x3A18
    # And indeed the metadata zlib starts at 0x3A1C (= 0x3A18 + 4 for the u32 field?)
    # Actually 0x3A18 is where the value 0x1B is stored, and 0x3A1C is where zlib starts
    metadata_offset_field = data_start  # offset to start of data section (metadata zlib)
    trailer = trailer_qk + struct.pack('<I', metadata_offset_field) + b'\x00\x00\x00\x00' + FILE_END_MAGIC
    data_section += trailer

    # --- Fill in offset/size fields in header blocks ---
    # Block N+1 stores: +0x48 = file offset to book N's zlib data
    #                   +0x50 = zlib compressed size of book N
    for i in range(num_books):
        next_block_base = (i + 1) * BLOCK_SIZE
        struct.pack_into('<I', header_blocks, next_block_base + 0x48, book_file_offsets[i])
        struct.pack_into('<I', header_blocks, next_block_base + 0x50, book_total_sizes[i])

    # Footer block: stores last book's offset/size
    # Already handled: block index num_books stores book num_books-1's info

    # --- Write file ---
    with open(output_path, 'wb') as f:
        f.write(header_blocks)
        f.write(data_section)

    total_size = len(header_blocks) + len(data_section)
    total_verses = sum(
        sum(len(ch) for ch in book['chapters'])
        for book in books
    )
    print(f"Created: {output_path}")
    print(f"  {num_books} books, {total_verses} verses")
    print(f"  File size: {total_size:,} bytes")
    print(f"  Bible ID: {bible_id}")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_ewb(ewb_path):
    """Read back an .ewb file and verify it can be parsed."""
    with open(ewb_path, 'rb') as f:
        data = f.read()

    # Check magic
    assert data[:22] == FILE_MAGIC, f"Bad magic: {data[:22]}"
    assert data[-8:] == FILE_END_MAGIC, f"Bad end magic: {data[-8:]}"

    # Read book count from verse count blocks
    num_books = 0
    for i in range(66):
        base = i * BLOCK_SIZE
        if base + 0x8B >= len(data):
            break
        if data[base + 0x8B] > 0:
            num_books += 1
        else:
            break

    print(f"Verified: {ewb_path}")
    print(f"  Books: {num_books}")

    # Decompress and check first and last book
    # Find first book's zlib offset from block 1 (points directly to zlib data)
    first_book_offset = struct.unpack_from('<I', data, BLOCK_SIZE + 0x48)[0]
    dec = zlib.decompress(data[first_book_offset:])
    text = dec.decode('utf-8')
    first_verse = text.split('\r\n\r\n')[0]
    print(f"  First verse: {first_verse[:100]}...")

    # Last book
    last_book_offset = struct.unpack_from('<I', data, num_books * BLOCK_SIZE + 0x48)[0]
    dec = zlib.decompress(data[last_book_offset:])
    text = dec.decode('utf-8')
    verses = [v for v in text.split('\r\n\r\n') if v.strip()]
    print(f"  Last verse: {verses[-1][:100]}...")
    print("  OK")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Build EasyWorship .ewb Bible files from XML"
    )
    parser.add_argument('--xml', required=True,
                        help="Path to Beblia XML bible file")
    parser.add_argument('--output', '-o', default=None,
                        help="Output .ewb file path")
    parser.add_argument('--name', default='SROV',
                        help="Bible identifier name (default: SROV)")
    parser.add_argument('--verify', action='store_true',
                        help="Verify the output file after creation")

    args = parser.parse_args()

    if not os.path.exists(args.xml):
        print(f"Error: XML file not found: {args.xml}")
        sys.exit(1)

    output = args.output or os.path.splitext(args.xml)[0] + '.ewb'

    print(f"Parsing XML: {args.xml}")
    books = parse_bible_xml(args.xml)
    print(f"  Found {len(books)} books")

    print(f"Building EWB: {output}")
    build_ewb(books, args.name, output)

    if args.verify:
        print()
        verify_ewb(output)
