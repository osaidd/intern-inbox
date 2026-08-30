"""Generate docs/social-card.png (1280x640) for link-preview cards: an
app-shell-dark background, title + one-paste command on the left, a framed
crop of the ATS grouped view on the right. Frame source dir is argv[1] so
this stays runnable whenever the demo frames are re-recorded.

Usage: uv run --with pillow python automation/social_card.py <frames_dir>
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
SYSTEM_FONTS = Path("/System/Library/Fonts")
CMD = "curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh"
W, H = 1280, 640
INK, TEXT, CHIP = (240, 239, 236), (198, 197, 193), (27, 27, 30)


def load_font(primary: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    for candidate, idx in ((primary, index), (SYSTEM_FONTS / "SFNS.ttf", 0)):
        try:
            return ImageFont.truetype(str(candidate), size, index=idx)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def hairline(bg: tuple, opacity: float = 0.18) -> tuple:
    """App-shell '--line-strong' equivalent: white at `opacity` over bg."""
    return tuple(round(c * (1 - opacity) + 255 * opacity) for c in bg)


def main(frames_dir: Path) -> None:
    frame01 = sorted(frames_dir.glob("01-*.png"))[0]
    frame07 = sorted(frames_dir.glob("07-*.png"))[0]
    bg = Image.open(frame01).convert("RGB").getpixel((2, 2))

    card = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(card)
    margin = 64

    draw.text((margin, 180), "Intern Inbox",
              font=load_font(SYSTEM_FONTS / "Helvetica.ttc", 66, index=1), fill=INK)
    draw.text((margin, 272), "NYC/NJ internships, triaged on your laptop",
              font=load_font(SYSTEM_FONTS / "Helvetica.ttc", 27), fill=TEXT)

    size, max_w = 20, 616 - margin - 24
    mono = load_font(SYSTEM_FONTS / "Menlo.ttc", size)
    while mono.getlength(CMD) > max_w and size > 10:
        size -= 1
        mono = load_font(SYSTEM_FONTS / "Menlo.ttc", size)
    top = 470
    chip = (margin, top, margin + int(mono.getlength(CMD)) + 24, top + size + 24)
    draw.rectangle(chip, fill=CHIP)
    draw.text((margin + 12, top + 12), CMD, font=mono, fill=INK)

    shot = Image.open(frame07).convert("RGB")
    shot = shot.crop((0, 0, int(shot.width * 0.82), int(shot.height * 0.95)))
    box = 560
    scale = min(box / shot.width, box / shot.height)
    shot = shot.resize((round(shot.width * scale), round(shot.height * scale)))
    ox, oy = 660 + (box - shot.width) // 2, (H - shot.height) // 2
    card.paste(shot, (ox, oy))
    draw.rectangle((ox - 1, oy - 1, ox + shot.width, oy + shot.height), outline=hairline(bg), width=1)

    out = REPO / "docs" / "social-card.png"
    card.save(out)
    print(f"wrote {out} ({out.stat().st_size} bytes, {card.size})")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
