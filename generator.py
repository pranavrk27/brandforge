"""
generator.py
AI copy generation plus full advertisement rendering for BrandForge.
"""

import json
import os
import random
import re
import textwrap
import time
import urllib.parse
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False


load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/auto"
POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"
FALLBACK_VISUAL_PROMPT = "minimal luxury architecture, clean modern house, cinematic lighting"
ASPECT_RATIO_MAP = {
    "1:1": (1024, 1024),
    "9:16": (1024, 1792),
    "16:9": (1792, 1024),
    "4:5": (1024, 1280),
}
STYLE_VARIATION_INDEX = {"minimal": 0, "bold": 1, "editorial": 2}
STYLE_COPY_FALLBACKS = {
    "minimal": {
        "headline": "Refined Living Starts Here",
        "body": "Clean premium storytelling for brands that value clarity and elegance.",
        "cta": "Explore More",
    },
    "bold": {
        "headline": "Make Every Impression Count",
        "body": "Confident creative that turns attention into action with striking visual energy.",
        "cta": "See The Drop",
    },
    "editorial": {
        "headline": "Crafted For The Spotlight",
        "body": "Cinematic brand moments designed to feel polished, modern, and culturally current.",
        "cta": "View Story",
    },
}
STYLE_IMAGE_MODIFIERS = {
    "minimal": "minimal architecture, clean lines, soft lighting, refined symmetry, airy premium composition",
    "bold": "dramatic lighting, high contrast, luxury editorial energy, cinematic shadows, powerful composition",
    "editorial": "magazine style, artistic composition, fashion photography mood, premium aesthetic, cinematic storytelling",
}
STYLE_IMAGE_SUBJECTS = {
    "minimal": "quiet premium scene, uncluttered environment, precise geometry",
    "bold": "heroic premium scene, commanding focal point, dramatic framing",
    "editorial": "curated premium scene, art-directed framing, expressive composition",
}


def _log_generation(style: str, event: str, detail: str = "") -> None:
    """Emit short generation logs for per-variation tracing."""
    style = _safe_str(style, "unknown").lower()
    suffix = f" | {detail}" if detail else ""
    print(f"[brandforge:{style}] {event}{suffix}")


def _get_requests():
    """Load requests lazily so missing dependencies do not crash imports."""
    try:
        import requests
        return requests
    except ImportError:
        return None


