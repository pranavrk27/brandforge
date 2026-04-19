"""
main.py - FastAPI Backend for BrandForge
Integrated pipeline:
User input -> brand intelligence -> visual strategy -> prompt builder
-> generator -> Pollinations background -> PIL ad rendering -> final PNG
"""

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from brand_intelligence import analyze_brand_input
from generator import ASPECT_RATIO_MAP, generate_quick_copy, generate_single_premium_ad
from parser import extract_text_from_file, parse_brand_guidelines, rule_based_extract


app = FastAPI(
    title="BrandForge API",
    description="AI-powered ad campaign generation and rendered advertisement pipeline",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
BRAND_DIR = BASE_DIR / "brand_data"
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = STATIC_DIR / "generated"
CAMPAIGNS_DIR = BASE_DIR / "campaigns"

UPLOAD_DIR.mkdir(exist_ok=True)
BRAND_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
CAMPAIGNS_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


SUPPORTED_FORMATS = {
    "square": {"label": "Square Ad", "dimensions": "1024x1024"},
    "instagram_post": {"label": "Instagram Post", "dimensions": "1024x1024"},
}
ASPECT_RATIO_OPTIONS = {
    "1:1": {"label": "Instagram Post", "dimensions": "1024x1024"},
    "9:16": {"label": "Instagram Story", "dimensions": "1024x1792"},
    "16:9": {"label": "Landscape / LinkedIn", "dimensions": "1792x1024"},
    "4:5": {"label": "Portrait Post", "dimensions": "1024x1280"},
}

CAMPAIGN_TYPES = [
    "product_launch",
    "brand_awareness",
    "seasonal_sale",
    "event_promotion",
]

COLOR_MAP = {
    "black": (18, 18, 18),
    "white": (245, 245, 245),
    "gold": (212, 175, 55),
    "beige": (222, 205, 168),
    "blue": (60, 120, 216),
    "red": (210, 50, 50),
    "green": (56, 142, 100),
    "yellow": (240, 204, 70),
    "orange": (236, 136, 63),
    "purple": (128, 89, 191),
    "pink": (219, 112, 147),
    "brown": (121, 85, 61),
    "gray": (120, 120, 120),
    "grey": (120, 120, 120),
    "silver": (192, 192, 192),
}


class GenerateRequest(BaseModel):
    prompt: str = ""
    session_id: Optional[str] = None
    campaign_type: str = "product_launch"
    format: str = "instagram_post"
    aspect_ratio: str = "1:1"


class QuickCopyRequest(BaseModel):
    brand_name: str
    product: str
    tone: str = "professional"
    num_options: int = 5


def _safe_str(value, fallback: str = "") -> str:
    """Return a clean string fallback for optional values."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _safe_list(value) -> list[str]:
    """Normalize nested list-like values into a flat list of strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _extract_color_list(colors) -> list[str]:
    """Support both legacy list colors and parsed/manual `{primary: [...]}` payloads."""
    if isinstance(colors, dict):
        ordered = []
        for key in ("primary", "secondary", "accent"):
            ordered.extend(_safe_list(colors.get(key)))
        return ordered
    return _safe_list(colors)


def _load_session_brand_data(session_id: Optional[str]) -> dict:
    """Read stored brand data for a session when available."""
    if not session_id:
        return {}

    brand_file = BRAND_DIR / f"{session_id}.json"
    if not brand_file.exists():
        return {}

    try:
        with open(brand_file, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"Failed to load brand data for session '{session_id}': {e}")
        return {}


def _normalize_session_brand_data(session_brand_data: dict) -> dict:
    """Map uploaded/manual brand data into the lightweight generation schema."""
    session_brand_data = session_brand_data or {}
    tone_of_voice = (
        session_brand_data.get("tone_of_voice")
        if isinstance(session_brand_data.get("tone_of_voice"), dict)
        else {}
    )

    normalized = {
        "brand_name": _safe_str(session_brand_data.get("brand_name")),
        "industry": _safe_str(session_brand_data.get("industry")).lower(),
        "tone": _safe_str(
            session_brand_data.get("tone")
            or session_brand_data.get("brand_tone")
            or tone_of_voice.get("primary")
        ).lower(),
        "style": _safe_str(session_brand_data.get("style")).lower(),
        "colors": _extract_color_list(session_brand_data.get("colors")),
        "visual_style": _safe_str(session_brand_data.get("visual_style")),
        "scene_type": _safe_str(
            session_brand_data.get("scene_type")
            or session_brand_data.get("value_proposition")
        ),
        "value_proposition": _safe_str(session_brand_data.get("value_proposition")),
        "_logo_file": _safe_str(session_brand_data.get("_logo_file")),
    }

    return {key: value for key, value in normalized.items() if value}


def _build_prompt_from_brand_data(session_brand_data: dict) -> str:
    """Create a useful campaign brief when a session exists but no prompt was supplied."""
    session_brand_data = session_brand_data or {}
    tone_of_voice = (
        session_brand_data.get("tone_of_voice")
        if isinstance(session_brand_data.get("tone_of_voice"), dict)
        else {}
    )
    brand_name = _safe_str(session_brand_data.get("brand_name"), "This brand")
    value_prop = _safe_str(session_brand_data.get("value_proposition"), "premium products and services")
    tone = _safe_str(
        session_brand_data.get("tone")
        or session_brand_data.get("brand_tone")
        or tone_of_voice.get("primary"),
        "premium",
    )
    colors = _extract_color_list(session_brand_data.get("colors"))
    colors_text = ", ".join(colors) if colors else "brand-aligned colors"
    return f"{brand_name} offers {value_prop} with a {tone} tone using {colors_text}."


def _merge_brand_data(user_input: str, session_brand_data: dict) -> tuple[str, dict]:
    """Blend prompt-derived intelligence with uploaded/manual brand data."""
    normalized_session = _normalize_session_brand_data(session_brand_data)
    prompt_text = _safe_str(user_input)

    if not prompt_text and normalized_session:
        prompt_text = _build_prompt_from_brand_data(session_brand_data)

    prompt_text = _safe_str(prompt_text, "Create a premium brand campaign.")
    merged = analyze_brand_input(prompt_text)
    merged.update(normalized_session)
    return prompt_text, merged


def _find_logo_path(session_id: Optional[str]) -> Optional[str]:
    """Locate a session logo on disk if one was uploaded earlier."""
    if not session_id:
        return None

    session_dir = UPLOAD_DIR / session_id
    if not session_dir.exists():
        return None

    for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        candidate = session_dir / f"logo{ext}"
        if candidate.exists():
            return str(candidate)
    return None


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend HTML."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(
        content="<h1>BrandForge API</h1><p>Visit <a href='/docs'>/docs</a> for API docs.</p>",
        status_code=200,
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "openrouter_api_key_set": bool(os.environ.get("OPENROUTER_API_KEY")),
    }


