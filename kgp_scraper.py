#!/usr/bin/env python3
"""
KGP Scraper — Kithunu Gee Potha Hymn Lyrics Scraper
Scrapes Sinhala hymn lyrics from http://www.chamathwebs.com/kgp/
Outputs .txt files compatible with ew_tool.py import format.

Requirements: pip install requests beautifulsoup4
(Falls back to stdlib urllib if not available)
"""

import os
import re
import sys
import json
import time
import hashlib

# Try to use requests + bs4, fall back to stdlib
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    import urllib.request
    HAS_DEPS = False
    print("Warning: requests/beautifulsoup4 not installed. Using stdlib (limited).")
    print("Install with: pip install requests beautifulsoup4")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "http://www.chamathwebs.com/kgp"
INDEX_URL = f"{BASE_URL}/index.asp"
PAGE_URL_TEMPLATE = f"{BASE_URL}/page.asp?LyricsID={{id}}&txtPass="

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "kgp")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "kgp")

RATE_LIMIT_SECONDS = 1.5  # Delay between requests
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

META_FENCE = "---"
SLIDE_MARKER = "[SLIDE]"


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------

def fetch_url(url, use_cache=True):
    """Fetch a URL, with optional file-based caching."""
    # Check cache
    if use_cache:
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}.html")
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return f.read()

    # Fetch
    if HAS_DEPS:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        # Try to detect encoding
        resp.encoding = resp.apparent_encoding or 'utf-8'
        html = resp.text
    else:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        raw = resp.read()
        # Try utf-8, fall back to latin-1
        try:
            html = raw.decode('utf-8')
        except UnicodeDecodeError:
            html = raw.decode('latin-1')

    # Save to cache
    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(html)

    return html


# ---------------------------------------------------------------------------
# Index Parser
# ---------------------------------------------------------------------------

def parse_index(html):
    """
    Parse the KGP index page to extract hymn metadata.
    Returns list of dicts with: id, number, title_sinhala, title_singlish, book_ref, url

    The index page structure (from historical analysis):
    - Each hymn is listed with a Sinhala title, singlish transliteration in parentheses,
      and a book reference like #B164
    - Links point to page.asp?LyricsID={id}&txtPass=
    """
    if not HAS_DEPS:
        print("Error: beautifulsoup4 required for parsing. Install: pip install beautifulsoup4")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    hymns = []

    # Look for hymn links — expected format: page.asp?LyricsID=NNN
    for link in soup.find_all('a', href=True):
        href = link['href']
        match = re.search(r'LyricsID=([^&]+)', href)
        if not match:
            continue

        lyrics_id = match.group(1)
        text = link.get_text(strip=True)

        # Try to extract: "Sinhala Title (Singlish Title) #BNNN"
        # Pattern: title text, optional (singlish), optional #Bref
        sinhala_title = text
        singlish_title = ""
        book_ref = ""

        # Extract book reference
        ref_match = re.search(r'(#B\d+)', text)
        if ref_match:
            book_ref = ref_match.group(1)
            text = text[:ref_match.start()].strip()

        # Extract singlish in parentheses
        paren_match = re.search(r'\(([^)]+)\)', text)
        if paren_match:
            singlish_title = paren_match.group(1).strip()
            sinhala_title = text[:paren_match.start()].strip()
        else:
            sinhala_title = text.strip()

        hymns.append({
            'id': lyrics_id,
            'title_sinhala': sinhala_title,
            'title_singlish': singlish_title,
            'book_ref': book_ref,
            'url': f"{BASE_URL}/{href}" if not href.startswith('http') else href,
        })

    return hymns


# ---------------------------------------------------------------------------
# Lyrics Page Parser
# ---------------------------------------------------------------------------

def parse_lyrics_page(html):
    """
    Parse an individual hymn page to extract formatted lyrics.
    Returns the lyrics text with [SLIDE] markers for verse breaks.
    """
    if not HAS_DEPS:
        return ""

    soup = BeautifulSoup(html, 'html.parser')

    # The lyrics are typically in a main content div or table
    # Look for the largest text block that contains Sinhala characters
    lyrics_text = ""

    # Strategy 1: Look for a specific lyrics container
    for candidate in ['lyrics', 'content', 'song-text', 'songtext']:
        elem = soup.find(id=candidate) or soup.find(class_=candidate)
        if elem:
            lyrics_text = elem.get_text('\n', strip=True)
            break

    # Strategy 2: Find the largest block with Sinhala text
    if not lyrics_text:
        sinhala_pattern = re.compile(r'[\u0D80-\u0DFF]')
        best_text = ""
        for tag in soup.find_all(['div', 'td', 'p', 'pre']):
            text = tag.get_text('\n', strip=True)
            if sinhala_pattern.search(text) and len(text) > len(best_text):
                best_text = text
        lyrics_text = best_text

    if not lyrics_text:
        return ""

    # Clean up: normalize line breaks, detect verse structure
    lines = lyrics_text.split('\n')
    cleaned_lines = []
    blank_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            blank_count += 1
            if blank_count == 1:
                # Single blank line between verses → slide marker
                cleaned_lines.append(SLIDE_MARKER)
            continue
        blank_count = 0
        cleaned_lines.append(line)

    # Remove leading/trailing slide markers
    while cleaned_lines and cleaned_lines[0] == SLIDE_MARKER:
        cleaned_lines.pop(0)
    while cleaned_lines and cleaned_lines[-1] == SLIDE_MARKER:
        cleaned_lines.pop()

    return '\n'.join(cleaned_lines)