def _safe_str(value, fallback=""):
    """Normalize optional values into clean strings."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _clean_output(text: str) -> str:
    """Strip markdown fences and stray whitespace from model output."""
    cleaned = _safe_str(text)
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _load_font(font_name: str, size: int):
    """Load a font with a safe fallback."""
    font_candidates = [
        font_name,
        str(Path("C:/Windows/Fonts") / font_name),
        str(Path("C:/Windows/Fonts") / "Arial.ttf"),
        str(Path("C:/Windows/Fonts") / "arial.ttf"),
    ]

    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _style_scale(style: str) -> float:
    """Return variation-specific text scale."""
    style = _safe_str(style, "minimal").lower()
    if style == "bold":
        return 1.3
    if style == "editorial":
        return 1.1
    return 1.0


def _default_copy(style: str) -> dict:
    """Return stable style-specific copy defaults for graceful fallbacks."""
    style = _safe_str(style, "minimal").lower()
    return dict(STYLE_COPY_FALLBACKS.get(style, STYLE_COPY_FALLBACKS["minimal"]))


def _resolve_image_prompt(
    prompt_data: dict,
    headline: str,
    body: str,
    cta: str,
    style: str,
    brand_context: str,
) -> str:
    """
    Preserve upstream visual prompts when available.
    Falls back to the internal prompt builder only when the caller did not supply one.
    """
    prompt_data = prompt_data or {}
    supplied_prompt = _safe_str(prompt_data.get("image_prompt"))
    if supplied_prompt:
        return build_variation_image_prompt(supplied_prompt, style)
    return build_image_prompt(headline, body, cta, style, brand_context)


def build_variation_image_prompt(base_prompt: str, style: str) -> str:
    """Append explicit style direction so each variation gets a distinct visual brief."""
    base_prompt = _safe_str(base_prompt, FALLBACK_VISUAL_PROMPT)
    style = _safe_str(style, "minimal").lower()
    modifier = STYLE_IMAGE_MODIFIERS.get(style, STYLE_IMAGE_MODIFIERS["minimal"])
    subject = STYLE_IMAGE_SUBJECTS.get(style, STYLE_IMAGE_SUBJECTS["minimal"])
    parts = [
        base_prompt,
        f"variation style: {style}",
        modifier,
        subject,
    ]
    unique_parts = []
    seen = set()
    for part in parts:
        normalized = _safe_str(part)
        key = normalized.lower()
        if normalized and key not in seen:
            unique_parts.append(normalized)
            seen.add(key)
    return ", ".join(unique_parts)


def _style_simple_retry_prompt(style: str, brand_context: str = "") -> str:
    """Return a short style-aware fallback prompt for retry generation."""
    style = _safe_str(style, "minimal").lower()
    brand_hint = _safe_str(brand_context)
    modifier = STYLE_IMAGE_MODIFIERS.get(style, STYLE_IMAGE_MODIFIERS["minimal"])
    if brand_hint:
        return f"{brand_hint}, {modifier}"
    return build_variation_image_prompt(FALLBACK_VISUAL_PROMPT, style)


def _extract_copy_fields(campaign: dict, prompt_data: dict) -> tuple[str, str, str]:
    """Recover copy from multiple response shapes without collapsing to generic text."""
    campaign = campaign if isinstance(campaign, dict) else {}
    prompt_data = prompt_data or {}
    style = _safe_str(prompt_data.get("style"), "minimal").lower()
    fallback = _default_copy(style)

    ad_copy = campaign.get("ad_copy") if isinstance(campaign.get("ad_copy"), dict) else {}
    selected_variation = {}
    variations = campaign.get("variations")
    if isinstance(variations, list) and variations:
        preferred_index = STYLE_VARIATION_INDEX.get(style, 0)
        if preferred_index < len(variations) and isinstance(variations[preferred_index], dict):
            selected_variation = variations[preferred_index]
        else:
            selected_variation = next(
                (item for item in variations if isinstance(item, dict)),
                {},
            )

    headline = _safe_str(
        campaign.get("headline")
        or ad_copy.get("headline")
        or selected_variation.get("headline"),
        fallback["headline"],
    )[:40]
    body = _safe_str(
        campaign.get("body")
        or campaign.get("body_copy")
        or ad_copy.get("body")
        or ad_copy.get("body_copy")
        or selected_variation.get("body")
        or selected_variation.get("body_copy"),
        fallback["body"],
    )[:100]
    cta = _safe_str(
        campaign.get("cta")
        or ad_copy.get("cta")
        or selected_variation.get("cta"),
        fallback["cta"],
    )[:20]
    return headline, body, cta


def _fallback_campaign(prompt_data: dict, meta=None) -> dict:
    """Return a stable campaign object with a clean fallback image prompt."""
    prompt_data = prompt_data or {}
    style = _safe_str(prompt_data.get("style"), "minimal")
    fallback_copy = _default_copy(style)
    headline = fallback_copy["headline"]
    body = fallback_copy["body"]
    cta = fallback_copy["cta"]
    brand_context = _safe_str(prompt_data.get("brand_context"), prompt_data.get("copy_prompt"))
    image_prompt = _resolve_image_prompt(prompt_data, headline, body, cta, style, brand_context)

    return {
        "headline": headline,
        "body": body,
        "cta": cta,
        "image_prompt": image_prompt,
        "negative_prompt": _safe_str(prompt_data.get("negative_prompt")),
        "image": None,
        "meta": meta if isinstance(meta, dict) else {},
    }


def _normalize_campaign(campaign: dict, prompt_data: dict, meta=None) -> dict:
    """Enforce the clean structured output used across the app."""
    campaign = campaign if isinstance(campaign, dict) else {}
    prompt_data = prompt_data or {}

    style = _safe_str(prompt_data.get("style"), "minimal")
    headline, body, cta = _extract_copy_fields(campaign, prompt_data)
    brand_context = _safe_str(prompt_data.get("brand_context"), prompt_data.get("copy_prompt"))

    return {
        "headline": headline,
        "body": body,
        "cta": cta,
        "image_prompt": _resolve_image_prompt(prompt_data, headline, body, cta, style, brand_context),
        "negative_prompt": _safe_str(prompt_data.get("negative_prompt")),
        "image": None,
        "meta": meta if isinstance(meta, dict) else {},
    }


def build_image_prompt(headline, body, cta, style, brand_context):
    """Build the detailed ad prompt used to derive the visual background."""
    style = _safe_str(style, "minimal").lower()
    brand_context = _safe_str(brand_context, "Premium lifestyle brand campaign.")

    style_directions = {
        "minimal": STYLE_IMAGE_MODIFIERS["minimal"],
        "bold": STYLE_IMAGE_MODIFIERS["bold"],
        "editorial": STYLE_IMAGE_MODIFIERS["editorial"],
    }

    prompt = f"""
Create a high-end advertisement image.

Brand:
{brand_context}

Headline:
{headline}

Body:
{body}

CTA:
{cta}

Style:
{style} (minimal / bold / editorial)

Scene:
Use realistic, brand-relevant environment (e.g., architecture, fashion, etc.)

Design:
- Clean layout
- Professional typography
- Proper spacing
- Modern ad composition
- {style_directions.get(style, style_directions["minimal"])}

Lighting:
Cinematic, high quality

