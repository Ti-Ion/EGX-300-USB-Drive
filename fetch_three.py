#!/usr/bin/env python3
"""
fetch_three.py - Download the three.js library used by camm2html.py viewers.

Saves three.min.js into viewer-output/ so generated HTML pages can find it via
a relative path. Run this once before generating viewers; the file is small
(~600 KB) and works offline afterwards.

Usage:
    python3 fetch_three.py
"""

import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / 'viewer-output'

# Pinned to r149 — last release with a working UMD `three.min.js` bundle.
# r150+ moved to ES modules only, which browsers refuse to load over file://.
THREE_VERSION = "0.149.0"
THREE_URL = f"https://unpkg.com/three@{THREE_VERSION}/build/three.min.js"
THREE_FILENAME = "three.min.js"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUTPUT_DIR / THREE_FILENAME
    if dest.exists():
        print(f"{dest} already exists ({dest.stat().st_size} bytes). Delete it to re-download.")
        return
    print(f"Downloading three@{THREE_VERSION} -> {dest}")
    urllib.request.urlretrieve(THREE_URL, dest)
    print(f"Saved {dest.stat().st_size} bytes.")


if __name__ == '__main__':
    main()
