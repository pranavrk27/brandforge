import requests
import json
import time

base_url = "http://127.0.0.1:8000"

print("1. Uploading manual brand data...")
upload_res = requests.post(
    f"{base_url}/upload-manual",
    data={
        "brand_name": "Test Brand",
        "brand_colors": "#FF0000, #00FF00",
        "typography": "Arial",
        "brand_tone": "Professional",
        "product_or_service": "Software",
        "campaign_type": "product_launch",
        "format": "instagram_post"
    }
)
print("Upload response:", upload_res.status_code)
try:
    upload_data = upload_res.json()
    print("Upload data:", upload_data)
    session_id = upload_data.get("session_id")
except Exception as e:
    print("Failed to parse upload json:", e)
    print(upload_res.text)
    exit(1)

if not session_id:
    print("No session ID returned!")
    exit(1)

print("\n2. Generating campaign...")
try:
    generate_res = requests.post(
        f"{base_url}/generate",
        json={
            "session_id": session_id,
            "campaign_type": "product_launch",
            "format": "instagram_post",
            "product_or_service": "Software"
        },
        timeout=60
    )
    print("Generate response:", generate_res.status_code)
    try:
        print("Generate data:", json.dumps(generate_res.json(), indent=2))
    except Exception as e:
        print("Failed to parse generate json:", e)
        print(generate_res.text)
except requests.exceptions.Timeout:
    print("Generate request timed out!")
except Exception as e:
    print("Generate request failed:", e)