Output:
A complete, polished advertisement image ready for Instagram.
"""
    return prompt.strip()


def _build_short_visual_prompt(prompt: str) -> str:
    """Convert a long structured prompt into a short visual-only prompt."""
    prompt = _safe_str(prompt, FALLBACK_VISUAL_PROMPT)
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    selected_parts = []

    for line in lines:
        lower = line.lower()
        if lower in {"brand:", "headline:", "body:", "cta:", "style:", "scene:", "design:", "lighting:", "output:"}:
            continue
        if lower.startswith("create a high-end advertisement image"):
            continue
        if lower.startswith("use realistic"):
            continue
        if lower.startswith("a complete, polished"):
            continue
        if lower.startswith("cinematic, high quality"):
            continue
        if line.startswith("-"):
            continue
        selected_parts.append(line)

    short_prompt = ", ".join(selected_parts)
    short_prompt = re.sub(r"\b(brand|headline|body|cta|style|scene|design|lighting|output)\b:?", "", short_prompt, flags=re.IGNORECASE)
    short_prompt = re.sub(r"[^a-zA-Z0-9,\- ]+", " ", short_prompt)
    short_prompt = re.sub(r"\s+", " ", short_prompt)
    short_prompt = re.sub(r"\s*,\s*", ", ", short_prompt).strip(" ,")

    if not short_prompt:
        short_prompt = FALLBACK_VISUAL_PROMPT

    return short_prompt[:200].strip(" ,")


def _build_pollinations_url(short_prompt: str, seed: int, width: int = 1024, height: int = 1024) -> str:
    """Build a safe Pollinations URL with encoded prompt and an explicit seed."""
    clean_prompt = urllib.parse.quote(short_prompt)
    return f"{POLLINATIONS_BASE_URL}/{clean_prompt}?width={width}&height={height}&seed={seed}&model=flux"


def _request_background_image(prompt: str, style: str, seed: int, width: int = 1024, height: int = 1024):
    """Fetch one background image attempt and return the PIL image plus source URL."""
    requests = _get_requests()
    if requests is None:
        raise RuntimeError("The 'requests' package is not installed.")

    image_url = _build_pollinations_url(prompt, seed, width=width, height=height)
    print(f"[IMAGE] Generating image for style: {style}")
    print(f"[IMAGE] Prompt: {prompt}")
    response = requests.get(image_url, timeout=60)
    print(f"[IMAGE] Status Code: {response.status_code}")
    print(f"Image URL: {image_url}")

    if response.status_code != 200:
        raise RuntimeError(f"Bad response: {response.status_code}")

    return Image.open(BytesIO(response.content)).convert("RGBA"), image_url


def _create_fallback_background(width: int = 1024, height: int = 1024) -> Image.Image:
    """Create a last-resort local background if network generation fails."""
    img = Image.new("RGBA", (width, height), (30, 36, 52, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        (int(width * 0.54), int(height * 0.07), int(width * 0.96), int(height * 0.42)),
        fill=(70, 92, 180, 110),
    )
    draw.rectangle(
        (int(width * 0.09), int(height * 0.09), int(width * 0.41), int(height * 0.41)),
        outline=(255, 255, 255, 26),
        width=3,
    )
    draw.rectangle(
        (int(width * 0.61), int(height * 0.61), int(width * 0.92), int(height * 0.92)),
        outline=(255, 255, 255, 20),
        width=3,
    )
    return img


def _wrap_body(body: str, width: int = 34) -> str:
    """Wrap body copy into at most two lines."""
    wrapped = textwrap.fill(_safe_str(body), width=width)
    return "\n".join(wrapped.splitlines()[:2])


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    """Measure text width and height safely across Pillow versions."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Wrap text so each line fits within a pixel width budget."""
    words = _safe_str(text).split()
    if not words:
        return [""]

    lines = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}"
        candidate_width, _ = _text_size(draw, candidate, font)
        if candidate_width <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word
        if len(lines) == max_lines:
            break

    if len(lines) < max_lines and current:
        lines.append(current)

    lines = lines[:max_lines]
    if len(lines) == max_lines and " ".join(lines).strip() != _safe_str(text).strip():
        last_line = lines[-1]
        while last_line:
            test_line = f"{last_line.rstrip('. ')}..."
            test_width, _ = _text_size(draw, test_line, font)
            if test_width <= max_width:
                lines[-1] = test_line
                break
            last_line = " ".join(last_line.split()[:-1])
        if not lines[-1].endswith("..."):
            lines[-1] = "..."

    return lines


def _draw_line_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    position: tuple[int, int],
    font,
    fill,
    line_spacing: int,
) -> int:
    """Draw wrapped lines and return the final y-position."""
    x, y = position
    current_y = y

    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        _, line_height = _text_size(draw, line or "Ag", font)
        current_y += line_height + line_spacing

    return current_y


def _render_ad_on_image(img: Image.Image, headline: str, body: str, cta: str, style: str) -> Image.Image:
    """Overlay ad copy onto the generated background to create the final ad."""
    style = _safe_str(style, "minimal").lower()
    scale = _style_scale(style)

    headline = _safe_str(headline, "Elevate Your Space")[:40]
    body = _safe_str(body, "Premium design for modern living.")[:100]
    cta = _safe_str(cta, "Explore Now")[:20]

    img = img.resize((1024, 1024)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 120))
    img = Image.alpha_composite(img, overlay)

    bottom_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bottom_draw = ImageDraw.Draw(bottom_overlay)
    bottom_draw.rounded_rectangle(
        [(36, 580), (988, 988)],
        radius=32,
        fill=(0, 0, 0, 110),
    )
    img = Image.alpha_composite(img, bottom_overlay)

    draw = ImageDraw.Draw(img)
    title_font = _load_font("arial.ttf", int(70 * scale))
    body_font = _load_font("arial.ttf", int(35 * scale))
    cta_font = _load_font("arial.ttf", int(40 * scale))

    width, height = img.size
    content_x = 80
    max_text_width = width - 160
    headline_y = int(height * 0.63)

    headline_lines = _wrap_text_to_width(draw, headline, title_font, max_text_width, max_lines=2)
    body_lines = _wrap_text_to_width(draw, body, body_font, max_text_width, max_lines=2)

    next_y = _draw_line_block(
        draw,
        headline_lines,
        (content_x, headline_y),
        title_font,
        (255, 255, 255),
        int(8 * scale),
    )
    body_y = next_y + int(18 * scale)
    next_y = _draw_line_block(
        draw,
        body_lines,
        (content_x, body_y),
        body_font,
        (220, 220, 220),
        int(6 * scale),
    )

    cta_y = min(next_y + int(28 * scale), height - 140)
    cta_text_width, cta_text_height = _text_size(draw, cta, cta_font)
    cta_padding_x = int(28 * scale)
    cta_padding_y = int(20 * scale)
    cta_width = min(max(cta_text_width + (cta_padding_x * 2), 260), width - 160)
    cta_height = max(cta_text_height + (cta_padding_y * 2), 78)
    draw.rounded_rectangle(
        [(content_x, cta_y), (content_x + cta_width, cta_y + cta_height)],
        radius=16,
        fill=(25, 50, 148),
    )
    text_x = content_x + (cta_width - cta_text_width) / 2
    text_y = cta_y + (cta_height - cta_text_height) / 2 - 4
    draw.text((text_x, text_y), cta, font=cta_font, fill=(255, 255, 255))
    return img


