# helpers/thumb.py — Alexa jaisa player card (blur bg + cover + progress bar)
import asyncio
import hashlib
import io
import os
from typing import Optional

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

W, H = 1280, 720
_FONT_PATHS = [
    "assets/font.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def _font(size: int):
    for p in _FONT_PATHS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


async def _download(url: str) -> Optional[Image.Image]:
    if not url:
        return None
    try:
        if os.path.isfile(url):
            return Image.open(url).convert("RGB")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return None
                data = await r.read()
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _star(d, cx, cy, r, fill):
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=fill)


def _render(cover: Optional[Image.Image], title: str, artist: str, played: int, total: int, paused: bool) -> Image.Image:
    if cover is None:
        cover = Image.new("RGB", (600, 600), (30, 30, 36))
        ImageDraw.Draw(cover).ellipse((150, 150, 450, 450), outline=(90, 90, 110), width=14)
    # background
    bg = cover.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.55).convert("RGBA")

    # glass panel
    px0, py0, px1, py1 = 190, 150, 1090, 570
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((px0, py0, px1, py1), 36, fill=(20, 20, 24, 140), outline=(255, 255, 255, 40), width=2)
    bg = Image.alpha_composite(bg, panel)
    d = ImageDraw.Draw(bg)

    # cover (square, rounded)
    size = 190
    c = cover.copy()
    s = min(c.size)
    c = c.crop(((c.width - s) // 2, (c.height - s) // 2, (c.width - s) // 2 + s, (c.height - s) // 2 + s)).resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), 26, fill=255)
    bg.paste(c, (px0 + 40, py0 + 40), mask)

    tx = px0 + 40 + size + 36
    max_w = px1 - tx - 40
    d.text((tx, py0 + 62), _fit(d, title, _font(46), max_w), font=_font(46), fill=(255, 255, 255))
    d.text((tx, py0 + 130), _fit(d, artist, _font(30), max_w), font=_font(30), fill=(200, 200, 205))

    # progress
    bx0, bx1, by = px0 + 50, px1 - 50, py0 + 290
    d.rounded_rectangle((bx0, by, bx1, by + 8), 4, fill=(255, 255, 255, 70))
    frac = (played / total) if total else 0
    frac = min(max(frac, 0), 1)
    d.rounded_rectangle((bx0, by, bx0 + max(int((bx1 - bx0) * frac), 8), by + 8), 4, fill=(255, 255, 255))
    d.ellipse((bx0 + (bx1 - bx0) * frac - 9, by - 5, bx0 + (bx1 - bx0) * frac + 9, by + 13), fill=(255, 255, 255))
    f = _font(24)
    from helpers.fonts import fmt_time
    d.text((bx0, by + 24), fmt_time(played), font=f, fill=(210, 210, 215))
    tt = fmt_time(total) if total else "LIVE"
    d.text((bx1 - d.textlength(tt, font=f), by + 24), tt, font=f, fill=(210, 210, 215))

    # controls
    cy = py0 + 365
    mid = (px0 + px1) // 2
    white = (255, 255, 255)
    _star(d, px0 + 90, cy, 20, (200, 200, 205))
    for off in (-8, 14):  # prev
        x = mid - 120 + off
        d.polygon([(x, cy), (x + 22, cy - 18), (x + 22, cy + 18)], fill=white)
    if paused:
        d.polygon([(mid - 16, cy - 28), (mid - 16, cy + 28), (mid + 28, cy)], fill=white)
    else:
        d.rounded_rectangle((mid - 22, cy - 28, mid - 8, cy + 28), 4, fill=white)
        d.rounded_rectangle((mid + 8, cy - 28, mid + 22, cy + 28), 4, fill=white)
    for off in (-14, 8):  # next
        x = mid + 120 + off
        d.polygon([(x, cy - 18), (x, cy + 18), (x + 22, cy)], fill=white)
    return bg.convert("RGB")


async def make_card(thumb_url: str, title: str, artist: str, played: int, total: int, paused: bool = False) -> Optional[str]:
    """Card banake file path return karta hai (fail hone par None)."""
    try:
        cover = await _download(thumb_url)
        img = await asyncio.to_thread(_render, cover, title, artist or "Unknown artist", played, total, paused)
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        name = hashlib.md5(f"{thumb_url}{title}{played}{paused}".encode()).hexdigest()[:16]
        path = os.path.join(config.CACHE_DIR, f"{name}.jpg")
        await asyncio.to_thread(img.save, path, "JPEG", quality=90)
        return path
    except Exception as e:
        print(f"thumb error: {e}")
        return None
