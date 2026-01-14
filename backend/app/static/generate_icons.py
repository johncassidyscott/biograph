#!/usr/bin/env python3
"""
Generate PWA icons from SVG source.

Requirements:
    pip install pillow cairosvg

Usage:
    python generate_icons.py
"""

import os
import sys

try:
    import cairosvg
    from PIL import Image
    import io
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("\nPlease install required packages:")
    print("  pip install pillow cairosvg")
    print("\nAlternatively, you can:")
    print("  1. Use an online converter: https://cloudconvert.com/svg-to-png")
    print("  2. Upload icon.svg and convert to 192x192 and 512x512 PNG")
    print("  3. Save as icon-192.png and icon-512.png in this directory")
    sys.exit(1)

def generate_png_icon(svg_path, output_path, size):
    """Convert SVG to PNG at specified size."""
    try:
        # Convert SVG to PNG bytes
        png_data = cairosvg.svg2png(
            url=svg_path,
            output_width=size,
            output_height=size
        )

        # Save PNG file
        with open(output_path, 'wb') as f:
            f.write(png_data)

        print(f"✓ Generated {output_path} ({size}x{size})")
        return True
    except Exception as e:
        print(f"✗ Failed to generate {output_path}: {e}")
        return False

def main():
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    svg_path = os.path.join(script_dir, 'icon.svg')

    if not os.path.exists(svg_path):
        print(f"Error: {svg_path} not found")
        sys.exit(1)

    print("Generating PWA icons from icon.svg...")
    print("=" * 50)

    # Generate required icon sizes
    sizes = [
        (192, 'icon-192.png'),
        (512, 'icon-512.png'),
    ]

    success_count = 0
    for size, filename in sizes:
        output_path = os.path.join(script_dir, filename)
        if generate_png_icon(svg_path, output_path, size):
            success_count += 1

    print("=" * 50)
    print(f"Generated {success_count}/{len(sizes)} icons successfully")

    if success_count == len(sizes):
        print("\n✓ All icons generated! Your PWA is ready.")
        print("  Deploy to Render and users can 'Add to Home Screen'")
    else:
        print("\n⚠ Some icons failed. See instructions above for alternatives.")

if __name__ == '__main__':
    main()
