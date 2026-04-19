"""
layout_engine.py
Deterministic ad layout engine for BrandForge.
"""

import os
import textwrap

from PIL import Image, ImageDraw, ImageFont


def _load_font(font_name: str, size: int):
    """Load a font with a safe fallback."""
    try:
        return ImageFont.truetype(font_name, size)
    except Exception:
        return ImageFont.load_default()


def _detect_style(image_path: str, output_path: str) -> str:
    """Infer the variation style from the known file naming convention."""
    haystack = f"{image_path} {output_path}".lower()
    if "bold" in haystack:
        return "bold"
    if "editorial" in haystack:
        return "editorial"
    return "minimal"


def _style_scale(style: str) -> float:
    """Return the typography scale for each variation style."""
    if style == "bold":
        return 1.3
    if style == "editorial":
        return 1.1
    return 1.0


def _wrap_text(text: str, width: int) -> str:
    """Wrap text to a predictable number of characters."""
    text = str(text or "").strip()
    if not text:
        return ""
    return textwrap.fill(text, width=width)


def render_ad(
    image_path: str,
    headline: str,
    body: str,
    cta: str,
    logo_path: str = None,
    output_path: str = "output.png"
) -> str:
    """
    Render a premium ad with fixed positioning and strict text limits.
    """
    style = _detect_style(image_path, output_path)
    font_scale = _style_scale(style)

    headline = str(headline or "")[:40]
    body = str(body or "")[:100]
    cta = str(cta or "")[:20]

    img = Image.open(image_path).convert("RGBA")
    img = img.resize((1024, 1024))

    # Create a subtle bottom overlay for stronger readability.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 360, 1024, 1024), fill=(0, 0, 0, 118))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    headline_font = _load_font("arial.ttf", int(52 * font_scale))
    body_font = _load_font("arial.ttf", int(28 * font_scale))
    cta_font = _load_font("arial.ttf", int(26 * font_scale))

    wrapped_headline = _wrap_text(headline, width=15)
    wrapped_body = _wrap_text(body, width=28)
    body_lines = wrapped_body.splitlines()[:2]
    wrapped_body = "\n".join(body_lines)

    # Optional logo in the top-left corner.
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo = logo.resize((140, 140))
            img.paste(logo, (60, 60), logo)
        except Exception:
            pass

    draw = ImageDraw.Draw(img)

    # Fixed layout coordinates for consistent premium output.
    draw.text((60, 450), wrapped_headline, font=headline_font, fill="white", spacing=6)
    draw.text((60, 520), wrapped_body, font=body_font, fill=(255, 255, 255, 200), spacing=6)

    button_left = 60
    button_top = 600
    button_right = 260
    button_bottom = 660
    draw.rounded_rectangle((button_left, button_top, button_right, button_bottom), radius=12, fill="#193294")
    draw.text((80, 615), cta, font=cta_font, fill="white")

    img.save(output_path)
    return output_path
