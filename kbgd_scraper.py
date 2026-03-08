#!/usr/bin/env python3
"""
KBGD Scraper — Kithu Bathi Gee Dahana Hymn Scraper
Fetches hymns from https://www.kithubathigeedahana.lk/ API,
strips guitar chords, and outputs .txt files for ew_tool.py import.

Uses the site's public API: /api/songs?limit=1000
No external dependencies required (stdlib only).
"""

import os
import re
import sys
import json
import time
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://www.kithubathigeedahana.lk/api"
SONGS_URL = f"{API_BASE}/songs?limit=1000"
CATEGORIES_URL = f"{API_BASE}/categories"

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "kbgd")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "kbgd")
CACHE_FILE = os.path.join(CACHE_DIR, "songs.json")

REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

META_FENCE = "---"
SLIDE_MARKER = "[SLIDE]"


# ---------------------------------------------------------------------------
# API Fetch
# ---------------------------------------------------------------------------

def fetch_json(url):
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    return json.loads(resp.read().decode('utf-8'))


def fetch_songs(use_cache=True):
    """Fetch all songs from the KBGD API, with optional caching."""
    if use_cache and os.path.exists(CACHE_FILE):
        print(f"Loading from cache: {CACHE_FILE}")
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    print(f"Fetching songs from API: {SONGS_URL}")
    songs = fetch_json(SONGS_URL)
    print(f"Fetched {len(songs)} songs")

    # Cache the response
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)
    print(f"Cached to: {CACHE_FILE}")

    return songs


# ---------------------------------------------------------------------------
# Chord Stripping
# ---------------------------------------------------------------------------

# Regex: bracketed chords like [Am], [G7], [Cmaj7], [D/F#]
RE_BRACKETED_CHORD = re.compile(
    r'\[([A-G][#b]?'
    r'(?:m|maj|min|dim|aug|sus[24]?|add|no)?'
    r'[0-9]*'
    r'(?:/[A-G][#b]?)?)\]'
)

# Regex: standalone chord-only lines (lines with ONLY chord names and whitespace)
RE_CHORD_LINE = re.compile(
    r'^[ \t]*(?:[A-G][#b]?'
    r'(?:m|maj|min|dim|aug|sus[24]?|add|no)?'
    r'[0-9]*'
    r'(?:/[A-G][#b]?)?\s*)+$',
    re.MULTILINE
)

# ChordPro directives to strip
RE_CHORDPRO_DIRECTIVE = re.compile(
    r'\{(?:start_of_chorus|end_of_chorus|start_of_verse|end_of_verse|'
    r'start_of_bridge|end_of_bridge|start_of_tab|end_of_tab|'
    r'soc|eoc|sov|eov|sob|eob|sot|eot|'
    r'comment|ci|title|subtitle|artist|composer|key|tempo|time|'
    r'capo|define|meta)[^}]*\}',
    re.IGNORECASE
)

# Lines that are chord/song metadata (e.g. "කෝඩ් සැකසුම : ...", "{composer: ...}")
RE_CHORD_META = re.compile(
    r'^(?:කෝඩ්\s*සැකසුම|chord|chords?\s*(?:by|arrangement)|key|beat|tempo)\s*[:：].*$',
    re.MULTILINE | re.IGNORECASE
)


def strip_chords(text):
    """
    Remove all chord notation from lyrics text.
    Handles: [Am], ChordPro directives, standalone chord lines, chord metadata.
    """
    if not text:
        return ""

    # Strip ChordPro directives
    text = RE_CHORDPRO_DIRECTIVE.sub('', text)

    # Strip bracketed chords
    text = RE_BRACKETED_CHORD.sub('', text)

    # Strip standalone chord-only lines
    text = RE_CHORD_LINE.sub('', text)

    # Strip chord metadata lines (Sinhala/English)
    text = RE_CHORD_META.sub('', text)

    # Clean up: collapse multiple blank lines, trim whitespace per line
    lines = text.split('\n')
    cleaned = []
    prev_blank = False
    for line in lines:
        line = line.rstrip()
        # Also strip leading whitespace that was left after chord removal
        stripped = line.strip()
        if not stripped:
            if not prev_blank:
                cleaned.append('')
            prev_blank = True
        else:
            cleaned.append(stripped)
            prev_blank = False

    # Remove leading/trailing blanks
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()

    return '\n'.join(cleaned)


# ---------------------------------------------------------------------------
# Lyrics Processing
# ---------------------------------------------------------------------------

def process_lyrics(raw_lyrics):
    """
    Process raw lyrics_chords field:
    1. Strip chords and ChordPro directives
    2. Detect verse/chorus structure → [SLIDE] markers
    3. Clean up formatting
    """
    if not raw_lyrics:
        return ""

    # Normalize line endings
    text = raw_lyrics.replace('\r\n', '\n').replace('\r', '\n')

    # Detect chorus/verse structure from ChordPro markers BEFORE stripping
    has_sections = '{start_of_' in text.lower() or '{soc}' in text.lower()

    # If there are ChordPro section markers, use them for slide breaks
    if has_sections:
        # Replace section boundaries with slide markers
        # First mark section starts
        text = re.sub(
            r'\{(?:start_of_chorus|start_of_verse|start_of_bridge|soc|sov|sob)\}',
            '\n__SLIDE__\n', text, flags=re.IGNORECASE
        )
        # Remove section ends
        text = re.sub(
            r'\{(?:end_of_chorus|end_of_verse|end_of_bridge|eoc|eov|eob)\}',
            '', text, flags=re.IGNORECASE
        )

    # Strip all remaining chords
    text = strip_chords(text)

    # Convert __SLIDE__ markers
    if has_sections:
        lines = text.split('\n')
        result_lines = []
        for line in lines:
            if '__SLIDE__' in line:
                # Add slide marker (but avoid duplicates)
                if result_lines and result_lines[-1] != SLIDE_MARKER:
                    result_lines.append(SLIDE_MARKER)
            else:
                result_lines.append(line)
        text = '\n'.join(result_lines)
    else:
        # No ChordPro sections: use double blank lines as slide breaks
        text = re.sub(r'\n\n\n+', f'\n{SLIDE_MARKER}\n', text)

    # Final cleanup
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped == SLIDE_MARKER:
            # Avoid consecutive slide markers
            if cleaned and cleaned[-1] != SLIDE_MARKER:
                cleaned.append(SLIDE_MARKER)
        elif stripped:
            cleaned.append(stripped)

    # Remove leading/trailing slide markers
    while cleaned and cleaned[0] == SLIDE_MARKER:
        cleaned.pop(0)
    while cleaned and cleaned[-1] == SLIDE_MARKER:
        cleaned.pop()

    return '\n'.join(cleaned)


