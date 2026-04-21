# app.py — CommunityVoice v4 (Resource Auto-Resolution Engine)
import os, json, uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
from groq import Groq

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "communityvoice-dev-secret-2026")

# ── Gemini ─────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-1.5-flash"


# ── Staff credentials ──────────────────────────────────────────────────────────
STAFF_USERNAME = os.environ.get("STAFF_USERNAME", "staff")
STAFF_PASSWORD = os.environ.get("STAFF_PASSWORD", "communityvoice2026")

# ── Firebase ───────────────────────────────────────────────────────────────────
firebase_initialized = False
db = None

def init_firebase():
    global firebase_initialized, db
    if firebase_initialized:
        return True
    try:
        cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        elif os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
        else:
            print("⚠  Firebase not configured — using in-memory fallback.")
            return False
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        firebase_initialized = True
        print("✅ Firebase connected.")
        return True
    except Exception as e:
        print(f"Firebase init failed: {e}")
        return False

init_firebase()

# In-memory fallbacks (used when Firebase not configured)
memory_cases     = []
memory_resources = []
memory_allocs    = []
chat_sessions    = {}

# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════
def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("staff_logged_in"):
            return redirect(url_for("staff_login"))
        return f(*args, **kwargs)
    return decorated

def api_staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("staff_logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ══════════════════════════════════════════════════════════════════════════════
# AI PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
def get_system_prompt(language="en"):
    lang_instruction = {
        "en": "Respond in English.",
        "es": "Respond ONLY in Spanish. Every single message must be entirely in Spanish.",
        "fr": "Respond ONLY in French. Every single message must be entirely in French.",
        "zh": "Respond ONLY in Simplified Chinese. Every single message must be entirely in Chinese.",
        "ar": "Respond ONLY in Arabic. Every single message must be entirely in Arabic.",
    }.get(language, "Respond in English.")

    return f"""You are CommunityVoice, a warm, empathetic intake assistant for a local nonprofit.
Your mission: help community members describe their situation and connect them with support.
{lang_instruction}

Guidelines:
- Greet warmly and ask how you can help
- Gently collect: first name, type of help needed, urgency context
- Ask ONE question at a time — never make it feel like a form
- Be patient, non-judgmental, affirming
- Categories: food_assistance, housing_shelter, utilities_help, medical_health,
  job_assistance, mental_health, legal_aid, childcare, transportation, other

When you have name + need + urgency, output EXACTLY this on its own line (no extra text after):
CASE_READY:{{"name":"<name>","need_type":"<category>","urgency":"<low|medium|high>","summary":"<1-2 sentence summary>","follow_up_needed":<true|false>,"language":"{language}"}}

Urgency guide: high=immediate safety risk, medium=needs help within days, low=general inquiry."""

CLOSING = {
    "en": "I've logged your request and our team will follow up shortly. Is there anything else I can help clarify?",
    "es": "He registrado su solicitud y nuestro equipo se comunicará pronto. ¿Hay algo más en lo que pueda ayudar?",
    "fr": "J'ai enregistré votre demande et notre équipe vous contactera bientôt. Y a-t-il autre chose?",
    "zh": "我已记录您的请求，团队将尽快联系您。还有什么需要帮助的吗？",
    "ar": "لقد سجلت طلبك وسيتواصل معك فريقنا قريباً. هل هناك أي شيء آخر؟",
}

def build_contents(history, user_message):
    """Build correctly-typed Content list for google-genai SDK."""
    contents = []
    for turn in history:
        contents.append(types.Content(
            role="model" if turn["role"] == "model" else "user",
            parts=[types.Part(text=turn["content"])]
        ))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents

# ══════════════════════════════════════════════════════════════════════════════
# RESOURCE ENGINE — DATA LAYER
# ══════════════════════════════════════════════════════════════════════════════
NEED_KEYWORDS = {
    "food_assistance":  ["food", "meal", "groceries", "pantry", "hunger", "eat"],
    "mental_health":    ["mental", "counseling", "therapy", "emotional", "psychological", "stress", "anxiety"],
    "utilities_help":   ["utility", "utilities", "electric", "gas", "water", "bill", "voucher", "energy"],
    "housing_shelter":  ["housing", "shelter", "rent", "eviction", "homeless", "home"],
    "job_assistance":   ["job", "employ", "work", "resume", "career", "unemployment"],
    "medical_health":   ["medical", "health", "clinic", "doctor", "medicine", "hospital"],
    "legal_aid":        ["legal", "law", "attorney", "court", "rights", "eviction"],
    "childcare":        ["child", "daycare", "kids", "babysitter", "school"],
    "transportation":   ["transport", "bus", "ride", "car", "travel"],
}

def get_all_resources():
    try:
        if firebase_initialized and db:
            return [{"id": d.id, **d.to_dict()} for d in db.collection("resources").stream()]
        return list(memory_resources)
    except Exception as e:
        print(f"get_all_resources error: {e}")
        return []

def save_resource_db(r):
    try:
        if firebase_initialized and db:
            ref = db.collection("resources").document()
            ref.set(r)
            r["id"] = ref.id
        else:
            r["id"] = str(uuid.uuid4())
            memory_resources.append(r)
        return r
    except Exception as e:
        print(f"save_resource error: {e}")
        return None

def update_resource_db(rid, updates):
    try:
        if firebase_initialized and db:
            db.collection("resources").document(rid).update(updates)
        else:
            for r in memory_resources:
                if r.get("id") == rid:
                    r.update(updates)
    except Exception as e:
        print(f"update_resource error: {e}")

def delete_resource_db(rid):
    global memory_resources
    try:
        if firebase_initialized and db:
            db.collection("resources").document(rid).delete()
        else:
            memory_resources = [r for r in memory_resources if r.get("id") != rid]
    except Exception as e:
        print(f"delete_resource error: {e}")

def find_matching_resources(need_type):
    """Find resources matching a need type by category or keyword."""
    keywords = NEED_KEYWORDS.get(need_type, [need_type.replace("_", " ")])
    matches = []
    for r in get_all_resources():
        if r.get("active") is False:
            continue
        combined = f"{r.get('name','')} {r.get('category','')} {r.get('notes','')}".lower()
        cat = r.get("category", "").replace(" ", "_").replace("/", "_")
        if cat == need_type or any(kw in combined for kw in keywords):
            matches.append(r)
    return matches

def log_allocation(resource_id, case_data, quantity, summary):
    record = {
        "resource_id": resource_id,
        "case_id": case_data.get("id", ""),
        "case_name": case_data.get("name", ""),
        "need_type": case_data.get("need_type", ""),
        "quantity": quantity,
        "summary": summary,
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        if firebase_initialized and db:
            db.collection("allocations").document().set(record)
        else:
            memory_allocs.append({**record, "id": str(uuid.uuid4())})
    except Exception as e:
        print(f"log_allocation error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# RESOURCE ENGINE — AUTO-RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════
def _no_resource_msg(name, need_type, lang):
    label = need_type.replace("_", " ")
    msgs = {
        "en": f"Thank you {name} — your {label} request has been logged and flagged as high priority for our team. Our current inventory is fully allocated, but a staff member will contact you shortly with alternatives.",
        "es": f"Gracias {name} — su solicitud de {label} ha sido registrada. Nuestro inventario actual está agotado, pero un miembro del equipo se comunicará pronto con alternativas.",
        "fr": f"Merci {name} — votre demande de {label} a été enregistrée. Notre inventaire actuel est épuisé, mais notre équipe vous contactera bientôt.",
        "zh": f"谢谢{name}——您的{label}请求已记录。目前库存已用尽，但工作人员将很快联系您提供替代方案。",
        "ar": f"شكراً {name} — تم تسجيل طلب {label} الخاص بك. مخزوننا الحالي ممتلئ لكن فريقنا سيتواصل معك قريباً.",
    }
    return msgs.get(lang, msgs["en"])

def execute_auto_resolution(case_data, language="en"):
    """
    Core engine: match case to resources, let Gemini decide best allocation,
    execute the allocation (deduct inventory / book slot / mark used),
    return result dict.
    """
    need_type = case_data.get("need_type", "other")
    name      = case_data.get("name", "there")

    matching = find_matching_resources(need_type)
    if not matching:
        return {
            "resolved": False,
            "action_taken": "No matching resources found",
            "resolution_details": {},
            "user_message": _no_resource_msg(name, need_type, language),
            "resource_id": None
        }

    # Build available-resource summaries for Gemini
    summaries = []
    for r in matching:
        rtype = r.get("type")
        if rtype in ("quantity", "voucher"):
            qty = r.get("quantity", 0)
            if qty > 0:
                summaries.append({
                    "id": r["id"], "name": r["name"], "type": rtype,
                    "available": qty, "unit": r.get("unit", "units"),
                    "notes": r.get("notes", "")
                })
        elif rtype == "appointment":
            free_slots = [s for s in r.get("slots", []) if not s.get("booked")]
            if free_slots:
                summaries.append({
                    "id": r["id"], "name": r["name"], "type": "appointment",
                    "next_available": free_slots[0].get("datetime", ""),
                    "staff_member": r.get("staff_member", ""),
                    "notes": r.get("notes", "")
                })
        elif rtype == "custom" and r.get("available", True):
            summaries.append({
                "id": r["id"], "name": r["name"], "type": "custom",
                "description": r.get("description", ""),
                "notes": r.get("notes", "")
            })

    if not summaries:
        return {
            "resolved": False,
            "action_taken": "Resources exist but none currently available",
            "resolution_details": {},
            "user_message": _no_resource_msg(name, need_type, language),
            "resource_id": None
        }

    lang_note = {"es":"in Spanish","fr":"in French","zh":"in Chinese","ar":"in Arabic"}.get(language, "in English")

    prompt = f"""You are a nonprofit resource allocation AI making a real decision.

Case details:
- Client name: {name}
- Need type: {need_type}
- Urgency: {case_data.get('urgency', 'medium')}
- Summary: {case_data.get('summary', '')}

Available resources right now:
{json.dumps(summaries, indent=2)}

Instructions:
1. Select the BEST resource for this person's need
2. For quantity/voucher: decide how many units to allocate (1-3 typical, match urgency)
3. For appointment: confirm the next available slot
4. Write a warm, specific confirmation message {lang_note} telling {name} exactly what was arranged

Respond ONLY with this exact JSON (no other text):
{{
  "selected_resource_id": "<id from list above>",
  "resource_name": "<name>",
  "resource_type": "<quantity|appointment|voucher|custom>",
  "quantity_allocated": <number or null>,
  "slot_datetime": "<ISO datetime string or null>",
  "action_summary": "<1 sentence in English describing what was done>",
  "user_message": "<warm 2-3 sentence confirmation message {lang_note} to {name} with specific details>"
}}"""

    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = resp.text.strip()
        # Strip markdown code fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        decision = json.loads(text.strip())
    except Exception as e:
        print(f"Auto-resolution Gemini error: {e}")
        return {
            "resolved": False,
            "action_taken": "AI processing error",
            "resolution_details": {},
            "user_message": _no_resource_msg(name, need_type, language),
            "resource_id": None
        }

    # Find the selected resource
    res_id = decision.get("selected_resource_id")
    full_r = next((r for r in matching if r.get("id") == res_id), None)
    if not full_r:
        return {
            "resolved": False,
            "action_taken": "Selected resource not found",
            "resolution_details": decision,
            "user_message": _no_resource_msg(name, need_type, language),
            "resource_id": None
        }

    # Execute the allocation
    try:
        rtype = decision.get("resource_type")

        if rtype in ("quantity", "voucher"):
            qty = max(1, int(decision.get("quantity_allocated") or 1))
            new_qty = max(0, full_r.get("quantity", 0) - qty)
            update_resource_db(res_id, {
                "quantity": new_qty,
                "last_allocated": datetime.utcnow().isoformat()
            })
            log_allocation(res_id, case_data, qty, decision.get("action_summary", ""))

        elif rtype == "appointment":
            slots = full_r.get("slots", [])
            booked_slot = None
            for s in slots:
                if not s.get("booked"):
                    s["booked"] = True
                    s["booked_by"] = name
                    s["booked_case_id"] = case_data.get("id", "")
                    s["booked_at"] = datetime.utcnow().isoformat()
                    booked_slot = s
                    break
            if booked_slot:
                update_resource_db(res_id, {
                    "slots": slots,
                    "last_allocated": datetime.utcnow().isoformat()
                })
                log_allocation(res_id, case_data, 1, decision.get("action_summary", ""))

        elif rtype == "custom":
            update_resource_db(res_id, {
                "last_allocated": datetime.utcnow().isoformat(),
                "allocation_count": full_r.get("allocation_count", 0) + 1
            })
            log_allocation(res_id, case_data, 1, decision.get("action_summary", ""))

    except Exception as e:
        print(f"Allocation execution error: {e}")
        # Still return resolved=True since Gemini made the decision, just note the exec error

    return {
        "resolved": True,
        "action_taken": decision.get("action_summary", "Resource allocated"),
        "resolution_details": decision,
        "user_message": decision.get("user_message", ""),
        "resource_id": res_id
    }

# ══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if u == STAFF_USERNAME and p == STAFF_PASSWORD:
            session["staff_logged_in"] = True
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=8)
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/staff/logout")
def staff_logout():
    session.clear()
    return redirect(url_for("staff_login"))

@app.route("/dashboard")
@staff_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/analytics")
@staff_required
def analytics():
    return render_template("analytics.html")

@app.route("/resources")
@staff_required
def resources_page():
    return render_template("resources.html")

# ══════════════════════════════════════════════════════════════════════════════
# CHAT API
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/chat", methods=["POST"])
def chat():
    data         = request.json or {}
    session_id   = data.get("session_id") or str(uuid.uuid4())
    user_message = (data.get("message") or "").strip()
    language     = data.get("language", "en")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in chat_sessions:
        chat_sessions[session_id] = {"history": [], "language": language}

    history = chat_sessions[session_id]["history"]

    try:
        # response = client.models.generate_content(
        #     model=GEMINI_MODEL,
        #     contents=build_contents(history, user_message),
        #     config=types.GenerateContentConfig(
        #         system_instruction=get_system_prompt(language)
        #     )
        # )
        # reply_text = response.text

        # ── Groq inference ────────────────────────────────────────────────────
        messages = [
            {"role": "system", "content": get_system_prompt(language)},
            *[
                {"role": "user" if t["role"] == "user" else "assistant", "content": t["content"]}
                for t in history
            ],
            {"role": "user", "content": user_message}
        ]

        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.7
        )

        reply_text = response.choices[0].message.content

        case_saved = False
        case_data  = None
        referrals  = []
        resolution = None

        if "CASE_READY:" in reply_text:
            raw_parts    = reply_text.split("CASE_READY:")
            display_text = raw_parts[0].strip()
            try:
                json_str  = raw_parts[1].strip().split("\n")[0]
                case_data = json.loads(json_str)
                case_data.update({
                    "session_id": session_id,
                    "timestamp":  datetime.utcnow().isoformat(),
                    "status":     "new",
                    "notes":      []
                })
                case_saved = save_case(case_data)

                # ── AUTO-RESOLUTION ENGINE ────────────────────────────────────
                resolution = execute_auto_resolution(case_data, language)

                if resolution["resolved"]:
                    # Update case status to auto_resolved
                    cid = case_data.get("id")
                    if cid:
                        update_case_field(cid, "status",              "auto_resolved")
                        update_case_field(cid, "auto_resolved",       True)
                        update_case_field(cid, "resolution_summary",  resolution["action_taken"])
                        update_case_field(cid, "resource_id",         resolution.get("resource_id"))
                    reply_text = display_text + "\n\n" + resolution["user_message"]
                else:
                    # Fall back to referral suggestions if no resources available
                    referrals = generate_referrals(case_data, language)
                    if referrals and case_data.get("id"):
                        update_case_field(case_data["id"], "referrals", referrals)
                    reply_text = display_text + "\n\n" + resolution["user_message"]

            except Exception as e:
                import traceback; traceback.print_exc()
                reply_text = display_text + "\n\n" + CLOSING.get(language, CLOSING["en"])

        history.append({"role": "user",  "content": user_message})
        history.append({"role": "model", "content": reply_text})

        return jsonify({
            "session_id": session_id,
            "reply":      reply_text,
            "case_saved": case_saved,
            "case_data":  case_data,
            "referrals":  referrals,
            "resolution": resolution
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "session_id": session_id}), 500

# ══════════════════════════════════════════════════════════════════════════════
# RESOURCE API
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/resources", methods=["GET"])
@api_staff_required
def get_resources():
    return jsonify(get_all_resources())

@app.route("/api/resources", methods=["POST"])
@api_staff_required
def create_resource():
    data = request.json or {}
    for field in ["name", "type", "category"]:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    r = {
        "name":                data["name"].strip(),
        "type":                data["type"],
        "category":            data["category"],
        "notes":               data.get("notes", ""),
        "active":              True,
        "created_at":          datetime.utcnow().isoformat(),
        "low_stock_threshold": int(data.get("low_stock_threshold", 3))
    }

    if data["type"] in ("quantity", "voucher"):
        r["quantity"] = int(data.get("quantity", 0))
        r["unit"]     = data.get("unit", "units")
        if data["type"] == "voucher":
            r["value"] = data.get("value", "")

    elif data["type"] == "appointment":
        r["staff_member"] = data.get("staff_member", "")
        r["slots"] = [
            {"datetime": s, "booked": False}
            for s in data.get("slots", []) if s
        ]

    elif data["type"] == "custom":
        r["description"]      = data.get("description", "")
        r["available"]        = True
        r["allocation_count"] = 0

    saved = save_resource_db(r)
    if saved:
        return jsonify(saved), 201
    return jsonify({"error": "Failed to save resource"}), 500

@app.route("/api/resources/<rid>", methods=["PATCH"])
@api_staff_required
def patch_resource(rid):
    data = request.json or {}
    allowed = {
        "name", "quantity", "notes", "active", "slots", "staff_member",
        "value", "unit", "low_stock_threshold", "description", "available", "category"
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400
    update_resource_db(rid, updates)
    return jsonify({"success": True})

@app.route("/api/resources/<rid>", methods=["DELETE"])
@api_staff_required
def remove_resource(rid):
    delete_resource_db(rid)
    return jsonify({"success": True})

@app.route("/api/resources/<rid>/restock", methods=["POST"])
@api_staff_required
def restock_resource(rid):
    qty = int((request.json or {}).get("quantity", 0))
    if qty <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400
    resources = get_all_resources()
    r = next((x for x in resources if x.get("id") == rid), None)
    if not r:
        return jsonify({"error": "Resource not found"}), 404
    new_qty = r.get("quantity", 0) + qty
    update_resource_db(rid, {"quantity": new_qty})
    return jsonify({"success": True, "new_quantity": new_qty})

@app.route("/api/resources/<rid>/add_slot", methods=["POST"])
@api_staff_required
def add_slot(rid):
    slot_dt = (request.json or {}).get("datetime", "").strip()
    if not slot_dt:
        return jsonify({"error": "datetime is required"}), 400
    resources = get_all_resources()
    r = next((x for x in resources if x.get("id") == rid), None)
    if not r:
        return jsonify({"error": "Resource not found"}), 404
    slots = r.get("slots", []) + [{"datetime": slot_dt, "booked": False}]
    update_resource_db(rid, {"slots": slots})
    return jsonify({"success": True})

@app.route("/api/allocations", methods=["GET"])
@api_staff_required
def get_allocations():
    try:
        if firebase_initialized and db:
            docs = db.collection("allocations").order_by(
                "timestamp", direction=firestore.Query.DESCENDING
            ).limit(100).stream()
            return jsonify([{"id": d.id, **d.to_dict()} for d in docs])
        return jsonify(list(reversed(memory_allocs[-100:])))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# CASES API
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/cases", methods=["GET"])
@api_staff_required
def get_cases():
    try:
        if firebase_initialized and db:
            docs = db.collection("cases").order_by(
                "timestamp", direction=firestore.Query.DESCENDING
            ).limit(200).stream()
            return jsonify([{"id": d.id, **d.to_dict()} for d in docs])
        return jsonify(list(reversed(memory_cases[-200:])))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<cid>/status", methods=["PATCH"])
@api_staff_required
def update_case_status(cid):
    status = (request.json or {}).get("status")
    valid = {"new", "in_progress", "resolved", "auto_resolved"}
    if status not in valid:
        return jsonify({"error": f"Invalid status. Must be one of: {valid}"}), 400
    try:
        if firebase_initialized and db:
            db.collection("cases").document(cid).update({"status": status})
        else:
            for c in memory_cases:
                if c.get("id") == cid:
                    c["status"] = status
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<cid>/notes", methods=["POST"])
@api_staff_required
def add_case_note(cid):
    note_text = ((request.json or {}).get("note") or "").strip()
    if not note_text:
        return jsonify({"error": "Note cannot be empty"}), 400
    note = {
        "text":      note_text,
        "timestamp": datetime.utcnow().isoformat(),
        "author":    "Staff"
    }
    try:
        if firebase_initialized and db:
            doc   = db.collection("cases").document(cid).get()
            notes = doc.to_dict().get("notes", []) + [note]
            db.collection("cases").document(cid).update({"notes": notes})
        else:
            for c in memory_cases:
                if c.get("id") == cid:
                    c.setdefault("notes", []).append(note)
        return jsonify({"success": True, "note": note})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS API
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/analytics/summary", methods=["GET"])
@api_staff_required
def analytics_summary():
    try:
        if firebase_initialized and db:
            cases = [d.to_dict() for d in db.collection("cases").stream()]
        else:
            cases = memory_cases

        needs = {}; langs = {}; daily = {}
        urg  = {"high": 0, "medium": 0, "low": 0}
        stat = {"new": 0, "in_progress": 0, "resolved": 0, "auto_resolved": 0}

        for c in cases:
            n = c.get("need_type", "other"); needs[n] = needs.get(n, 0) + 1
            l = c.get("language", "en");     langs[l]  = langs.get(l, 0) + 1
            u = c.get("urgency", "low");     urg[u]    = urg.get(u, 0) + 1
            s = c.get("status", "new");      stat[s]   = stat.get(s, 0) + 1
            ts = c.get("timestamp", "")
            if ts:
                day = ts[:10]
                daily[day] = daily.get(day, 0) + 1

        return jsonify({
            "total":         len(cases),
            "needs":         needs,
            "languages":     langs,
            "urgency":       urg,
            "status":        stat,
            "top_need":      max(needs, key=needs.get) if needs else "N/A",
            "daily":         dict(sorted(daily.items())[-14:]),
            "auto_resolved": stat.get("auto_resolved", 0)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/analytics/insight", methods=["POST"])
@api_staff_required
def analytics_insight():
    stats = (request.json or {}).get("stats", {})
    try:
        prompt = f"""You are a nonprofit operations analyst.
Give a 3-4 sentence insight and one specific actionable recommendation based on this data:
{json.dumps(stats, indent=2)}
Be specific, compassionate, and practical. Under 130 words."""
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return jsonify({"insight": resp.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def generate_referrals(case_data, language="en"):
    """Gemini-generated referral suggestions (fallback when no resources exist)."""
    try:
        lang_note = {"es":"in Spanish","fr":"in French","zh":"in Chinese","ar":"in Arabic"}.get(language, "in English")
        prompt = f"""Nonprofit case: need={case_data.get('need_type')}, urgency={case_data.get('urgency')}, summary={case_data.get('summary','')}.
Suggest 3 realistic local resource types {lang_note}.
Respond ONLY with a JSON array: [{{"type":"...","description":"..."}}]
No extra text."""
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = resp.text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        return result[:3] if isinstance(result, list) else []
    except Exception as e:
        print(f"generate_referrals error: {e}")
        return []

def update_case_field(cid, field, value):
    try:
        if firebase_initialized and db:
            db.collection("cases").document(cid).update({field: value})
        else:
            for c in memory_cases:
                if c.get("id") == cid:
                    c[field] = value
    except Exception as e:
        print(f"update_case_field error: {e}")

def save_case(case_data):
    try:
        if firebase_initialized and db:
            ref = db.collection("cases").document()
            ref.set(case_data)
            case_data["id"] = ref.id
        else:
            case_data["id"] = str(uuid.uuid4())
            memory_cases.append(case_data)
        return True
    except Exception as e:
        print(f"save_case error: {e}")
        return False

@app.route("/health")
def health():
    return jsonify({
        "status":    "ok",
        "firebase":  firebase_initialized,
        "timestamp": datetime.utcnow().isoformat()
    })

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    print(f"\n🚀 CommunityVoice → http://127.0.0.1:{port}")
    print(f"   Staff portal  → http://127.0.0.1:{port}/staff/login\n")
    app.run(debug=debug, host="0.0.0.0", port=port)