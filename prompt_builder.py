"""
prompt_builder.py
Central prompt construction layer for BrandForge.
"""


def _safe_str(value, fallback=""):
    """Return a clean string value with a fallback."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _safe_list(value):
    """Normalize list-like values into a clean list of strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _style_copy_direction(style: str) -> str:
    """Return concise copy direction for each variation style."""
    style = _safe_str(style, "minimal").lower()
    directions = {
        "minimal": "Use restrained, refined language with clean premium clarity.",
        "bold": "Use assertive, high-energy language with strong momentum and confidence.",
        "editorial": "Use polished, magazine-like language with cinematic sophistication.",
    }
    return directions.get(style, directions["minimal"])


def _style_image_direction(style: str) -> str:
    """Return explicit visual direction so each variation stays visually distinct."""
    style = _safe_str(style, "minimal").lower()
    directions = {
        "minimal": "minimal architecture, clean lines, soft lighting, generous negative space, refined composition",
        "bold": "dramatic lighting, high contrast, striking luxury editorial energy, cinematic shadows, commanding composition",
        "editorial": "magazine style, artistic composition, fashion photography mood, premium aesthetic, cinematic storytelling",
    }
    return directions.get(style, directions["minimal"])


def build_campaign_prompt(user_input: str, brand_data: dict, visual_data: dict) -> dict:
    """
    Build structured prompts for copy generation and image generation.
    This module only constructs prompts and does not perform any API calls.
    """
    brand_data = brand_data or {}
    visual_data = visual_data or {}

    industry = _safe_str(brand_data.get("industry"), "general")
    tone = _safe_str(brand_data.get("tone"), "modern")
    style = _safe_str(brand_data.get("style"), "minimal")
    scene_type = _safe_str(brand_data.get("scene_type"), "brand showcase")
    colors = _safe_list(brand_data.get("colors"))

    image_prompt_base = _safe_str(
        visual_data.get("image_prompt"),
        "clean modern branding visual, premium advertisement, minimal layout",
    )
    negative_prompt = _safe_str(
        visual_data.get("negative_prompt"),
        "text, watermark, logo, blurry, low quality, distorted, deformed",
    )

    colors_text = ", ".join(colors) if colors else "not specified"
    intent_text = _safe_str(user_input, "Create a premium brand campaign.")

    copy_prompt = f"""
You are a world-class brand strategist and creative director.

Brand Context:
- Industry: {industry}
- Tone: {tone}
- Style: {style}
- Colors: {colors_text}
- Scene Type: {scene_type}

User Intent:
{intent_text}

Generate a high-converting ad campaign with:

1. Headline (premium, attention-grabbing)
2. Body Copy (clear, emotional, brand-aligned)
3. CTA (short and action-driven)

Variation Direction:
{_style_copy_direction(style)}

Make it feel like a premium brand campaign.
""".strip()

    image_prompt = f"""
{image_prompt_base}

Ad design style:
premium advertisement, minimal layout, strong typography space, clean hierarchy
Variation visual direction:
{_style_image_direction(style)}

DO NOT include text or logos in the image.
""".strip()

    return {
        "copy_prompt": copy_prompt,
        "image_prompt": image_prompt,
        "negative_prompt": negative_prompt,
    }