def _save_rendered_ad(img: Image.Image, save_dir: str) -> str:
    """Save the rendered advertisement and return its static path."""
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    filename = f"ad_{uuid.uuid4().hex}.png"
    file_path = Path(save_dir) / filename
    img.save(file_path)
    return f"/static/generated/{filename}"


def generate_image(prompt: str, headline: str, body: str, cta: str, style: str, save_dir: str = None) -> str:
    """Generate a background with Pollinations, then render a complete ad on top."""
    save_dir = save_dir or str(Path(__file__).parent / "static" / "generated")
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    style = _safe_str(style, "minimal").lower()
    styled_prompt = build_variation_image_prompt(prompt, style)
    short_prompt = _build_short_visual_prompt(styled_prompt)
    simpler_prompt = _style_simple_retry_prompt(style, short_prompt)
    primary_seed = random.randint(1, 999999)
    retry_seed = random.randint(1, 999999)

    _log_generation(style, "image:start", f"seed={primary_seed}")

    background = None
    source_url = ""
    prompt_attempts = [
        ("primary", short_prompt, primary_seed),
        ("retry", simpler_prompt, retry_seed),
    ]

    for prompt_label, attempt_prompt, initial_seed in prompt_attempts:
        if prompt_label == "retry":
            _log_generation(style, "image:retry", f"seed={initial_seed}")

        for attempt in range(3):
            attempt_seed = initial_seed if attempt == 0 else random.randint(1, 999999)
            try:
                background, source_url = _request_background_image(attempt_prompt, style, attempt_seed)
                break
            except Exception as exc:
                error_text = str(exc)
                if "429" in error_text:
                    _log_generation(style, "image:rate-limit", f"attempt={attempt + 1}")
                    time.sleep(4)
                else:
                    _log_generation(style, "image:error", error_text)
                    time.sleep(2)

            if attempt == 2:
                _log_generation(style, "image:exhausted", prompt_label)

        if background is not None:
            break

    if background is None:
        _log_generation(style, "image:fallback")
        background = _create_fallback_background()
        source_url = "local-fallback"

    final_ad = _render_ad_on_image(background, headline, body, cta, style)
    rendered_path = _save_rendered_ad(final_ad, save_dir)
    _log_generation(style, "image:done", source_url or rendered_path)
    return rendered_path


