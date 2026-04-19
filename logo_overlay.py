from PIL import Image
import os
from pathlib import Path

def apply_logo_overlay(base_img: Image.Image, logo_path: str, position: str = "top_center") -> Image.Image:
    """
    Overlays a logo onto a base image deterministically.
    
    Args:
        base_img: The base background image (PIL Image).
        logo_path: Path to the logo image file.
        position: 'top_center', 'top_left', 'top_right', or 'bottom_center'.
        
    Returns:
        The modified base image with the logo overlaid.
    """
    if not logo_path or not os.path.exists(logo_path):
        print(f"Logo not found at {logo_path}")
        return base_img

    try:
        base_img = base_img.convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        
        base_w, base_h = base_img.size
        logo_w, logo_h = logo.size
        
        # Determine maximum logo dimensions (e.g., max 30% width, 15% height)
        max_logo_w = int(base_w * 0.3)
        max_logo_h = int(base_h * 0.15)
        
        # Calculate resize ratio to fit within constraints while maintaining aspect ratio
        ratio_w = max_logo_w / logo_w
        ratio_h = max_logo_h / logo_h
        ratio = min(ratio_w, ratio_h)
        
        new_w = int(logo_w * ratio)
        new_h = int(logo_h * ratio)
        
        # Resize logo smoothly
        logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        # Determine placement
        padding_y = int(base_h * 0.05)
        padding_x = int(base_w * 0.05)
        
        if position == "top_left":
            x = padding_x
            y = padding_y
        elif position == "top_right":
            x = base_w - new_w - padding_x
            y = padding_y
        elif position == "bottom_center":
            x = (base_w - new_w) // 2
            y = base_h - new_h - padding_y
        else: # top_center
            x = (base_w - new_w) // 2
            y = padding_y
            
        # Create an empty overlay and paste logo
        overlay = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
        overlay.paste(logo, (x, y), mask=logo) # Use logo itself as mask for transparency
        
        # Composite
        final_img = Image.alpha_composite(base_img, overlay)
        return final_img
        
    except Exception as e:
        print(f"Error applying logo overlay: {e}")
        return base_img