# ---------------------------------------------------------------------------
# TXT Writer
# ---------------------------------------------------------------------------

def write_hymn_txt(filepath, hymn, lyrics):
    """Write a single hymn to a .txt file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f'{META_FENCE}\n')
        f.write(f'title: {hymn.get("title_singlish", "") or hymn.get("title_sinhala", "")}\n')
        f.write(f'title_sinhala: {hymn.get("title_sinhala", "")}\n')
        f.write(f'author: \n')
        f.write(f'copyright: \n')
        f.write(f'ccli: \n')
        f.write(f'book_ref: {hymn.get("book_ref", "")}\n')
        f.write(f'source: kgp\n')
        f.write(f'{META_FENCE}\n\n')
        f.write(lyrics)
        f.write('\n')


# ---------------------------------------------------------------------------
# Main Scraper
# ---------------------------------------------------------------------------

def scrape_all(use_cache=True):
    """Scrape all hymns from the KGP site."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    print(f"Fetching index page: {INDEX_URL}")
    try:
        index_html = fetch_url(INDEX_URL, use_cache=use_cache)
    except Exception as e:
        print(f"Error fetching index page: {e}")
        print("\nThe KGP site may be down. Check: http://www.chamathwebs.com/kgp/index.asp")
        print("If you have cached HTML files, place them in:", CACHE_DIR)
        return

    hymns = parse_index(index_html)
    total = len(hymns)
    print(f"Found {total} hymns in index")

    if total == 0:
        print("No hymns found. The page structure may have changed.")
        return

    scraped = 0
    errors = 0

    for i, hymn in enumerate(hymns):
        try:
            # Check if already scraped
            title = hymn.get('title_singlish', '') or hymn.get('title_sinhala', '') or f"hymn_{hymn['id']}"
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:80]
            filepath = os.path.join(OUTPUT_DIR, f"{safe_title}.txt")

            if os.path.exists(filepath) and use_cache:
                scraped += 1
                continue

            # Fetch lyrics page
            page_html = fetch_url(hymn['url'], use_cache=use_cache)
            lyrics = parse_lyrics_page(page_html)

            if not lyrics:
                print(f"  Warning: No lyrics found for {title} (ID: {hymn['id']})")
                errors += 1
                continue

            write_hymn_txt(filepath, hymn, lyrics)
            scraped += 1

            if (i + 1) % 10 == 0:
                print(f"  Scraped {i + 1}/{total} hymns...")

            # Rate limiting
            time.sleep(RATE_LIMIT_SECONDS)

        except Exception as e:
            print(f"  Error scraping hymn {hymn.get('id', '?')}: {e}")
            errors += 1

    print(f"\nScraping complete: {scraped} scraped, {errors} errors")
    print(f"Output directory: {OUTPUT_DIR}")


# ---------------------------------------------------------------------------
# Cached/Offline Mode — import from pre-downloaded data
# ---------------------------------------------------------------------------

def import_from_cache():
    """
    If the site is down, users can manually place HTML files in the cache dir.
    This function processes cached files.
    """
    if not os.path.isdir(CACHE_DIR):
        print(f"Cache directory not found: {CACHE_DIR}")
        return

    html_files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.html')]
    if not html_files:
        print(f"No cached HTML files found in: {CACHE_DIR}")
        return

    print(f"Found {len(html_files)} cached HTML files")
    # Process the index file first if present
    # Then process individual pages
    print("Processing cached files...")
    scrape_all(use_cache=True)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="KGP Hymn Lyrics Scraper")
    parser.add_argument('--no-cache', action='store_true', help="Ignore cached files")
    parser.add_argument('--cache-only', action='store_true',
                        help="Only process cached files (offline mode)")
    parser.add_argument('--output', default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    if args.output != OUTPUT_DIR:
        OUTPUT_DIR = args.output

    if args.cache_only:
        import_from_cache()
    else:
        scrape_all(use_cache=not args.no_cache)
