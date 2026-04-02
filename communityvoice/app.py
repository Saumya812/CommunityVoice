import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ── Gemini setup ──────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ── Firebase setup ────────────────────────────────────────────────────────────
firebase_initialized = False
db = None

def init_firebase():
    global firebase_initialized, db
    if firebase_initialized:
        return True
    try:
        cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
        elif os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
        else:
            print("Firebase not configured — using in-memory fallback.")
            return False
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        firebase_initialized = True
        return True
    except Exception as e:
        print(f"Firebase init failed: {e}")
        return False

init_firebase()
memory_cases = []

SYSTEM_PROMPT = """You are CommunityVoice, a warm, empathetic intake assistant for a local nonprofit.
Your job is to help community members describe their situation and connect them with the right services.

During the conversation:
- Greet warmly and ask how you can help
- Gently collect: their first name, the type of help they need, and any urgency details
- Categories: food assistance, housing/shelter, utilities help, medical/health, job assistance, mental health, other
- Ask clarifying follow-ups naturally, never make it feel like a form
- When you have enough info (name + need + urgency), end with exactly this on its own line:

CASE_READY:{"name":"<n>","need_type":"<category>","urgency":"<low|medium|high>","summary":"<1-2 sentence summary>","follow_up_needed":<true|false>}

Urgency: high=immediate safety concern, medium=needs help in days, low=general inquiry.
Always be warm, compassionate, and human."""

sessions = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    session_id = data.get("session_id") or str(uuid.uuid4())
    user_message = data.get("message", "").strip()

    if session_id not in sessions:
        sessions[session_id] = []

    history = sessions[session_id]

    conversation = [
        {"role": "user", "parts": [SYSTEM_PROMPT]},
        {"role": "model", "parts": ["Understood. Ready to help community members with warmth and care."]}
    ]
    for turn in history:
        conversation.append({"role": turn["role"], "parts": [turn["content"]]})

    try:
        chat_session = model.start_chat(history=conversation)
        response = chat_session.send_message(user_message)
        reply_text = response.text

        case_saved = False
        case_data = None
        if "CASE_READY:" in reply_text:
            parts = reply_text.split("CASE_READY:")
            display_text = parts[0].strip()
            try:
                json_str = parts[1].strip().split("\n")[0]
                case_data = json.loads(json_str)
                case_data["session_id"] = session_id
                case_data["timestamp"] = datetime.utcnow().isoformat()
                case_data["status"] = "new"
                case_saved = save_case(case_data)
                reply_text = display_text + "\n\nI've logged your request and our team will be in touch. Is there anything else I can help clarify?"
            except Exception as e:
                print(f"Case parse error: {e}")

        history.append({"role": "user", "content": user_message})
        history.append({"role": "model", "content": reply_text})
        sessions[session_id] = history

        return jsonify({"session_id": session_id, "reply": reply_text, "case_saved": case_saved, "case_data": case_data})

    except Exception as e:
        return jsonify({"error": str(e), "session_id": session_id}), 500

@app.route("/api/cases", methods=["GET"])
def get_cases():
    try:
        if firebase_initialized and db:
            docs = db.collection("cases").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50).stream()
            cases = [{"id": doc.id, **doc.to_dict()} for doc in docs]
        else:
            cases = list(reversed(memory_cases[-50:]))
        return jsonify(cases)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<case_id>/status", methods=["PATCH"])
def update_case_status(case_id):
    data = request.json
    new_status = data.get("status")
    try:
        if firebase_initialized and db:
            db.collection("cases").document(case_id).update({"status": new_status})
        else:
            for c in memory_cases:
                if c.get("id") == case_id:
                    c["status"] = new_status
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def save_case(case_data):
    try:
        if firebase_initialized and db:
            doc_ref = db.collection("cases").document()
            doc_ref.set(case_data)
            case_data["id"] = doc_ref.id
        else:
            case_data["id"] = str(uuid.uuid4())
            memory_cases.append(case_data)
        return True
    except Exception as e:
        print(f"Save case error: {e}")
        return False

if __name__ == "__main__":
    app.run(debug=True, port=5000)
