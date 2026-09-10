#!/usr/bin/env python3
"""Generate high-resolution 1024x1024 icon for ableton-agent."""

import math
from PIL import Image, ImageDraw, ImageFilter

def create_icon(output_path, size=1024):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background squircle (macOS Big Sur+ style rounded rect)
    pad = int(size * 0.08)
    radius = int(size * 0.22)
    rect = [pad, pad, size - pad, size - pad]

    # Create dark gradient background
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)

    # Draw smooth gradient inside squircle
    bg_draw.rounded_rectangle(rect, radius=radius, fill=(12, 17, 29, 255), outline=(0, 242, 254, 180), width=int(size * 0.012))

    # Glow effect
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle(rect, radius=radius, fill=(0, 242, 254, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(int(size * 0.04)))
    img.paste(glow, (0, 0), glow)
    img.paste(bg, (0, 0), bg)

    # Inner elements:
    # 1. Neon Sound Waves / AI Synth lines (top half)
    cx, cy = size // 2, size // 2
    wave_y = int(size * 0.38)
    bars = 17
    bar_width = int(size * 0.022)
    bar_gap = int(size * 0.018)
    total_w = bars * bar_width + (bars - 1) * bar_gap
    start_x = (size - total_w) // 2

    for i in range(bars):
        # Symmetrical waveform heights
        dist = abs(i - bars // 2) / (bars // 2)
        h = int((size * 0.22) * (1.0 - 0.7 * (dist ** 1.5)))
        bx = start_x + i * (bar_width + bar_gap)
        by1 = wave_y - h // 2
        by2 = wave_y + h // 2

        # Gradient color: cyan to magenta
        t = i / (bars - 1)
        r = int(0 * (1 - t) + 255 * t)
        g = int(242 * (1 - t) + 0 * t)
        b = int(254 * (1 - t) + 180 * t)

        draw.rounded_rectangle([bx, by1, bx + bar_width, by2], radius=bar_width // 2, fill=(r, g, b, 240))

    # 2. Stylized Piano Keys (bottom half)
    piano_w = int(size * 0.64)
    piano_h = int(size * 0.26)
    px = (size - piano_w) // 2
    py = int(size * 0.54)

    # Base piano bed
    draw.rounded_rectangle([px - 10, py - 10, px + piano_w + 10, py + piano_h + 10], radius=16, fill=(20, 26, 42, 255), outline=(255, 255, 255, 40), width=4)

    # White keys
    white_keys = 8
    wk_width = piano_w // white_keys
    for i in range(white_keys):
        kx = px + i * wk_width
        draw.rounded_rectangle([kx + 2, py, kx + wk_width - 2, py + piano_h], radius=8, fill=(245, 247, 250, 255))
        # Add subtle shadow to white keys
        draw.rounded_rectangle([kx + 4, py + piano_h - 16, kx + wk_width - 4, py + piano_h - 4], radius=4, fill=(200, 205, 215, 255))

    # Black keys (at indices 0, 1, 3, 4, 5)
    bk_width = int(wk_width * 0.6)
    bk_height = int(piano_h * 0.62)
    black_indices = [0, 1, 3, 4, 5]
    for idx in black_indices:
        bk_x = px + (idx + 1) * wk_width - bk_width // 2
        draw.rounded_rectangle([bk_x, py, bk_x + bk_width, py + bk_height], radius=6, fill=(18, 22, 34, 255), outline=(0, 242, 254, 160), width=2)

    # 3. Ambient AI spark / badge on top right
    spark_cx, spark_cy = int(size * 0.76), int(size * 0.24)
    draw.ellipse([spark_cx - 24, spark_cy - 24, spark_cx + 24, spark_cy + 24], fill=(0, 242, 254, 255))
    # Sparkle rays
    for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
        rad = math.radians(angle)
        dx1, dy1 = math.cos(rad) * 32, math.sin(rad) * 32
        dx2, dy2 = math.cos(rad) * 52, math.sin(rad) * 52
        draw.line([spark_cx + dx1, spark_cy + dy1, spark_cx + dx2, spark_cy + dy2], fill=(0, 242, 254, 200), width=5)

    img.save(output_path, "PNG")
    print("Icon generated successfully at: %s" % output_path)

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "icon.png"
    create_icon(out)
