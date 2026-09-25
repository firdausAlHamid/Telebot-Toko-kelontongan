"""
download_fonts.py -- Download bundled fonts for receipt generation
=================================================================
Run this to download monospace fonts if they don't exist locally.
Uses IBM Plex Mono (open source, OFL) from google/fonts.
"""

import os
import urllib.request

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONTS = {
    "IBMPlexMono-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Bold.ttf",
    # Legacy DejaVu names kept for backward compat - map to Plex if missing
    "DejaVuSansMono.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    "DejaVuSansMono-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Bold.ttf",
}


def main():
    os.makedirs(FONTS_DIR, exist_ok=True)

    for filename, url in FONTS.items():
        filepath = os.path.join(FONTS_DIR, filename)

        if os.path.exists(filepath):
            print(f"[INFO] {filename} already exists, skipping...")
            continue

        print(f"[DOWNLOAD] Downloading {filename}...")
        try:
            urllib.request.urlretrieve(url, filepath)
            print(f"[OK] {filename} saved to {filepath}")
        except Exception as e:
            print(f"[ERROR] Failed to download {filename}: {e}")

    print("\n[OK] Font setup complete!")


if __name__ == "__main__":
    main()
