# Fonts

This directory contains bundled fonts for receipt generation.

## Required Fonts
- `DejaVuSansMono.ttf` - Monospace font for receipt body
- `DejaVuSansMono-Bold.ttf` - Bold variant for headers/titles

## Download

The DejaVu fonts are free and open-source. Download them from:
https://dejavu-fonts.github.io/

Or install via package manager:
- Ubuntu/Debian: `sudo apt install fonts-dejavu-core`
- macOS: `brew install dejavu-fonts`

After downloading, place the `.ttf` files in this directory.

## Fallback

If fonts are not found, the system will fall back to PIL's default bitmap font,
which may produce lower quality output but keeps the receipt functional.
