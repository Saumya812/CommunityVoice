# CommunityVoice 🤝
### GDG Solution Challenge 2026 — Top 10 North America Finalist
### AI-powered nonprofit intake and resource resolution platform

Built with: **Gemini 2.5 Flash** · **Firebase Firestore** · **Google Cloud Run** · **Flask** · **Web Speech API**

🔗 **Live Demo:** https://tinyurl.com/communityvoice2026  
👤 **Staff Login:** `staff` / `communityvoice2026`

---

## 🔴 The Problem

Every day, millions of people reach out to local nonprofits in crisis — needing food, shelter, utility help, or mental health support. What they find is a system that was never built for them.

- **1.9 million nonprofits** in the US still running on phone calls and paper forms
- **$3.5 trillion sector** largely untouched by AI
- Staff spend **23 minutes per intake case** — 8 hours of paperwork per day for a food bank doing 20 intakes
- **75% of nonprofits** report persistent staff vacancies
- **95% of nonprofit leaders** cite staff burnout as a top concern
- Non-English speakers — often the most marginalized — face near-complete exclusion from underfunded systems
- No help available at 2am when someone is in crisis

## ✅ The Solution: CommunityVoice

CommunityVoice is a **Gemini-powered agentic AI intake platform** that removes every point of friction from nonprofit intake — the first point of contact — with a warm, intelligent, multilingual conversation available **24/7 on any device**.

The key word is **agentic** — the AI doesn't just answer questions, it takes actions: reserves resources, updates inventory, flags crises, generates referrals, and coordinates with partner organizations.

### How it works:
1. A community member visits the site and begins a chat or voice conversation **in their own language**
2. **Gemini 2.5 Flash** guides them naturally through intake — capturing name, need type, and urgency — no forms, no hold music, no phone trees
3. The AI checks live Firebase inventory and **autonomously allocates resources** — reserving food bags, booking counseling slots, issuing utility vouchers
4. A structured case record is **auto-generated and saved to Firebase Firestore** in real time
5. Staff log into a **protected dashboard** and see a fully triaged, AI-annotated caseload — ready to act on
6. Crisis cases are **never auto-resolved** — immediately escalated to human staff with 988/911 resources shown

### By the numbers:
- Reduces average intake time: **23 minutes → 90 seconds (93% faster)**
- Supports **5 languages** end-to-end: English, Spanish, French, Chinese, Arabic
- Available **24/7** — no office hours needed
- **Cross-NGO Resource Network** — if one org runs out, partner organizations automatically fulfill the gap
- Pilot partner: **Shriver PeaceWorker Program, UMBC — Summer 2026**

---

## 🧠 Google Technology — 4 Gemini Use Cases

| Use Case | Model | What it does |
|---|---|---|
| **Conversational Intake** | gemini-2.5-flash | Warm empathetic intake in 5 languages — extracts name, need type, urgency naturally |
| **Autonomous Resource Allocation** | gemini-2.5-flash | Reads live Firebase inventory, reserves bags, books appointments, issues vouchers |
| **AI Quality Layer** | gemini-2.5-flash | Every response safety-checked before reaching a vulnerable person — checks for medical advice, cold tone, PII requests |
| **Analytics Insight** | gemini-2.5-flash | Turns case data into plain-language recommendations for nonprofit leadership |

**Also using:** Firebase Firestore · Google Cloud Run · Cloud Build · Web Speech API · Google Fonts · Google Secret Manager

---

## ⚡ Quick Start (5 minutes)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
Create a `.env` file:
```
GEMINI_API_KEY=your_gemini_key_here
GROQ_API_KEY=your_groq_key_here
MAPS_API_KEY=your_maps_key_here
FIREBASE_CREDENTIALS=serviceAccountKey.json
```

Get a free Gemini key at https://aistudio.google.com/app/apikey

### 3. Run
```bash
python run.py
```

Open: **http://localhost:5000**  
Staff portal: **http://localhost:5000/staff/login**  
Username: `staff` · Password: `communityvoice2026`

---

## 🔥 Firebase Setup (recommended)

1. Go to https://console.firebase.google.com
2. Create a project → Enable Firestore (test mode)
3. Project Settings → Service Accounts → **Generate new private key**
4. Rename to `serviceAccountKey.json`, place in project root
5. Restart `python run.py` — auto-connects

> **Without Firebase:** cases still work but are lost when the server restarts.

---

## 📱 Features

