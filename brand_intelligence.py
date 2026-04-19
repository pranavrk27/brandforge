"""
brand_intelligence.py
Rule-based brand intelligence layer for BrandForge.
"""

import re


INDUSTRY_KEYWORDS = {
    "architecture": ["architecture", "construction", "building", "interior", "real estate"],
    "fashion": ["clothing", "apparel", "luxury wear", "outfit", "model"],
    "tech": ["ai", "software", "app", "saas", "platform"],
    "food": ["restaurant", "cafe", "food", "beverage"],
}

TONE_KEYWORDS = {
    "luxury": ["premium", "high-end", "elegant"],
    "modern": ["clean", "minimal", "sleek"],
    "bold": ["powerful", "strong", "aggressive"],
    "playful": ["fun", "vibrant"],
}

STYLE_KEYWORDS = {
    "minimal": ["minimal"],
    "futuristic": ["futuristic"],
    "editorial": ["editorial"],
    "corporate": ["corporate"],
    "cinematic": ["cinematic"],
}

COLOR_KEYWORDS = [
    "black",
    "white",
    "gold",
    "beige",
    "blue",
    "red",
    "green",
    "yellow",
    "orange",
    "purple",
    "pink",
    "brown",
    "gray",
    "grey",
    "silver",
]

VISUAL_STYLE_BY_INDUSTRY = {
    "architecture": "luxury modern architecture, glass buildings, clean geometry",
    "fashion": "editorial fashion shoot, model, studio lighting",
    "tech": "futuristic UI, glowing elements, abstract tech background",
    "food": "high-quality food photography, close-up, soft lighting",
    "general": "clean modern branding visual",
}

SCENE_TYPE_BY_INDUSTRY = {
    "architecture": "luxury house exterior",
    "fashion": "model showcase",
    "tech": "product interface",
    "food": "food close-up",
    "general": "brand showcase",
}


def _normalize_text(user_input: str) -> str:
    """Lowercase and normalize spacing for simple keyword matching."""
    return re.sub(r"\s+", " ", user_input.strip().lower())


def _contains_keyword(text: str, keyword: str) -> bool:
    """
    Match whole words when possible.
    Multi-word phrases are matched directly as substrings.
    """
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _detect_from_keywords(text: str, mapping: dict, fallback: str) -> str:
    """Return the first matching label from a keyword mapping."""
    for label, keywords in mapping.items():
        for keyword in keywords:
            if _contains_keyword(text, keyword):
                return label
    return fallback


def _extract_colors(text: str) -> list:
    """Collect unique color hints in the order they appear in COLOR_KEYWORDS."""
    colors = []
    for color in COLOR_KEYWORDS:
        if _contains_keyword(text, color):
            colors.append(color)
    return colors


def analyze_brand_input(user_input: str) -> dict:
    """
    Convert raw brand input into a structured intelligence object.
    This is a simple rule-based v1 system.
    """
    text = _normalize_text(user_input or "")

    industry = _detect_from_keywords(text, INDUSTRY_KEYWORDS, "general")
    tone = _detect_from_keywords(text, TONE_KEYWORDS, "modern")
    style = _detect_from_keywords(text, STYLE_KEYWORDS, "minimal")
    colors = _extract_colors(text)

    visual_style = VISUAL_STYLE_BY_INDUSTRY.get(industry, VISUAL_STYLE_BY_INDUSTRY["general"])
    scene_type = SCENE_TYPE_BY_INDUSTRY.get(industry, SCENE_TYPE_BY_INDUSTRY["general"])

    return {
        "industry": industry,
        "tone": tone,
        "style": style,
        "colors": colors,
        "visual_style": visual_style,
        "scene_type": scene_type,
    }
