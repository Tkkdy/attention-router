# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Bounded monochrome title rendering for bitmap-titles-v1 devices.

Uses the host's installed Chinese font; no font file is distributed to devices.
Only pixels cross this optional scene extension. Business text is unchanged.
"""
from functools import lru_cache
from pathlib import Path
import os
import warnings

WIDTH, HEIGHT = 344, 18


@lru_cache(maxsize=1)
def title_font():
    from PIL import ImageFont
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    try:
        return ImageFont.truetype(str(path), size=16)
    except OSError:
        warnings.warn("Device title font unavailable: install Microsoft YaHei legally on Windows; using ASCII titles. Chinese display titles unavailable.", RuntimeWarning)
        return None


@lru_cache(maxsize=256)
def title_bitmap(text: str) -> str | None:
    from PIL import Image, ImageDraw
    font = title_font()
    if font is None:
        return None
    text = ' '.join(text.split())[:63]
    canvas = Image.new('1', (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(canvas)
    if draw.textlength(text, font=font) > WIDTH:
        while text and draw.textlength(text + '...', font=font) > WIDTH:
            text = text[:-1]
        text += '...'
    draw.text((0, 0), text, font=font, fill=1, anchor='lt')
    return canvas.tobytes().hex()