### Community Member Interface (`/chat`)
- Warm conversational AI intake powered by Gemini 2.5 Flash
- Voice input via Web Speech API (Chrome/Edge)
- **No login, no forms** — just describe your situation
- Auto-detects: name, need type, urgency level
- Multilingual: English, Spanish, French, Chinese, Arabic
- Auto-resolves cases with real resource allocation
- Thumbs up/down feedback — flags unhelpful responses for staff review
- Crisis detection — 988, Crisis Text Line, 911 surfaced immediately
- PII masking — SSN, card numbers, DOB never stored

### Staff Dashboard (`/dashboard`)
- Real-time case list with urgency color-coding
- Filter by: All, New, In Progress, Resolved, ✦ Auto-Resolved, ⚡ High Urgency, 🆘 Crisis, 👎 Needs Review
- One-click status updates and staff notes
- Human takeover for flagged cases
- Auto-refreshes in real time

### Resource Manager (`/resources`)
- Add quantity resources, appointments, vouchers, custom resources
- Low stock alerts with visual indicators
- Restock inventory, add appointment slots
- **Live Google Maps** — resource locations as colored pins
- Allocation history — every auto-resolve logged

### Analytics (`/analytics`)
- Gemini-powered AI insight and recommendations
- Need-type breakdown, urgency distribution
- Languages served, daily volume trends
- Auto-resolved rate tracking

### Cross-NGO Resource Network (`/network`)
- Partner organizations sharing resources across the network
- Automatic split fulfillment when local inventory is insufficient
- Live fulfillment log from Firebase
- Baltimore Food Bank, Shriver PeaceWorker Program, Maryland Legal Aid seeded as partners

### Impact Dashboard (`/impact`)
- Real-time hours saved calculation
- Cases resolved, languages served, crisis interventions
- Pilot partnership status

---

## 🏗️ Architecture

```
Community Member → / (landing page)
                       ↓
                  /chat (voice/chat UI)
                       ↓
                  Flask /api/chat
                       ↓
         Gemini 2.5 Flash (conversational intake)
                       ↓
         AI Quality Layer (safety check)
                       ↓
         Gemini 2.5 Flash (resource allocation)
                       ↓
         Cross-NGO Network (if local inventory low)
                       ↓
         Firebase Firestore (case + allocation storage)
                       ↑
    Staff → /dashboard  /analytics  /resources  /network  /impact
```

**AI Fallback Chain:**
```
gemini-2.5-flash → gemini-2.5-flash-lite → groq llama-3.3-70b
```

---

## 🚀 Deploy to Google Cloud Run

```bash
gcloud run deploy communityvoice \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GEMINI_API_KEY=your_key,GROQ_API_KEY=your_groq_key"

# Set Firebase via Secret Manager (recommended)
gcloud secrets create firebase-credentials --data-file="./serviceAccountKey.json"
gcloud run services update communityvoice \
  --region us-central1 \
  --set-secrets="FIREBASE_CREDENTIALS_JSON=firebase-credentials:latest"
```

---

## 📁 Project Structure

```
communityvoice/
├── app.py                  # Flask backend + Gemini + Firebase + Cross-NGO
├── run.py                  # Dev launcher with config validation
├── requirements.txt        # Python dependencies
├── Dockerfile              # Cloud Run deployment
├── serviceAccountKey.json  # Firebase credentials (not committed)
├── .env                    # Environment variables (not committed)
└── templates/
    ├── landing.html        # Public landing page (/)
    ├── index.html          # Community member intake chat (/chat)
    ├── login.html          # Staff authentication
    ├── dashboard.html      # Case management dashboard
    ├── analytics.html      # Gemini-powered analytics
    ├── resources.html      # Resource manager + Google Maps
    ├── impact.html         # Impact metrics
    └── network.html        # Cross-NGO resource network
```

---

## 🏆 SDG Alignment

| Goal | How |
|---|---|
| **SDG 1 — No Poverty** | Connects people to financial assistance and utility support instantly |
| **SDG 2 — Zero Hunger** | Food assistance allocated automatically, Cross-NGO network fills gaps |
| **SDG 3 — Good Health** | Mental health appointments booked, crisis resources surfaced immediately |
| **SDG 10 — Reduced Inequalities** | 5 languages, voice input, 24/7 availability removes access barriers |
| **SDG 17 — Partnerships** | Cross-NGO network enables organizations to collaborate on fulfillment |

---

## 🎬 Demo

**Live:** https://tinyurl.com/communityvoice2026  
**Demo video:** [GDG Solution Challenge 2026 Submission]

*GDG Solution Challenge 2026 — Top 10 North America Finalist*  
