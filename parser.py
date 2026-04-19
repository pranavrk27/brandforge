"""
parser.py - Brand Guidelines Extractor
Extracts structured brand data from PDF/text files using PyMuPDF + Claude AI
"""

import os
import json
import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# PDF / Text Extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file_path: str) -> str:
    """Extract raw text from a PDF file using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to read PDF brand guideline files. "
            "Install dependencies with 'pip install -r requirements.txt'."
        ) from exc

    doc = fitz.open(file_path)
    pages_text = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pages_text.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages_text)


def extract_text_from_file(file_path: str) -> str:
    """Extract text from PDF or plain-text file."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".txt", ".md"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ---------------------------------------------------------------------------
# Claude-Powered Brand Parser
# ---------------------------------------------------------------------------

BRAND_EXTRACTION_PROMPT = """
You are an expert brand analyst. Analyze the following brand guidelines document and extract structured brand data.

Return ONLY a valid JSON object (no markdown, no explanation) with exactly this structure:

{
  "brand_name": "string - the brand name",
  "tagline": "string - brand tagline or slogan if present",
  "brand_personality": ["list", "of", "personality", "traits"],
  "tone_of_voice": {
    "primary": "string - main tone (e.g., professional, playful, bold)",
    "description": "string - detailed tone description",
    "words_to_use": ["list", "of", "recommended", "words"],
    "words_to_avoid": ["list", "of", "words", "to", "avoid"]
  },
  "colors": {
    "primary": ["#HEX or color name"],
    "secondary": ["#HEX or color name"],
    "accent": ["#HEX or color name"],
    "background": ["#HEX or color name"],
    "text": ["#HEX or color name"]
  },
  "typography": {
    "primary_font": "string - main font family",
    "secondary_font": "string - secondary font family",
    "heading_style": "string - style guidelines for headings",
    "body_style": "string - style guidelines for body text"
  },
  "logo_usage": {
    "clear_space": "string - spacing rules",
    "backgrounds": "string - approved backgrounds",
    "prohibited": ["list", "of", "prohibited", "uses"],
    "minimum_size": "string - minimum size rule"
  },
  "target_audience": {
    "demographics": "string - age, location, etc.",
    "psychographics": "string - interests, values, lifestyle",
    "pain_points": ["list", "of", "audience", "pain", "points"]
  },
  "value_proposition": "string - core brand value proposition",
  "industry": "string - industry or sector",
  "competitors": ["list", "of", "competitor", "brands", "if", "mentioned"],
  "visual_style": {
    "photography_style": "string - photography guidelines",
    "illustration_style": "string - illustration style if applicable",
    "overall_aesthetic": "string - overall visual aesthetic description"
  }
}

If any field is not mentioned in the document, use null or an empty array [].

BRAND GUIDELINES DOCUMENT:
---
{document_text}
---
"""


def parse_brand_guidelines(file_path: str) -> dict:
    """
    Parse brand guidelines from a file and return structured JSON.
    Uses Claude AI to intelligently extract brand data.
    """
    # Extract raw text
    raw_text = extract_text_from_file(file_path)
    
    if not raw_text.strip():
        raise ValueError("Document appears to be empty or could not be read.")
    
    # Truncate if too long (preserve first + last portions)
    max_chars = 12000
    if len(raw_text) > max_chars:
        half = max_chars // 2
        raw_text = raw_text[:half] + "\n...[content truncated]...\n" + raw_text[-half:]
    
    # Call Claude API
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required for AI-based brand parsing. "
            "Install dependencies with 'pip install -r requirements.txt'."
        ) from exc

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    prompt = BRAND_EXTRACTION_PROMPT.format(document_text=raw_text)
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    response_text = message.content[0].text.strip()
    
    # Clean up response (remove markdown code fences if present)
    response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)
    
    brand_data = json.loads(response_text)
    brand_data["_raw_text_length"] = len(raw_text)
    brand_data["_source_file"] = Path(file_path).name
    
    return brand_data


# ---------------------------------------------------------------------------
# Fallback: Rule-based extractor (used if Claude call fails)
# ---------------------------------------------------------------------------

def rule_based_extract(text: str) -> dict:
    """Simple regex-based fallback extractor."""
    hex_colors = re.findall(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b", text)
    unique_colors = list(dict.fromkeys(hex_colors))

    font_matches = re.findall(
        r"\b(Helvetica|Arial|Futura|Gotham|Gill Sans|Garamond|Roboto|"
        r"Open Sans|Lato|Montserrat|Playfair Display|Georgia|Times New Roman)\b",
        text, re.IGNORECASE
    )
    fonts = list(dict.fromkeys(font_matches))

    return {
        "brand_name": "Unknown Brand",
        "tagline": None,
        "brand_personality": [],
        "tone_of_voice": {
            "primary": "professional",
            "description": "Extracted from document",
            "words_to_use": [],
            "words_to_avoid": []
        },
        "colors": {
            "primary": unique_colors[:2] if unique_colors else ["#000000"],
            "secondary": unique_colors[2:4] if len(unique_colors) > 2 else ["#FFFFFF"],
            "accent": unique_colors[4:5] if len(unique_colors) > 4 else [],
            "background": [],
            "text": []
        },
        "typography": {
            "primary_font": fonts[0] if fonts else "Helvetica",
            "secondary_font": fonts[1] if len(fonts) > 1 else None,
            "heading_style": None,
            "body_style": None
        },
        "logo_usage": {"clear_space": None, "backgrounds": None, "prohibited": [], "minimum_size": None},
        "target_audience": {"demographics": None, "psychographics": None, "pain_points": []},
        "value_proposition": None,
        "industry": None,
        "competitors": [],
        "visual_style": {"photography_style": None, "illustration_style": None, "overall_aesthetic": None},
        "_fallback": True
    }
