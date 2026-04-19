import os
import uuid
import urllib.parse
from pathlib import Path


def _get_requests():
    try:
        import requests
        return requests
    except ImportError as exc:
        raise RuntimeError(
            "The 'requests' package is required for image generation. "
            "Install dependencies with 'pip install -r requirements.txt'."
        ) from exc


def _get_pillow_image():
    try:
        from PIL import Image
        return Image
    except ImportError as exc:
        raise RuntimeError(
            "The 'Pillow' package is required for image post-processing. "
            "Install dependencies with 'pip install -r requirements.txt'."
        ) from exc


def _safe_str(value, fallback=""):
    """Normalize optional values into clean strings."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _extract_color_list(colors) -> list[str]:
    """Support both `{primary: [...]}` and flat list color payloads."""
    if isinstance(colors, dict):
        ordered = []
        for key in ("primary", "secondary", "accent"):
            values = colors.get(key)
            if isinstance(values, list):
                ordered.extend([str(item).strip() for item in values if str(item).strip()])
        return ordered
    if isinstance(colors, list):
        return [str(item).strip() for item in colors if str(item).strip()]
    return []


def _extract_campaign_copy(campaign_data: dict) -> tuple[str, str, str]:
    """Read copy from both legacy `ad_copy` and flat response shapes."""
    campaign_data = campaign_data or {}
    ad_copy = campaign_data.get("ad_copy") if isinstance(campaign_data.get("ad_copy"), dict) else {}
    headline = _safe_str(campaign_data.get("headline") or ad_copy.get("headline"), "Elevate Your Space")
    body = _safe_str(
        campaign_data.get("body")
        or campaign_data.get("body_copy")
        or ad_copy.get("body_copy"),
        "Premium design for modern living.",
    )
    cta = _safe_str(campaign_data.get("cta") or ad_copy.get("cta"), "Explore Now")
    return headline, body, cta


def _resolve_logo_path(brand_data: dict) -> str | None:
    """Convert stored upload URLs back to local filesystem paths when needed."""
    brand_data = brand_data or {}
    logo_file = _safe_str(brand_data.get("_logo_file"))
    if not logo_file:
        return None
    if logo_file.startswith("/uploads/"):
        return str(Path(__file__).parent / "uploads" / logo_file.split("/uploads/")[1])
    return logo_file if os.path.exists(logo_file) else None


def _create_local_background(save_dir: str) -> str:
    """Create a deterministic local background so rendering never returns `None`."""
    Image = _get_pillow_image()
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    bg = Image.new("RGBA", (1024, 1024), (26, 31, 44, 255))
    for x in range(1024):
        alpha = int(85 * (x / 1024))
        for y in range(1024):
            bg.putpixel((x, y), (26 + min(alpha, 45), 31 + min(alpha, 35), 44 + min(alpha, 90), 255))

    bg_filename = f"generated_bg_fallback_{uuid.uuid4().hex}.png"
    bg_path = Path(save_dir) / bg_filename
    bg.save(bg_path)
    return str(bg_path)


def generate_ad_image(campaign_data: dict, brand_data: dict, save_dir: str) -> str:
    """
    Generates a high-quality base image via OpenAI DALL-E (or free Pollinations.ai fallback),
    applies strict programmatic layout (logo + text), saves it to save_dir, 
    and returns the file path relative to static.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    campaign_data = campaign_data or {}
    brand_data = brand_data or {}
    visual_dir = campaign_data.get("visual_direction", {}) if isinstance(campaign_data.get("visual_direction"), dict) else {}
    image_prompts = campaign_data.get("image_generation_prompt", {}) if isinstance(campaign_data.get("image_generation_prompt"), dict) else {}
    colors = _extract_color_list(brand_data.get("colors"))

    base_prompt = _safe_str(image_prompts.get("dalle") or image_prompts.get("stable_diffusion"))
    if not base_prompt:
        layout = _safe_str(visual_dir.get("layout_description"))
        imagery = _safe_str(visual_dir.get("imagery_style"))
        mood = _safe_str(visual_dir.get("mood"), "Professional")
        base_prompt = f"Professional advertising photography. {imagery}. Layout: {layout}. Mood: {mood}."

    full_prompt = (
        f"{base_prompt} "
        f"Brand colors applied subtly: {', '.join(colors) if colors else 'brand-aligned palette'}. "
        f"Mood: {_safe_str(visual_dir.get('mood'), 'Professional')}. "
        f"IMPORTANT: The image must be pure photography or illustration without ANY typography, text, letters, symbols, or logos. "
        f"DO NOT include any text. DO NOT generate logos. Focus entirely on lighting, composition, and high-end aesthetic quality."
    )

    Path(save_dir).mkdir(parents=True, exist_ok=True)
    background_path = None

    try:
        requests = _get_requests()
        if api_key:
            response = requests.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "dall-e-3",
                    "prompt": full_prompt[:4000],
                    "n": 1,
                    "size": "1024x1024",
                    "response_format": "url",
                    "quality": "hd",
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            image_url = data["data"][0]["url"]
        else:
            print("No OPENAI_API_KEY found, using free pollinations.ai API fallback.")
            encoded_prompt = urllib.parse.quote(full_prompt[:1000])
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()

        bg_filename = f"generated_bg_{uuid.uuid4().hex}.png"
        background_path = Path(save_dir) / bg_filename
        with open(background_path, "wb") as f:
            f.write(img_response.content)
    except Exception as e:
        print(f"Image generation failed: {e}")
        background_path = Path(_create_local_background(save_dir))

    try:
        from layout_engine import render_ad

        headline, body, cta = _extract_campaign_copy(campaign_data)
        style = _safe_str(campaign_data.get("style"), "minimal").lower()
        final_filename = f"final_ad_{style}_{uuid.uuid4().hex}.png"
        final_path = Path(save_dir) / final_filename
        render_ad(
            image_path=str(background_path),
            headline=headline,
            body=body,
            cta=cta,
            logo_path=_resolve_logo_path(brand_data),
            output_path=str(final_path),
        )
        return f"/static/generated/{final_filename}"
    except Exception as e:
        print(f"Post-processing failed: {e}")
        if background_path and Path(background_path).exists():
            return f"/static/generated/{Path(background_path).name}"
        return None