@app.get("/formats")
async def get_formats():
    """Return supported output formats and campaign types."""
    return {
        "formats": SUPPORTED_FORMATS,
        "aspect_ratios": ASPECT_RATIO_OPTIONS,
        "campaign_types": CAMPAIGN_TYPES,
    }


@app.post("/upload-manual")
async def upload_manual_brand(
    brand_name: str = Form(...),
    brand_colors: str = Form(...),
    typography: str = Form(...),
    brand_tone: str = Form(...),
    product_or_service: str = Form(...),
    campaign_type: str = Form(...),
    format: str = Form(...),
    logo: Optional[UploadFile] = File(None),
):
    """Store manually entered brand information and an optional logo."""
    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    logo_filename = None
    if logo and logo.filename:
        ext = Path(logo.filename).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
            logo_filename = f"logo{ext}"
            file_path = session_dir / logo_filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(logo.file, f)

    brand_data = {
        "brand_name": brand_name,
        "brand_personality": [],
        "tone_of_voice": {
            "primary": brand_tone,
            "description": brand_tone,
        },
        "colors": {
            "primary": [c.strip() for c in brand_colors.split(",")] if brand_colors else [],
        },
        "typography": {
            "primary_font": typography,
        },
        "value_proposition": product_or_service,
        "_logo_file": f"/uploads/{session_id}/{logo_filename}" if logo_filename else None,
        "_is_manual": True,
    }

    brand_file = BRAND_DIR / f"{session_id}.json"
    with open(brand_file, "w", encoding="utf-8") as f:
        json.dump(brand_data, f, indent=2)

    return JSONResponse(
        content={
            "session_id": session_id,
            "brand_data": brand_data,
            "status": "manual_saved",
            "prefilled": {
                "product_or_service": product_or_service,
                "campaign_type": campaign_type,
                "format": format,
            },
        }
    )


