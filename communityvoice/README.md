# CommunityVoice 🤝
### GDG Solution Challenge 2026 — AI-powered intake assistant for nonprofits

Built with: **Gemini API** · **Firebase Firestore** · **Flask** · **Web Speech API**

---

## ⚡ Quick Start (5 minutes)

### 1. Install dependencies
```bash
cd communityvoice
pip install -r requirements.txt
```

### 2. Set your Gemini API key
Get a free key at https://aistudio.google.com/app/apikey

```bash
# Mac/Linux
export GEMINI_API_KEY="your_key_here"

# Windows (PowerShell)
$env:GEMINI_API_KEY="your_key_here"
```

### 3. Run it
```bash
python app.py
```

Then open: http://localhost:5000

---

## 🔥 Firebase Setup (optional but recommended for demo)

1. Go to https://console.firebase.google.com
2. Create a new project → Enable Firestore (test mode is fine)
3. Project Settings → Service Accounts → Generate new private key
4. Download the JSON file → rename it `serviceAccountKey.json`
5. Place it in this folder (same level as `app.py`)
6. Restart `python app.py` — it will auto-connect

Without Firebase: cases still work but are lost when you restart the server.

---

## 📱 Features

**Community Member Interface** (`/`)
- Friendly AI chat powered by Gemini 1.5 Flash
- Voice input via Web Speech API (works in Chrome)
- Quick-prompt buttons for common needs
- Auto-detects: name, need type, urgency level
- Shows confirmation when case is logged

**Staff Dashboard** (`/dashboard`)
- Real-time case list with urgency color coding
- Filter by status (New / In Progress / Resolved)
- One-click status updates
- Auto-refreshes every 30 seconds
- Summary stats at top

---

## 🏗️ Architecture

```
Community Member → index.html (voice/chat UI)
                       ↓
                  Flask /api/chat
                       ↓
               Gemini 1.5 Flash API
               (triage + extraction)
                       ↓
              Firebase Firestore (cases)
                       ↑
              Staff Dashboard /dashboard
```

---

## 📁 Project Structure

```
communityvoice/
├── app.py                 # Flask backend + Gemini + Firebase
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variable template
├── serviceAccountKey.json # Firebase credentials (you add this)
└── templates/
    ├── index.html         # Community member intake UI
    └── dashboard.html     # Staff case dashboard
```

---

## 🎬 Demo Script (for your submission video)

1. Open http://localhost:5000
2. Click "🥗 Food assistance" quick prompt
3. Have a conversation — the AI will collect name + details
4. Show the green "Case logged" confirmation
5. Switch to the Staff Dashboard tab
6. Show the new case appearing with urgency indicator
7. Click "In Progress" then "Resolved"

That's your whole demo. Keep it under 3 minutes!

---

## 🏆 Judging Criteria Coverage

| Criterion | How this project covers it |
|-----------|---------------------------|
| Impact & Value | Saves nonprofit staff hours daily; serves vulnerable community members 24/7 |
| Innovation | Voice + AI triage is new for local nonprofits; uses Gemini + Firebase together |
| Communication | Clean UI, real demo-able prototype, clear value prop |
| Feasibility | Fully working app; deployable to Google Cloud Run in minutes |

---

## 🚀 Deploy to Google Cloud Run (bonus points!)

```bash
# Build and deploy
gcloud run deploy communityvoice \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your_key_here
```

