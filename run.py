#!/usr/bin/env python3
"""
run.py — CommunityVoice launcher
Run this instead of app.py: python run.py
"""
import os
import sys
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"

if env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=True, encoding="utf-8-sig")
        print(f"✅ Loaded .env")
    except ImportError:
        # Manual fallback if python-dotenv not installed
        content = env_path.read_text(encoding="utf-8-sig")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'").strip()
            if key:
                os.environ[key] = val
        print(f"✅ Loaded .env (manual parser)")
else:
    print(f"⚠  No .env file found. Create one with GEMINI_API_KEY=your_key")

# ── Validate ───────────────────────────────────────────────────────────────────
print("\n── Config check ──────────────────────────────────────────────────────")

PLACEHOLDERS = {"", "your_key_here", "YOUR_GEMINI_API_KEY_HERE"}
key = os.environ.get("GEMINI_API_KEY", "").strip()

if key and key not in PLACEHOLDERS:
    masked = key[:6] + "…" + key[-4:]
    print(f"✅ GEMINI_API_KEY ({masked})")
else:
    print("❌ GEMINI_API_KEY is missing or still a placeholder!")
    print("\n   Fix:")
    print("   1. Create a file called .env in this folder")
    print("   2. Add this line:  GEMINI_API_KEY=your_actual_key_here")
    print("   3. Get a free key: https://aistudio.google.com/app/apikey")

fb_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
fb_file = Path(__file__).parent / "serviceAccountKey.json"
if fb_json and fb_json not in ("{}", ""):
    print("✅ Firebase credentials (env var)")
elif fb_file.exists() and fb_file.stat().st_size > 10:
    print("✅ Firebase serviceAccountKey.json found")
else:
    print("⚠  Firebase not configured — in-memory storage (cases lost on restart)")

print("──────────────────────────────────────────────────────────────────────")

# ── Run ────────────────────────────────────────────────────────────────────────
from app import app

port  = int(os.environ.get("PORT", 5000))
debug = True

print(f"\n🚀 CommunityVoice → http://127.0.0.1:{port}")
print(f"   Staff portal  → http://127.0.0.1:{port}/staff/login")
print(f"   Resources     → http://127.0.0.1:{port}/resources")
print(f"\n   Username: staff  |  Password: communityvoice2026\n")

app.run(debug=debug, host="0.0.0.0", port=port, use_reloader=debug)