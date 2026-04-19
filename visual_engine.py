"""
visual_engine.py
Builds a visual generation strategy from structured brand intelligence.
"""


def _safe_str(value, fallback=""):
    """Return a clean string fallback for optional values."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _safe_list(value):
    """Return a normalized list for optional sequence inputs."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _get_tone_modifiers(tone: str) -> str:
    """Map tone to visual mood and lighting modifiers."""
    tone_map = {
        "luxury": "premium, high-end, elegant lighting, refined composition",
        "modern": "clean, minimal, sharp lighting",
        "bold": "dramatic lighting, strong contrast",
        "playful": "vibrant colors, dynamic composition",
    }
    return tone_map.get(tone, tone_map["modern"])


def _get_industry_boost(industry: str) -> str:
    """Add industry-specific visual direction to improve image prompts."""
    boost_map = {
        "architecture": "wide angle lens, exterior realism, architectural photography, glass and concrete materials",
        "fashion": "editorial fashion shoot, model presence, studio lighting, magazine-quality styling",
        "tech": "futuristic UI, glow effects, sleek surfaces, abstract tech environment",
        "food": "close-up shot, shallow depth of field, food photography, soft natural lighting",
    }
    return boost_map.get(industry, "clean branding visual, polished commercial photography")


def _get_scene_details(industry: str, scene_type: str) -> str:
    """Build the main subject description with a sensible fallback."""
    base_scene = scene_type or "brand showcase"

    if industry == "architecture":
        return f"ultra realistic {base_scene}, luxury modern house exterior"
    if industry == "fashion":
        return f"ultra realistic {base_scene}, editorial model showcase"
    if industry == "tech":
        return f"ultra realistic {base_scene}, futuristic product interface"
    if industry == "food":
        return f"ultra realistic {base_scene}, premium food close-up"
    return f"ultra realistic {base_scene}, clean modern branding visual"


def build_visual_strategy(brand_data: dict) -> dict:
    """
    Convert brand intelligence into a visual generation strategy.
    This function only builds prompts and does not generate images.
    """
    brand_data = brand_data or {}

    industry = _safe_str(brand_data.get("industry"), "general").lower()
    tone = _safe_str(brand_data.get("tone"), "modern").lower()
    style = _safe_str(brand_data.get("style"), "minimal").lower()
    visual_style = _safe_str(brand_data.get("visual_style"), "clean modern branding visual")
    scene_type = _safe_str(brand_data.get("scene_type"), "brand showcase")
    colors = _safe_list(brand_data.get("colors"))

    scene = _get_scene_details(industry, scene_type)
    tone_modifiers = _get_tone_modifiers(tone)
    industry_boost = _get_industry_boost(industry)
    composition = "center composition, balanced layout, subject focus"

    # Add color guidance only when color hints are available.
    color_hint = f"brand colors: {', '.join(colors)}" if colors else "harmonious brand color palette"

    final_prompt = (
        f"{scene}, {visual_style}, {style} style, {tone_modifiers}, "
        f"{industry_boost}, {color_hint}, {composition}, cinematic shadows, "
        f"ultra realistic, premium aesthetic, 8k"
    )

    negative_prompt = "text, watermark, logo, blurry, low quality, distorted, deformed"

    return {
        "image_prompt": final_prompt,
        "negative_prompt": negative_prompt,
    }