@app.post("/upload")
async def upload_brand_guidelines(
    file: UploadFile = File(...),
    auto_parse: bool = Form(default=True),
):
    """Upload and optionally parse a brand guidelines file."""
    allowed_types = {".pdf", ".txt", ".md"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {allowed_types}",
        )

    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = f"brand_guidelines{ext}"
    file_path = session_dir / safe_filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    result = {
        "session_id": session_id,
        "filename": file.filename,
        "saved_as": safe_filename,
        "size_bytes": file_path.stat().st_size,
        "status": "uploaded",
    }

    if auto_parse:
        try:
            brand_data = parse_brand_guidelines(str(file_path))
            with open(BRAND_DIR / f"{session_id}.json", "w", encoding="utf-8") as f:
                json.dump(brand_data, f, indent=2)
            result["status"] = "parsed"
            result["brand_data"] = brand_data
            result["parse_message"] = "Brand guidelines parsed successfully."
        except Exception as e:
            try:
                raw_text = extract_text_from_file(str(file_path))
                brand_data = rule_based_extract(raw_text)
                brand_data["_parse_error"] = str(e)
                with open(BRAND_DIR / f"{session_id}.json", "w", encoding="utf-8") as f:
                    json.dump(brand_data, f, indent=2)
                result["status"] = "partially_parsed"
                result["brand_data"] = brand_data
                result["parse_message"] = f"Used fallback parser. Error: {str(e)}"
            except Exception as fallback_error:
                result["status"] = "parse_failed"
                result["parse_error"] = str(fallback_error)

    return JSONResponse(content=result)


@app.post("/parse/{session_id}")
async def parse_session(session_id: str):
    """Parse a previously uploaded guidelines file."""
    session_dir = UPLOAD_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    file_path = None
    for ext in [".pdf", ".txt", ".md"]:
        candidate = session_dir / f"brand_guidelines{ext}"
        if candidate.exists():
            file_path = candidate
            break

    if not file_path:
        raise HTTPException(status_code=404, detail="No guidelines file found for this session.")

    try:
        brand_data = parse_brand_guidelines(str(file_path))
    except Exception as e:
        raw_text = extract_text_from_file(str(file_path))
        brand_data = rule_based_extract(raw_text)
        brand_data["_parse_error"] = str(e)

    with open(BRAND_DIR / f"{session_id}.json", "w", encoding="utf-8") as f:
        json.dump(brand_data, f, indent=2)

    return {"session_id": session_id, "brand_data": brand_data}


@app.get("/brand/{session_id}")
async def get_brand_data(session_id: str):
    """Return parsed brand data for a session."""
    brand_file = BRAND_DIR / f"{session_id}.json"
    if not brand_file.exists():
        raise HTTPException(status_code=404, detail=f"No brand data for session '{session_id}'.")

    with open(brand_file, encoding="utf-8") as f:
        brand_data = json.load(f)

    return {"session_id": session_id, "brand_data": brand_data}


@app.post("/generate")
async def generate_ad_campaign(request: GenerateRequest):
    """Generate one premium advertisement and return the rendered asset plus copy."""
    session_brand_data = _load_session_brand_data(request.session_id)
    user_input, base_brand_data = _merge_brand_data(request.prompt, session_brand_data)
    aspect_ratio = request.aspect_ratio if request.aspect_ratio in ASPECT_RATIO_MAP else "1:1"
    logo_path = _find_logo_path(request.session_id)
    ad = generate_single_premium_ad(
        brand_description=user_input,
        brand_data=base_brand_data,
        aspect_ratio=aspect_ratio,
        logo_path=logo_path,
    )

    campaign_record = {
        "user_input": user_input,
        "session_id": request.session_id,
        "brand_data": base_brand_data,
        "ad": ad,
    }

    try:
        with open(CAMPAIGNS_DIR / f"{uuid.uuid4().hex}.json", "w", encoding="utf-8") as f:
            json.dump(campaign_record, f, indent=2)
    except Exception as e:
        print(f"Failed to save campaign record: {e}")

    return ad


@app.post("/quick-copy")
async def quick_copy(request: QuickCopyRequest):
    """Generate simple headline options."""
    headlines = generate_quick_copy(
        brand_name=request.brand_name,
        product=request.product,
        tone=request.tone,
        num_options=min(request.num_options, 10),
    )
    return {"headlines": headlines}


@app.get("/sessions")
async def list_sessions():
    """List all upload sessions."""
    sessions = []
    for session_dir in UPLOAD_DIR.iterdir():
        if session_dir.is_dir():
            brand_file = BRAND_DIR / f"{session_dir.name}.json"
            sessions.append(
                {
                    "session_id": session_dir.name,
                    "has_brand_data": brand_file.exists(),
                    "files": [f.name for f in session_dir.iterdir()],
                }
            )
    return {"sessions": sessions}


@app.post("/demo")
async def demo_generate(
    prompt: str = Form(default="Create a luxury modern architecture ad campaign for a premium real estate brand."),
    aspect_ratio: str = Form(default="1:1"),
):
    """Run the integrated pipeline without requiring a saved session."""
    request = GenerateRequest(prompt=prompt, aspect_ratio=aspect_ratio)
    return await generate_ad_campaign(request)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