def generate_campaign(prompt_data: dict) -> dict:
    """
    Generate structured ad copy and a full rendered advertisement image.
    Always returns a dictionary.
    """
    prompt_data = prompt_data or {}
    style = _safe_str(prompt_data.get("style"), "minimal")
    copy_prompt = _safe_str(prompt_data.get("copy_prompt"))

    if not copy_prompt:
        _log_generation(style, "campaign:fallback", "missing copy prompt")
        campaign = _fallback_campaign(
            prompt_data,
            {"error": "No copy prompt was provided."},
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    full_prompt = f"""
You are a professional ad copywriter.

Return ONLY valid JSON in this format:

{{
  "headline": "max 6 words, powerful",
  "body": "max 2 short lines, premium tone",
  "cta": "2-3 words"
}}

Rules:
- NO markdown
- NO explanation
- NO extra text
- Keep it short and clean

Brand context:
{copy_prompt}
"""

    requests = _get_requests()
    if requests is None:
        _log_generation(style, "campaign:fallback", "requests unavailable")
        campaign = _fallback_campaign(
            prompt_data,
            {"error": "The 'requests' package is not installed."},
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        _log_generation(style, "campaign:fallback", "missing api key")
        campaign = _fallback_campaign(
            prompt_data,
            {"error": "OPENROUTER_API_KEY is not set."},
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "user", "content": full_prompt}
                ],
            },
            timeout=45,
        )
    except Exception as exc:
        _log_generation(style, "campaign:fallback", "copy request failed")
        campaign = _fallback_campaign(
            prompt_data,
            {"error": str(exc)},
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    try:
        result = response.json()
    except Exception as exc:
        _log_generation(style, "campaign:fallback", "invalid copy response")
        campaign = _fallback_campaign(
            prompt_data,
            {
                "error": f"Failed to decode API response: {exc}",
                "status_code": getattr(response, "status_code", None),
            },
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    if "choices" not in result:
        _log_generation(style, "campaign:fallback", "missing choices")
        campaign = _fallback_campaign(
            prompt_data,
            {
                "status_code": getattr(response, "status_code", None),
                "result": result,
            },
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    try:
        response_text = result["choices"][0]["message"]["content"]
    except Exception as exc:
        _log_generation(style, "campaign:fallback", "bad response shape")
        campaign = _fallback_campaign(
            prompt_data,
            {
                "error": f"Invalid OpenRouter response structure: {exc}",
                "result": result,
            },
        )
        campaign["image"] = generate_image(
            campaign["image_prompt"],
            campaign["headline"],
            campaign["body"],
            campaign["cta"],
            _safe_str(prompt_data.get("style"), "minimal"),
        )
        return campaign

    response_text = _clean_output(response_text)

    try:
        campaign = json.loads(response_text)
    except Exception:
        _log_generation(style, "campaign:fallback", "non-json copy output")
        campaign = {
            "headline": "Elevate Your Space",
            "body": "Premium design for modern living.",
            "cta": "Explore Now",
        }

    normalized = _normalize_campaign(
        campaign,
        prompt_data,
        {
            "model": OPENROUTER_MODEL,
            "status_code": getattr(response, "status_code", None),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    normalized["image"] = generate_image(
        normalized["image_prompt"],
        normalized["headline"],
        normalized["body"],
        normalized["cta"],
        _safe_str(prompt_data.get("style"), "minimal"),
    )
    return normalized


def boost_creative_brief(user_input: str) -> str:
    """Backward-compatible helper that safely returns the input text."""
    return _safe_str(user_input)


def generate_quick_copy(
    brand_name: str,
    product: str,
    tone: str = "professional",
    num_options: int = 5,
) -> list:
    """Return simple short-form headlines without external calls."""
    brand_name = _safe_str(brand_name, "Your Brand")
    product = _safe_str(product, "your product")
    tone = _safe_str(tone, "professional")

    options = [
        f"{brand_name} redefines {product}",
        "Meet the smarter side",
        f"{product} with {tone} edge",
        "Premium moves begin here",
        "Design that drives action",
    ]
    return options[: max(1, min(int(num_options or 5), 10))]


def enhance_image_prompt(
    base_prompt: str,
    style: str = "photorealistic",
    aspect_ratio: str = "1:1",
) -> dict:
    """Return a stable image prompt package without external dependencies."""
    base_prompt = _safe_str(base_prompt, "clean modern branding visual")
    style = _safe_str(style, "photorealistic")
    aspect_ratio = _safe_str(aspect_ratio, "1:1")

    enhanced = f"{base_prompt}, {style}, aspect ratio {aspect_ratio}, premium commercial quality"
    return {
        "stable_diffusion": enhanced,
        "midjourney": enhanced,
        "dalle": enhanced,
        "negative_prompt": "text, watermark, logo, blurry, low quality, distorted, deformed",
    }


def _safe_hashtag(token: str) -> str:
    """Normalize free-form text into a hashtag token."""
    token = re.sub(r"[^a-zA-Z0-9]+", "", _safe_str(token))
    return f"#{token}" if token else ""


def _extract_color_palette(colors) -> list[str]:
    """Support both nested brand palettes and flat color lists."""
    if isinstance(colors, dict):
        ordered = []
        for key in ("primary", "secondary", "accent"):
            values = colors.get(key)
            if isinstance(values, list):
                ordered.extend([_safe_str(value) for value in values if _safe_str(value)])
        return ordered
    if isinstance(colors, list):
        return [_safe_str(value) for value in colors if _safe_str(value)]
    return []


def _normalize_style(style: str, industry: str = "") -> str:
    """Map arbitrary style hints into the supported premium ad aesthetics."""
    style = _safe_str(style, "").lower()
    industry = _safe_str(industry, "").lower()
    if style in {"minimal", "bold", "editorial"}:
        return style
    if industry == "fashion":
        return "editorial"
    if "bold" in style or "cinematic" in style:
        return "bold"
    return "minimal"


def _resolve_aspect_ratio(aspect_ratio: str) -> tuple[str, tuple[int, int]]:
    """Return the normalized aspect ratio key and canvas dimensions."""
    aspect_ratio = _safe_str(aspect_ratio, "1:1")
    return aspect_ratio if aspect_ratio in ASPECT_RATIO_MAP else "1:1", ASPECT_RATIO_MAP.get(aspect_ratio, ASPECT_RATIO_MAP["1:1"])


def _detect_scene(brand_description: str, industry: str = "") -> str:
    """Infer a domain-specific scene with simple keyword detection."""
    haystack = f"{_safe_str(industry)} {_safe_str(brand_description)}".lower()
    if "fashion" in haystack or "apparel" in haystack or "clothing" in haystack:
        return "fashion editorial photoshoot"
    if "architecture" in haystack or "real estate" in haystack or "villa" in haystack or "interior" in haystack:
        return "modern luxury villa exterior"
    if "fitness" in haystack or "gym" in haystack or "athletic" in haystack:
        return "athletic dynamic scene"
    if "corporate" in haystack or "business" in haystack or "office" in haystack or "saas" in haystack:
        return "premium office business setting"
    if "beauty" in haystack or "skincare" in haystack or "cosmetic" in haystack:
        return "premium skincare studio scene"
    return "premium brand lifestyle scene"


def _fallback_hashtags(brand_description: str, industry: str, style: str) -> list[str]:
    """Return 8-12 stable hashtags when the language model is unavailable."""
    tokens = [
        industry or "brand",
        style,
        "premium",
        "advertising",
        "campaign",
        "design",
        "creative",
        "branding",
        "marketing",
        "visualstorytelling",
        "socialmedia",
        "contentcreation",
    ]
    if brand_description:
        tokens.extend(re.findall(r"[A-Za-z0-9]+", brand_description)[:4])

    hashtags = []
    for token in tokens:
        hashtag = _safe_hashtag(token)
        if hashtag and hashtag.lower() not in {tag.lower() for tag in hashtags}:
            hashtags.append(hashtag)
        if len(hashtags) == 10:
            break
    return hashtags[:10]


def _limit_words(text: str, max_words: int) -> str:
    """Trim text to a maximum number of words."""
    words = _safe_str(text).split()
    return " ".join(words[:max_words]) if words else ""


def _normalize_copy_payload(payload: dict, brand_description: str, industry: str, style: str) -> dict:
    """Enforce the single-ad response contract and length rules."""
    payload = payload if isinstance(payload, dict) else {}
    fallback = _default_copy(style)
    headline = _limit_words(payload.get("headline") or fallback["headline"], 8) or fallback["headline"]
    body = _limit_words(payload.get("body") or payload.get("body_copy") or fallback["body"], 20) or fallback["body"]
    cta = _limit_words(payload.get("cta") or fallback["cta"], 3) or fallback["cta"]
    caption = _safe_str(payload.get("caption"))
    if not caption:
        caption = f"{headline}. {body} {cta}".strip()

    hashtags = payload.get("hashtags")
    if isinstance(hashtags, str):
        hashtags = re.findall(r"#\w+", hashtags)
    elif not isinstance(hashtags, list):
        hashtags = []

    normalized_hashtags = []
    for tag in hashtags:
        hashtag = _safe_hashtag(tag)
        if hashtag and hashtag.lower() not in {item.lower() for item in normalized_hashtags}:
            normalized_hashtags.append(hashtag)

    if len(normalized_hashtags) < 8:
        for tag in _fallback_hashtags(brand_description, industry, style):
            if tag.lower() not in {item.lower() for item in normalized_hashtags}:
                normalized_hashtags.append(tag)
            if len(normalized_hashtags) == 10:
                break

    return {
        "headline": headline,
        "body": body,
        "cta": cta,
        "caption": caption,
        "hashtags": normalized_hashtags[:12],
    }


def _fallback_copy_payload(brand_description: str, industry: str, style: str) -> dict:
    """Return resilient single-ad copy when the model is unavailable."""
    fallback = _default_copy(style)
    payload = {
        "headline": fallback["headline"],
        "body": fallback["body"],
        "cta": fallback["cta"],
        "caption": f"{fallback['headline']}. {fallback['body']} {fallback['cta']}.",
        "hashtags": _fallback_hashtags(brand_description, industry, style),
    }
    return _normalize_copy_payload(payload, brand_description, industry, style)


def generate_ad_copy(brand_description: str, brand_data: dict) -> dict:
    """Generate the strict single-ad copy payload."""
    brand_data = brand_data or {}
    industry = _safe_str(brand_data.get("industry"), "general").lower()
    tone = _safe_str(brand_data.get("tone"), "premium")
    style = _normalize_style(brand_data.get("style"), industry)
    requests = _get_requests()
    if requests is None:
        return _fallback_copy_payload(brand_description, industry, style)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return _fallback_copy_payload(brand_description, industry, style)

    prompt = f"""
You are a premium advertising copywriter.

Return ONLY valid JSON in this exact structure:
{{
  "headline": "...",
  "body": "...",
  "cta": "...",
  "caption": "...",
  "hashtags": ["#...", "#...", "#..."]
}}

Rules:
- Headline: max 8 words
- Body: max 20 words
- CTA: max 3 words
- Caption: Instagram-ready, premium tone
- Hashtags: 8-12 relevant tags
- No markdown
- No extra keys

Brand description:
{brand_description}

Brand data:
- Industry: {industry}
- Tone: {tone}
- Style: {style}
""".strip()

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        response.raise_for_status()
        result = response.json()
        content = _clean_output(result["choices"][0]["message"]["content"])
        payload = json.loads(content)
        return _normalize_copy_payload(payload, brand_description, industry, style)
    except Exception:
        return _fallback_copy_payload(brand_description, industry, style)


def build_structured_image_prompt(brand_description: str, brand_data: dict) -> str:
    """Build the structured, domain-aware image prompt for the single premium ad."""
    brand_data = brand_data or {}
    industry = _safe_str(brand_data.get("industry"), "general").lower()
    style = _normalize_style(brand_data.get("style"), industry)
    scene = _detect_scene(brand_description, industry)
    colors = ", ".join(_extract_color_palette(brand_data.get("colors"))) or "brand-aligned palette"
    safe_area = "LEFT safe area" if style == "bold" else "BOTTOM safe area"
    return f"""
High-end advertisement photography.

Brand context:
{_safe_str(brand_description, "Premium brand campaign")}

Visual scene:
Generate a realistic, domain-specific environment.
Scene: {scene}

Style:
{style} aesthetic

Composition:
- Clean layout
- Strong focal point
- Negative space for text ({safe_area})
- Cinematic lighting
- Premium color grading
- Subtle use of {colors}

DO NOT include text in the image.
""".strip()


def _fallback_image_prompt(brand_description: str, industry: str) -> str:
    """Return the final stock-style retry prompt."""
    scene = _detect_scene(brand_description, industry)
    return f"premium commercial photography, {scene}, clean composition, cinematic lighting, no text"


def _infer_accent_color(brand_data: dict, style: str) -> tuple[int, int, int]:
    """Resolve an accent color from brand data with sensible fallbacks."""
    palette = _extract_color_palette(brand_data.get("colors")) if isinstance(brand_data, dict) else []
    for color in palette:
        lower = color.lower()
        if lower in COLOR_FALLBACKS:
            return COLOR_FALLBACKS[lower]
        if lower.startswith("#") and len(lower) == 7:
            try:
                return tuple(int(lower[i : i + 2], 16) for i in (1, 3, 5))
            except Exception:
                continue
    if style == "bold":
        return (200, 84, 51)
    if style == "editorial":
        return (48, 48, 48)
    return (25, 50, 148)


COLOR_FALLBACKS = {
    "black": (18, 18, 18),
    "white": (245, 245, 245),
    "gold": (212, 175, 55),
    "beige": (222, 205, 168),
    "blue": (60, 120, 216),
    "red": (210, 50, 50),
    "green": (56, 142, 100),
    "orange": (236, 136, 63),
    "brown": (121, 85, 61),
    "gray": (120, 120, 120),
    "grey": (120, 120, 120),
    "silver": (192, 192, 192),
}


def generate_background_image(prompt: str, brand_description: str, brand_data: dict, aspect_ratio: str) -> tuple[Image.Image, str]:
    """Generate one background image with retries and a final safe fallback prompt."""
    brand_data = brand_data or {}
    style = _normalize_style(brand_data.get("style"), _safe_str(brand_data.get("industry")))
    normalized_ratio, (width, height) = _resolve_aspect_ratio(aspect_ratio)
    style_prompt = build_variation_image_prompt(prompt, style)
    short_prompt = _build_short_visual_prompt(style_prompt)
    fallback_prompt = _build_short_visual_prompt(
        _fallback_image_prompt(brand_description, _safe_str(brand_data.get("industry")))
    )

    attempts = [
        ("primary", short_prompt),
        ("retry", short_prompt),
        ("fallback", fallback_prompt),
    ]
    for label, attempt_prompt in attempts:
        seed = random.randint(1, 999999)
        try:
            image, url = _request_background_image(
                attempt_prompt,
                style,
                seed,
                width=width,
                height=height,
            )
            return image.resize((width, height)).convert("RGBA"), url
        except Exception as exc:
            _log_generation(style, "image:error", f"{label}:{exc}")
            time.sleep(1.5)

    return _create_fallback_background(width, height), "local-fallback"


def _measure_multiline_text(draw: ImageDraw.ImageDraw, lines: list[str], font, line_spacing: int) -> tuple[int, int]:
    """Measure a wrapped multiline block."""
    widths = []
    total_height = 0
    for index, line in enumerate(lines):
        width, height = _text_size(draw, line or "Ag", font)
        widths.append(width)
        total_height += height
        if index < len(lines) - 1:
            total_height += line_spacing
    return (max(widths) if widths else 0, total_height)


def _fit_text_group(
    draw: ImageDraw.ImageDraw,
    headline: str,
    body: str,
    cta: str,
    max_width: int,
    max_height: int,
    base_size: int,
):
    """Shrink typography until the group fits inside the designated safe area."""
    size = base_size
    while size >= 24:
        headline_font = _load_font("arial.ttf", size)
        body_font = _load_font("arial.ttf", max(int(size * 0.42), 20))
        cta_font = _load_font("arial.ttf", max(int(size * 0.34), 18))
        headline_lines = _wrap_text_to_width(draw, headline, headline_font, max_width, max_lines=3)
        body_lines = _wrap_text_to_width(draw, body, body_font, max_width, max_lines=3)
        headline_spacing = max(int(size * 0.14), 8)
        body_spacing = max(int(size * 0.12), 6)
        _, headline_height = _measure_multiline_text(draw, headline_lines, headline_font, headline_spacing)
        _, body_height = _measure_multiline_text(draw, body_lines, body_font, body_spacing)
        cta_width, cta_height = _text_size(draw, cta, cta_font)
        button_height = max(cta_height + max(int(size * 0.44), 18), 54)
        total_height = headline_height + int(size * 0.32) + body_height + int(size * 0.42) + button_height
        if total_height <= max_height:
            return {
                "headline_font": headline_font,
                "body_font": body_font,
                "cta_font": cta_font,
                "headline_lines": headline_lines,
                "body_lines": body_lines,
                "headline_spacing": headline_spacing,
                "body_spacing": body_spacing,
                "button_height": button_height,
            }
        size -= 4

    headline_font = _load_font("arial.ttf", 24)
    body_font = _load_font("arial.ttf", 18)
    cta_font = _load_font("arial.ttf", 16)
    return {
        "headline_font": headline_font,
        "body_font": body_font,
        "cta_font": cta_font,
        "headline_lines": _wrap_text_to_width(draw, headline, headline_font, max_width, max_lines=3),
        "body_lines": _wrap_text_to_width(draw, body, body_font, max_width, max_lines=3),
        "headline_spacing": 8,
        "body_spacing": 6,
        "button_height": 54,
    }


def _apply_gradient_overlay(base: Image.Image, aspect_ratio: str) -> tuple[Image.Image, dict]:
    """Create a safe text zone with a soft gradient overlay."""
    width, height = base.size
    padding = 60
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    if aspect_ratio == "16:9":
        panel_width = int(width * 0.42)
        for x in range(panel_width):
            alpha = int(205 * (1 - (x / max(panel_width - 1, 1))) + 20)
            overlay_draw.line([(x, 0), (x, height)], fill=(7, 10, 18, min(alpha, 220)))
        region = {
            "x": padding,
            "y": padding,
            "width": panel_width - (padding * 2),
            "height": height - (padding * 2),
        }
    else:
        top = int(height * 0.56 if aspect_ratio == "1:1" else height * 0.62 if aspect_ratio == "9:16" else height * 0.6)
        for y in range(top, height):
            ratio = (y - top) / max(height - top - 1, 1)
            alpha = int(220 * ratio)
            overlay_draw.line([(0, y), (width, y)], fill=(7, 10, 18, min(alpha, 220)))
        region = {
            "x": padding,
            "y": top + padding,
            "width": width - (padding * 2),
            "height": height - top - (padding * 2),
        }

    return Image.alpha_composite(base.convert("RGBA"), overlay), region


def _paste_logo(draw_base: Image.Image, logo_path: str, region: dict) -> int:
    """Paste the optional logo inside the safe region and return the consumed height."""
    if not logo_path or not os.path.exists(logo_path):
        return 0
    try:
        logo = Image.open(logo_path).convert("RGBA")
        max_width = min(int(region["width"] * 0.28), 180)
        max_height = 72
        logo.thumbnail((max_width, max_height))
        draw_base.paste(logo, (region["x"], region["y"]), logo)
        return logo.height + 20
    except Exception:
        return 0


def render_premium_ad(
    background: Image.Image,
    copy_payload: dict,
    aspect_ratio: str,
    style: str,
    accent_color: tuple[int, int, int],
    logo_path: str | None = None,
) -> Image.Image:
    """Compose the final premium advertisement image with safe text placement."""
    normalized_ratio, (width, height) = _resolve_aspect_ratio(aspect_ratio)
    base = background.resize((width, height)).convert("RGBA")
    base, region = _apply_gradient_overlay(base, normalized_ratio)
    draw = ImageDraw.Draw(base)
    logo_height = _paste_logo(base, logo_path, region)
    region["y"] += logo_height
    region["height"] = max(region["height"] - logo_height, 160)

    headline = copy_payload["headline"]
    body = copy_payload["body"]
    cta = copy_payload["cta"]
    typography = _fit_text_group(
        draw,
        headline,
        body,
        cta,
        region["width"],
        region["height"],
        base_size=max(int(min(width, height) * 0.08), 42),
    )

    current_y = region["y"]
    current_y = _draw_line_block(
        draw,
        typography["headline_lines"],
        (region["x"], current_y),
        typography["headline_font"],
        (255, 255, 255),
        typography["headline_spacing"],
    )
    current_y += 18
    current_y = _draw_line_block(
        draw,
        typography["body_lines"],
        (region["x"], current_y),
        typography["body_font"],
        (225, 225, 225),
        typography["body_spacing"],
    )
    current_y += 28

    cta_font = typography["cta_font"]
    cta_width, cta_height = _text_size(draw, cta, cta_font)
    button_padding_x = 28
    button_width = min(max(cta_width + (button_padding_x * 2), 200), region["width"])
    button_height = typography["button_height"]
    button_x = region["x"]
    button_y = min(current_y, region["y"] + region["height"] - button_height)
    draw.rounded_rectangle(
        [(button_x, button_y), (button_x + button_width, button_y + button_height)],
        radius=18,
        fill=accent_color,
    )
    text_x = button_x + (button_width - cta_width) / 2
    text_y = button_y + (button_height - cta_height) / 2 - 2
    draw.text((text_x, text_y), cta, font=cta_font, fill=(255, 255, 255))
    return base


def generate_single_premium_ad(
    brand_description: str,
    brand_data: dict | None = None,
    aspect_ratio: str = "1:1",
    logo_path: str | None = None,
) -> dict:
    """Generate one premium, production-ready ad."""
    brand_data = dict(brand_data or {})
    industry = _safe_str(brand_data.get("industry"), "general").lower()
    style = _normalize_style(brand_data.get("style"), industry)
    brand_data["style"] = style
    normalized_ratio, _ = _resolve_aspect_ratio(aspect_ratio)
    copy_payload = generate_ad_copy(brand_description, brand_data)
    image_prompt = build_structured_image_prompt(brand_description, brand_data)
    background, source_url = generate_background_image(
        image_prompt,
        brand_description,
        brand_data,
        normalized_ratio,
    )
    accent_color = _infer_accent_color(brand_data, style)
    final_ad = render_premium_ad(
        background,
        copy_payload,
        normalized_ratio,
        style,
        accent_color,
        logo_path=logo_path,
    )
    image_path = _save_rendered_ad(final_ad, str(Path(__file__).parent / "static" / "generated"))
    return {
        "image_url": image_path,
        "download_url": image_path,
        "headline": copy_payload["headline"],
        "body": copy_payload["body"],
        "cta": copy_payload["cta"],
        "caption": copy_payload["caption"],
        "hashtags": copy_payload["hashtags"],
        "style": style,
        "aspect_ratio": normalized_ratio,
        "source_image_url": source_url,
    }