# ---------------------------------------------------------------------------
# Title Processing
# ---------------------------------------------------------------------------

def extract_titles(song_name):
    """
    Extract Sinhala and Singlish titles from song_name.
    Format: "සිංහල මාතෘකාව / Singlish Title"
    Returns (singlish_title, sinhala_title).
    """
    if not song_name:
        return ("Untitled", "")

    # Split on " / " separator
    if ' / ' in song_name:
        parts = song_name.split(' / ', 1)
        sinhala = parts[0].strip()
        singlish = parts[1].strip()
        return (singlish, sinhala)

    # Check if the name is primarily Sinhala
    sinhala_chars = len(re.findall(r'[\u0D80-\u0DFF]', song_name))
    if sinhala_chars > 0:
        return (song_name, song_name)

    return (song_name, "")


# ---------------------------------------------------------------------------
# TXT Writer
# ---------------------------------------------------------------------------

def write_hymn_txt(filepath, singlish_title, sinhala_title, artist, category, lyrics):
    """Write a single hymn to a .txt file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f'{META_FENCE}\n')
        f.write(f'title: {singlish_title}\n')
        f.write(f'title_sinhala: {sinhala_title}\n')
        f.write(f'author: {artist}\n')
        f.write(f'copyright: \n')
        f.write(f'ccli: \n')
        f.write(f'book_ref: \n')
        f.write(f'source: kbgd\n')
        f.write(f'{META_FENCE}\n\n')
        f.write(lyrics)
        f.write('\n')


# ---------------------------------------------------------------------------
# Main Scraper
# ---------------------------------------------------------------------------

def scrape_all(use_cache=True):
    """Fetch and process all KBGD hymns."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    songs = fetch_songs(use_cache=use_cache)
    total = len(songs)
    print(f"\nProcessing {total} songs...")

    processed = 0
    skipped = 0
    errors = 0

    for i, song in enumerate(songs):
        try:
            song_name = song.get('song_name', '')
            singlish_title, sinhala_title = extract_titles(song_name)
            artist = song.get('artist', '') or ''
            category = song.get('category', {})
            category_name = category.get('name', '') if category else ''
            raw_lyrics = song.get('lyrics_chords', '')

            if not raw_lyrics:
                skipped += 1
                continue

            # Process lyrics: strip chords, detect structure
            lyrics = process_lyrics(raw_lyrics)

            if not lyrics:
                skipped += 1
                continue

            # Generate filename
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', singlish_title)[:80].strip('_. ')
            if not safe_title:
                safe_title = f"song_{song.get('id', i)}"
            filepath = os.path.join(OUTPUT_DIR, f"{safe_title}.txt")

            # Handle duplicate filenames
            counter = 1
            base_path = filepath
            while os.path.exists(filepath):
                name, ext = os.path.splitext(base_path)
                filepath = f"{name}_{counter}{ext}"
                counter += 1

            write_hymn_txt(filepath, singlish_title, sinhala_title, artist, category_name, lyrics)
            processed += 1

            if (i + 1) % 50 == 0:
                print(f"  Processed {i + 1}/{total} songs...")

        except Exception as e:
            print(f"  Error processing song {song.get('id', '?')}: {e}")
            errors += 1

    print(f"\nProcessing complete:")
    print(f"  Processed: {processed}")
    print(f"  Skipped (no lyrics): {skipped}")
    print(f"  Errors: {errors}")
    print(f"  Output: {OUTPUT_DIR}")

    return processed, skipped, errors


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="KBGD Hymn Scraper (Kithu Bathi Gee Dahana)")
    parser.add_argument('--no-cache', action='store_true',
                        help="Fetch fresh data from API (ignore cache)")
    parser.add_argument('--output', default=None,
                        help="Output directory (default: output/kbgd/)")
    parser.add_argument('--test', type=int, default=0,
                        help="Only process first N songs (for testing)")
    args = parser.parse_args()

    if args.output:
        OUTPUT_DIR = args.output

    if args.test > 0:
        songs = fetch_songs(use_cache=not args.no_cache)
        songs = songs[:args.test]
        print(f"\nTest mode: processing first {args.test} songs")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for song in songs:
            name = song.get('song_name', 'Unknown')
            raw = song.get('lyrics_chords', '')
            processed = process_lyrics(raw)
            print(f"\n{'='*60}")
            print(f"Song: {name}")
            print(f"{'='*60}")
            print(f"Raw ({len(raw)} chars):")
            print(raw[:200] + "..." if len(raw) > 200 else raw)
            print(f"\nProcessed ({len(processed)} chars):")
            print(processed[:300] + "..." if len(processed) > 300 else processed)
    else:
        scrape_all(use_cache=not args.no_cache)
