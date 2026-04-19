import requests
import json
import time

url = "http://127.0.0.1:8000/demo"
response = requests.post(url, data={
    "campaign_type": "product_launch",
    "format": "instagram_post",
    "brand_name": "Lumina",
    "industry": "sustainable beauty",
    "product_or_service": "Radiance Serum"
})

campaign = response.json().get("campaign")

if not campaign:
    print("Demo failed to return campaign data")
    exit(1)

# Now mock a brand data file
brand_data = {
    "brand_name": "Lumina",
    "colors": {
        "primary": ["#2D6A4F"]
    },
    "_logo_file": None  # No logo for test
}

import os
from pathlib import Path

# Write mock brand data to brand_data dir
session_id = "test_session_123"
brand_file = Path("brand_data") / f"{session_id}.json"
brand_file.parent.mkdir(exist_ok=True)
with open(brand_file, "w") as f:
    json.dump(brand_data, f)

generate_url = "http://127.0.0.1:8000/generate"
print("Triggering /generate endpoint...")
response = requests.post(generate_url, json={
    "session_id": session_id,
    "campaign_type": "product_launch",
    "format": "instagram_post",
    "product_or_service": "Radiance Serum"
})

if response.status_code == 200:
    print("Success!")
    print(json.dumps(response.json(), indent=2))
else:
    print(f"Failed with {response.status_code}: {response.text}")
