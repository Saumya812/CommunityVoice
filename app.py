# app.py — CommunityVoice v5 (Gemini Only — no Groq)
import os, json, uuid, re
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
import time
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from google import genai
from google.genai import types
import firebase_admin
try:
    from groq import Groq as GroqClient
    _groq_available = True
except ImportError:
    _groq_available = False
from firebase_admin import credentials, firestore

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "communityvoice-dev-secret-2026")

# ── AI Setup — Gemini only (primary + fallback) ────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
gemini_client = None
GEMINI_PRIMARY  = "gemini-2.5-flash"
GEMINI_FALLBACK = "gemini-2.5-flash-lite"
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE":
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print(f"✅ Gemini connected ({GEMINI_PRIMARY} + {GEMINI_FALLBACK} fallback)")
    except Exception as e:
        print(f"Gemini init failed: {e}")
else:
    print("⚠  No Gemini API key found")

# ── Groq fallback (silent — only used when Gemini quota exceeded) ────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client = None
if _groq_available and GROQ_API_KEY:
    try:
        groq_client = GroqClient(api_key=GROQ_API_KEY)
        print(f"✅ Groq fallback ready (llama-3.3-70b)")
    except Exception as e:
        print(f"Groq init failed: {e}")

# ── Rate limiting ──────────────────────────────────────────────────────────
_rate_store = defaultdict(list)
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW   = 60

def is_rate_limited(ip):
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
    if len(_rate_store[ip]) >= RATE_LIMIT_REQUESTS:
        return True
    _rate_store[ip].append(now)
    return False

# ── Staff credentials ──────────────────────────────────────────────────────
STAFF_USERNAME = os.environ.get("STAFF_USERNAME", "staff")
STAFF_PASSWORD = os.environ.get("STAFF_PASSWORD", "communityvoice2026")

# ── Firebase ───────────────────────────────────────────────────────────────
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

memory_cases     = []
memory_resources = []
memory_allocs    = []
chat_sessions    = {}

# ══════════════════════════════════════════════════════════════════════════
# CRISIS DETECTION
# ══════════════════════════════════════════════════════════════════════════
CRISIS_KEYWORDS = [
    "suicide", "suicidal", "kill myself", "end my life", "want to die",
    "self-harm", "self harm", "cutting", "hurt myself", "no reason to live",
    "can't go on", "cant go on", "overdose", "harm myself",
    "abused", "domestic violence", "he hits me", "she hits me",
]

def detect_crisis(text):
    return any(kw in text.lower() for kw in CRISIS_KEYWORDS)

# ══════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════
# AI PROMPTS
# ══════════════════════════════════════════════════════════════════════════
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

CRITICAL SAFETY RULE: If a user expresses thoughts of self-harm, suicide, or is in immediate danger,
you MUST immediately provide crisis resources (988 Suicide & Crisis Lifeline, 911) BEFORE anything else.
Never attempt to provide therapy or counseling. Your role is intake and referral ONLY.
Always make clear that a licensed human professional will follow up — not an AI.
For ANY mental health case, explicitly state the person will be connected with a qualified human counselor.

Guidelines:
- Greet warmly and ask how you can help
- Gently collect: first name, type of help needed, urgency context
- Ask ONE question at a time — never make it feel like a form
- Be patient, non-judgmental, affirming
- Categories: food_assistance, housing_shelter, utilities_help, medical_health,
  job_assistance, mental_health, legal_aid, childcare, transportation, other

When you have name + need + urgency, output EXACTLY this on its own line (no extra text after):
CASE_READY:{{"name":"<name>","need_type":"<category>","urgency":"<low|medium|high>","summary":"<1-2 sentence summary>","follow_up_needed":<true|false>,"language":"{language}","is_crisis":<true|false>}}

Set is_crisis=true for any safety concern.
Urgency guide: high=immediate safety risk, medium=needs help within days, low=general inquiry."""

CLOSING = {
    "en": "I've logged your request and our team will follow up shortly. Is there anything else I can help clarify?",
    "es": "He registrado su solicitud y nuestro equipo se comunicará pronto. ¿Hay algo más en lo que pueda ayudar?",
    "fr": "J'ai enregistré votre demande et notre équipe vous contactera bientôt. Y a-t-il autre chose?",
    "zh": "我已记录您的请求，团队将尽快联系您。还有什么需要帮助的吗？",
    "ar": "لقد سجلت طلبك وسيتواصل معك فريقنا قريباً. هل هناك أي شيء آخر؟",
}

def build_contents(history, user_message):
    contents = []
    for turn in history:
        contents.append(types.Content(
            role="model" if turn["role"] == "model" else "user",
            parts=[types.Part(text=turn["content"])]
        ))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents

def call_ai(prompt_or_messages, is_chat=False, history=None, user_message=None, language="en"):
    """Gemini-only AI caller — gemini-2.0-flash primary, gemini-1.5-flash fallback."""
    if not gemini_client:
        raise Exception("Gemini API key not configured. Set GEMINI_API_KEY in .env")

    if is_chat:
        contents = build_contents(history or [], user_message or "")
        system   = get_system_prompt(language)
        for model in [GEMINI_PRIMARY, GEMINI_FALLBACK]:
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system)
                )
                return response.text
            except Exception as e:
                print(f"Gemini {model} failed, trying fallback: {e}")
        # Both Gemini models failed — try Groq silently
        if groq_client:
            print("Gemini quota exceeded — using Groq fallback")
            messages = [
                {"role": "system", "content": get_system_prompt(language)},
                *[{"role": "user" if t["role"] == "user" else "assistant", "content": t["content"]} for t in (history or [])],
                {"role": "user", "content": user_message or ""}
            ]
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages, temperature=0.7
            )
            return response.choices[0].message.content
        raise Exception("All Gemini models failed and no Groq fallback available")
    else:
        for model in [GEMINI_PRIMARY, GEMINI_FALLBACK]:
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=prompt_or_messages,
                )
                return response.text
            except Exception as e:
                print(f"Gemini {model} failed, trying fallback: {e}")
        # Both Gemini models failed — try Groq for non-chat calls too
        if groq_client:
            print("Gemini quota exceeded — using Groq fallback for prompt")
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt_or_messages}],
                temperature=0.7
            )
            return response.choices[0].message.content
        raise Exception("All Gemini models failed and no Groq fallback available")

# ══════════════════════════════════════════════════════════════════════════
# AI QUALITY LAYER
# ══════════════════════════════════════════════════════════════════════════
QUALITY_FALLBACK = {
    "en": "I want to make sure I am helping you properly. Could you tell me a bit more about what you need? A real staff member will also follow up with you personally.",
    "es": "Quiero asegurarme de ayudarle correctamente. Un miembro real del equipo se comunicara con usted personalmente.",
    "fr": "Je veux m assurer de vous aider correctement. Un vrai membre de l equipe vous contactera egalement.",
    "zh": "我想确保我能正确地帮助您。一位真正的工作人员也会亲自跟进。",
    "ar": "اريد التاكد من مساعدتك بشكل صحيح. سيتابع معك احد اعضاء الفريق الحقيقيين شخصيا.",
}

def ai_quality_check(response_text, user_message, need_type=None, language="en"):
    """Priority 2 — AI Quality Layer. Evaluates AI response before user sees it."""
    if any(x in response_text for x in ["988", "911", "Crisis Text Line", "CASE_READY:"]):
        return True, response_text

    is_mh = need_type == "mental_health" or any(
        kw in user_message.lower()
        for kw in ["mental", "depress", "anxiety", "stress", "therapy", "counseling"]
    )

    prompt = (
        "You are a responsible AI safety reviewer for a nonprofit intake system.\n"
        "Review this AI response shown to a vulnerable community member.\n\n"
        f"User message: {repr(user_message[:200])}\n"
        f"AI response: {repr(response_text[:600])}\n"
        f"Mental health related: {is_mh}\n\n"
        "Check for:\n"
        "1. Does it give medical or therapy advice? (FAIL)\n"
        "2. Does it make promises the nonprofit cannot keep? (FAIL)\n"
        "3. Is it dismissive or cold to someone in need? (FAIL)\n"
        "4. Does it ask for SSN, bank details, or passwords? (FAIL)\n"
        "5. Is it appropriate and helpful for a vulnerable person? (PASS)\n\n"
        "Respond ONLY with JSON: "
        '{"passed": true/false, "reason": "<one sentence>", "severity": "low/medium/high"}'
    )

    try:
        result = call_ai(prompt)
        if "```" in result:
            result = result.split("```")[1]
            if result.startswith("json"): result = result[4:]
        check = json.loads(result.strip())
        passed   = check.get("passed", True)
        severity = check.get("severity", "low")
        reason   = check.get("reason", "")
        print(f"Quality check: {'PASS' if passed else 'FAIL'} | {severity} | {reason}")
        if not passed and severity in ("medium", "high"):
            return False, QUALITY_FALLBACK.get(language, QUALITY_FALLBACK["en"])
        return True, response_text
    except Exception as e:
        print(f"Quality check error (passing through): {e}")
        return True, response_text

# ══════════════════════════════════════════════════════════════════════════
# PII MASKING
# ══════════════════════════════════════════════════════════════════════════
PII_PATTERNS = [
    (re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'), "[SSN MASKED]"),
    (re.compile(r'\b(?:\d[ -]?){15,16}\b'), "[CARD MASKED]"),
    (re.compile(r'\b(0?[1-9]|1[0-2])[\/\-](0?[1-9]|[12]\d|3[01])[\/\-](19|20)\d{2}\b'), "[DOB MASKED]"),
]

def mask_pii(text):
    if not text:
        return text, False
    masked = text
    was_masked = False
    for pattern, replacement in PII_PATTERNS:
        new = pattern.sub(replacement, masked)
        if new != masked:
            was_masked = True
            masked = new
    return masked, was_masked

def mask_case_data(case_data):
    fields_to_mask = ["summary", "name"]
    any_masked = False
    for field in fields_to_mask:
        val = case_data.get(field, "")
        if val:
            masked, was_masked = mask_pii(str(val))
            if was_masked:
                case_data[field] = masked
                any_masked = True
                print(f"PII masked in field: {field}")
    if any_masked:
        case_data["pii_masked"] = True
    return case_data

# ══════════════════════════════════════════════════════════════════════════
# RESOURCE ENGINE
# ══════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════
# CROSS-NGO RESOURCE NETWORK
# ══════════════════════════════════════════════════════════════════════════

# Partner organizations stored in Firebase under network_orgs collection
# Each org has: name, contact, resources (list of resource summaries)

def get_network_orgs():
    """Get all partner organizations that have opted into sharing."""
    try:
        if firebase_initialized and db:
            docs = db.collection("network_orgs").where("sharing", "==", True).stream()
            return [{"id": d.id, **d.to_dict()} for d in docs]
        return []
    except Exception as e:
        print(f"get_network_orgs error: {e}"); return []

def seed_network_orgs():
    """Seed demo partner organizations if none exist."""
    try:
        if not firebase_initialized or not db:
            return
        existing = list(db.collection("network_orgs").limit(1).stream())
        if existing:
            return
        orgs = [
            {
                "name": "Baltimore Food Bank",
                "type": "Food Assistance",
                "location": "Baltimore, MD",
                "sharing": True,
                "contact": "info@baltimorefoodbank.org",
                "resources": [
                    {"name": "Rice Bags", "category": "food_assistance", "quantity": 45, "unit": "bags"},
                    {"name": "Canned Goods", "category": "food_assistance", "quantity": 120, "unit": "cans"},
                    {"name": "Baby Formula", "category": "food_assistance", "quantity": 8, "unit": "units"},
                ]
            },
            {
                "name": "Shriver PeaceWorker Program",
                "type": "Housing & Support",
                "location": "UMBC",
                "sharing": True,
                "contact": "sfarina@umbc.edu",
                "resources": [
                    {"name": "Housing Referrals", "category": "housing_shelter", "quantity": 3, "unit": "referrals"},
                    {"name": "Emergency Funds", "category": "utilities_help", "quantity": 500, "unit": "dollars"},
                ]
            },
            {
                "name": "Maryland Legal Aid",
                "type": "Legal Services",
                "location": "Baltimore, MD",
                "sharing": False,
                "contact": "info@mdlegalaid.org",
                "resources": [
                    {"name": "Legal Consultations", "category": "legal_aid", "quantity": 5, "unit": "slots"},
                ]
            },
        ]
        for org in orgs:
            db.collection("network_orgs").document().set(org)
        print("✅ Network orgs seeded")
    except Exception as e:
        print(f"seed_network_orgs error: {e}")

def find_network_resources(need_type, quantity_needed, local_quantity):
    """
    Check partner organizations for resources when local inventory is insufficient.
    Returns list of fulfillment sources or empty list.
    """
    shortfall = quantity_needed - local_quantity
    if shortfall <= 0:
        return []

    orgs = get_network_orgs()
    fulfillments = []
    remaining = shortfall

    for org in orgs:
        if remaining <= 0:
            break
        for res in org.get("resources", []):
            if res.get("category") == need_type and res.get("quantity", 0) > 0:
                can_provide = min(res["quantity"], remaining)
                fulfillments.append({
                    "org_name": org["name"],
                    "org_id": org["id"],
                    "resource_name": res["name"],
                    "quantity": can_provide,
                    "unit": res.get("unit", "units"),
                })
                remaining -= can_provide
                break

    return fulfillments if (shortfall - remaining) > 0 else []

def log_network_fulfillment(case_data, local_qty, network_fulfillments, need_type):
    """Log a cross-NGO fulfillment event."""
    record = {
        "case_id": case_data.get("id", ""),
        "case_name": case_data.get("name", ""),
        "need_type": need_type,
        "local_quantity": local_qty,
        "network_fulfillments": network_fulfillments,
        "timestamp": datetime.utcnow().isoformat(),
        "total_fulfilled": local_qty + sum(f["quantity"] for f in network_fulfillments),
    }
    try:
        if firebase_initialized and db:
            db.collection("network_fulfillments").document().set(record)
    except Exception as e:
        print(f"log_network_fulfillment error: {e}")

def get_all_resources():
    try:
        if firebase_initialized and db:
            return [{"id": d.id, **d.to_dict()} for d in db.collection("resources").stream()]
        return list(memory_resources)
    except Exception as e:
        print(f"get_all_resources error: {e}"); return []

def save_resource_db(r):
    try:
        if firebase_initialized and db:
            ref = db.collection("resources").document()
            ref.set(r); r["id"] = ref.id
        else:
            r["id"] = str(uuid.uuid4()); memory_resources.append(r)
        return r
    except Exception as e:
        print(f"save_resource error: {e}"); return None

def update_resource_db(rid, updates):
    try:
        if firebase_initialized and db:
            db.collection("resources").document(rid).update(updates)
        else:
            for r in memory_resources:
                if r.get("id") == rid: r.update(updates)
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
    keywords = NEED_KEYWORDS.get(need_type, [need_type.replace("_", " ")])
    matches = []
    for r in get_all_resources():
        if r.get("active") is False: continue
        combined = f"{r.get('name','')} {r.get('category','')} {r.get('notes','')}".lower()
        cat = r.get("category", "").replace(" ", "_").replace("/", "_")
        if cat == need_type or any(kw in combined for kw in keywords):
            matches.append(r)
    return matches

def log_allocation(resource_id, case_data, quantity, summary):
    record = {
        "resource_id": resource_id, "case_id": case_data.get("id", ""),
        "case_name": case_data.get("name", ""), "need_type": case_data.get("need_type", ""),
        "quantity": quantity, "summary": summary,
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        if firebase_initialized and db:
            db.collection("allocations").document().set(record)
        else:
            memory_allocs.append({**record, "id": str(uuid.uuid4())})
    except Exception as e:
        print(f"log_allocation error: {e}")

def _no_resource_msg(name, need_type, lang):
    label = need_type.replace("_", " ")
    msgs = {
        "en": f"Thank you {name} — your {label} request has been logged and flagged as high priority. A staff member will contact you shortly.",
        "es": f"Gracias {name} — su solicitud de {label} ha sido registrada como prioridad. Un miembro del equipo se comunicará pronto.",
        "fr": f"Merci {name} — votre demande de {label} a été enregistrée. Notre équipe vous contactera bientôt.",
        "zh": f"谢谢{name}——您的{label}请求已被标记为优先事项。工作人员将很快联系您。",
        "ar": f"شكراً {name} — تم تسجيل طلبك كأولوية. سيتواصل معك أحد أعضاء الفريق قريباً.",
    }
    return msgs.get(lang, msgs["en"])

def execute_auto_resolution(case_data, language="en"):
    need_type = case_data.get("need_type", "other")
    name      = case_data.get("name", "there")
    is_crisis = case_data.get("is_crisis", False)

    if is_crisis or (case_data.get("urgency") == "high" and need_type == "mental_health"):
        msg = {
            "en": f"Thank you for trusting us, {name}. Your case is marked urgent and a real staff member will reach out directly. You are not alone. Please call or text 988 (free, 24/7) or 911 if in immediate danger.",
            "es": f"Gracias por confiar en nosotros, {name}. Su caso es urgente. No está solo/a. Llame al 988 o al 911.",
        }.get(language, f"Thank you {name}. Your case is urgent and staff will contact you directly. Call 988 for immediate support.")
        return {"resolved": False, "action_taken": "Crisis — escalated to human staff",
                "resolution_details": {}, "user_message": msg, "resource_id": None, "escalated_to_human": True}

    matching = find_matching_resources(need_type)
    summaries = []
    for r in matching:
        rtype = r.get("type")
        if rtype in ("quantity", "voucher") and r.get("quantity", 0) > 0:
            summaries.append({"id": r["id"], "name": r["name"], "type": rtype,
                               "available": r["quantity"], "unit": r.get("unit", "units"), "notes": r.get("notes", "")})
        elif rtype == "appointment":
            free = [s for s in r.get("slots", []) if not s.get("booked")]
            if free:
                summaries.append({"id": r["id"], "name": r["name"], "type": "appointment",
                                   "next_available": free[0].get("datetime", ""), "staff_member": r.get("staff_member", ""), "notes": r.get("notes", "")})
        elif rtype == "custom" and r.get("available", True):
            summaries.append({"id": r["id"], "name": r["name"], "type": "custom",
                               "description": r.get("description", ""), "notes": r.get("notes", "")})

    if not summaries:
        # Check cross-NGO network before giving up
        network_fulfillments = find_network_resources(need_type, 1, 0)
        if network_fulfillments:
            org_names = " + ".join(f["org_name"] for f in network_fulfillments)
            log_network_fulfillment(case_data, 0, network_fulfillments, need_type)
            lang_msgs = {
                "en": f"Great news {name} — while our local inventory is currently low, our partner network has stepped in. {org_names} will fulfill your {need_type.replace('_',' ')} request. A staff member will coordinate the details with you shortly.",
                "es": f"Buenas noticias {name} — nuestra red de socios puede ayudarle. {org_names} atenderá su solicitud. Un miembro del equipo se comunicará pronto.",
            }
            msg = lang_msgs.get(language, lang_msgs["en"])
            return {"resolved": True, "action_taken": f"Cross-NGO fulfillment via {org_names}",
                    "resolution_details": {"network_fulfillments": network_fulfillments},
                    "user_message": msg, "resource_id": None, "cross_ngo": True}
        return {"resolved": False, "action_taken": "No resources available",
                "resolution_details": {}, "user_message": _no_resource_msg(name, need_type, language), "resource_id": None}

    lang_note = {"es":"in Spanish","fr":"in French","zh":"in Chinese","ar":"in Arabic"}.get(language, "in English")
    prompt = f"""Nonprofit resource allocation. Case: name={name}, need={need_type}, urgency={case_data.get("urgency","medium")}
Resources: {json.dumps(summaries)}
Respond ONLY with JSON:
{{"selected_resource_id":"<id>","resource_name":"<name>","resource_type":"<type>","quantity_allocated":<n or null>,"slot_datetime":"<dt or null>","action_summary":"<1 sentence English>","user_message":"<warm 2-3 sentence {lang_note} to {name}>"}}"""

    try:
        text = call_ai(prompt)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        decision = json.loads(text.strip())
    except Exception as e:
        print(f"Auto-resolution error: {e}")
        return {"resolved": False, "action_taken": "AI error",
                "resolution_details": {}, "user_message": _no_resource_msg(name, need_type, language), "resource_id": None}

    res_id = decision.get("selected_resource_id")
    full_r = next((r for r in matching if r.get("id") == res_id), None)
    if not full_r:
        return {"resolved": False, "action_taken": "Resource not found",
                "resolution_details": {}, "user_message": _no_resource_msg(name, need_type, language), "resource_id": None}

    try:
        rtype = decision.get("resource_type")
        if rtype in ("quantity", "voucher"):
            qty = max(1, int(decision.get("quantity_allocated") or 1))
            update_resource_db(res_id, {"quantity": max(0, full_r.get("quantity", 0) - qty),
                                        "last_allocated": datetime.utcnow().isoformat()})
            log_allocation(res_id, case_data, qty, decision.get("action_summary", ""))
        elif rtype == "appointment":
            slots = full_r.get("slots", [])
            for s in slots:
                if not s.get("booked"):
                    s["booked"] = True; s["booked_by"] = name
                    s["booked_at"] = datetime.utcnow().isoformat(); break
            update_resource_db(res_id, {"slots": slots, "last_allocated": datetime.utcnow().isoformat()})
            log_allocation(res_id, case_data, 1, decision.get("action_summary", ""))
        elif rtype == "custom":
            update_resource_db(res_id, {"last_allocated": datetime.utcnow().isoformat(),
                                        "allocation_count": full_r.get("allocation_count", 0) + 1})
            log_allocation(res_id, case_data, 1, decision.get("action_summary", ""))
    except Exception as e:
        print(f"Allocation exec error: {e}")

    # Check if we need cross-NGO top-up (partial local fulfillment)
    qty_allocated = decision.get("quantity_allocated") or 1
    qty_available = full_r.get("quantity", 0)
    cross_ngo_msg = ""
    if qty_available < qty_allocated:
        shortfall = qty_allocated - qty_available
        network_fulfillments = find_network_resources(need_type, shortfall, 0)
        if network_fulfillments:
            log_network_fulfillment(case_data, qty_available, network_fulfillments, need_type)
            org_names = " + ".join(f["org_name"] for f in network_fulfillments)
            cross_ngo_msg = f" Additionally, {org_names} will provide the remaining {shortfall} {full_r.get('unit','units')} through our partner network."
            print(f"Cross-NGO top-up: {org_names} providing {shortfall} units")

    user_msg = decision.get("user_message", "") + cross_ngo_msg

    return {"resolved": True, "action_taken": decision.get("action_summary", "Allocated"),
            "resolution_details": decision, "user_message": user_msg,
            "resource_id": res_id, "cross_ngo": bool(cross_ngo_msg)}

# ══════════════════════════════════════════════════════════════════════════
# SECURITY HEADERS
# ══════════════════════════════════════════════════════════════════════════
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    return response

# ══════════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════
@app.route("/")
def landing(): return render_template("landing.html")

@app.route("/chat")
def index(): return render_template("index.html")

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
    session.clear(); return redirect(url_for("staff_login"))

@app.route("/dashboard")
@staff_required
def dashboard(): return render_template("dashboard.html")

@app.route("/analytics")
@staff_required
def analytics(): return render_template("analytics.html")

@app.route("/resources")
@staff_required
def resources_page(): return render_template("resources.html")

@app.route("/impact")
@staff_required
def impact_page(): return render_template("impact.html")

@app.route("/network")
@staff_required
def network_page(): return render_template("network.html")

# ══════════════════════════════════════════════════════════════════════════
# CHAT API
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/chat", methods=["POST"])
def chat():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if is_rate_limited(ip):
        return jsonify({"error": "Too many requests. Please wait a moment."}), 429

    data         = request.json or {}
    session_id   = data.get("session_id") or str(uuid.uuid4())
    user_message = (data.get("message") or "").strip()
    language     = data.get("language", "en")
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in chat_sessions:
        chat_sessions[session_id] = {"history": [], "language": language}
    history = chat_sessions[session_id]["history"]

    is_crisis_msg = detect_crisis(user_message)
    crisis_payload = None
    if is_crisis_msg:
        crisis_payload = {
            "message": "Please reach out — immediate support is available right now",
            "resources": [
                {"name": "988 Suicide & Crisis Lifeline", "detail": "Call or text 988 — free, confidential, 24/7", "urgent": True},
                {"name": "Crisis Text Line", "detail": "Text HOME to 741741 — free, 24/7", "urgent": True},
                {"name": "Emergency Services", "detail": "Call 911 if you or someone else is in immediate danger", "urgent": True},
            ]
        }

    try:
        raw_reply = call_ai(None, is_chat=True, history=history, user_message=user_message, language=language)

        # AI Quality Layer — evaluate before showing to user
        passed, reply_text = ai_quality_check(raw_reply, user_message, language=language)
        if not passed:
            print("Quality check FAILED — using safe fallback")

        case_saved = False; case_data = None; referrals = []; resolution = None

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
                    "notes":      [],
                    "is_crisis":  case_data.get("is_crisis", is_crisis_msg)
                })
                case_data = mask_case_data(case_data)
                case_saved = save_case(case_data)
                resolution = execute_auto_resolution(case_data, language)

                if resolution["resolved"]:
                    cid = case_data.get("id")
                    if cid:
                        update_case_field(cid, "status", "auto_resolved")
                        update_case_field(cid, "auto_resolved", True)
                        update_case_field(cid, "resolution_summary", resolution["action_taken"])
                        update_case_field(cid, "resource_id", resolution.get("resource_id"))
                    reply_text = display_text + "\n\n" + resolution["user_message"]
                else:
                    if resolution.get("escalated_to_human") and case_data.get("id"):
                        update_case_field(case_data["id"], "crisis_flag", True)
                    else:
                        referrals = generate_referrals(case_data, language)
                        if referrals and case_data.get("id"):
                            update_case_field(case_data["id"], "referrals", referrals)
                    reply_text = display_text + "\n\n" + resolution["user_message"]
            except Exception as e:
                import traceback; traceback.print_exc()
                reply_text = display_text + "\n\n" + CLOSING.get(language, CLOSING["en"])

        history.append({"role": "user", "content": user_message})
        history.append({"role": "model", "content": reply_text})

        return jsonify({"session_id": session_id, "reply": reply_text, "case_saved": case_saved,
                        "case_data": case_data, "referrals": referrals, "resolution": resolution,
                        "crisis": crisis_payload})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "session_id": session_id}), 500

# ══════════════════════════════════════════════════════════════════════════
# FEEDBACK API
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/cases/<cid>/feedback/public", methods=["POST"])
def case_feedback_public(cid):
    data   = request.json or {}
    rating = data.get("rating")
    if rating not in ("up", "down"):
        return jsonify({"error": "rating must be up or down"}), 400
    update = {
        "satisfaction":        rating,
        "satisfaction_source": "user",
        "satisfaction_at":     datetime.utcnow().isoformat(),
        "needs_review":        rating == "down",
    }
    try:
        if firebase_initialized and db:
            db.collection("cases").document(cid).update(update)
        else:
            for c in memory_cases:
                if c.get("id") == cid: c.update(update)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<cid>/feedback", methods=["POST"])
@api_staff_required
def case_feedback(cid):
    data   = request.json or {}
    rating = data.get("rating")
    if rating not in ("up", "down"):
        return jsonify({"error": "rating must be up or down"}), 400
    update = {
        "satisfaction":        rating,
        "satisfaction_source": "staff",
        "satisfaction_at":     datetime.utcnow().isoformat(),
        "needs_review":        rating == "down",
    }
    try:
        if firebase_initialized and db:
            db.collection("cases").document(cid).update(update)
        else:
            for c in memory_cases:
                if c.get("id") == cid: c.update(update)
        return jsonify({"success": True, "flagged_for_review": rating == "down"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<cid>/takeover", methods=["POST"])
@api_staff_required
def takeover_case(cid):
    data       = request.json or {}
    staff_note = data.get("note", "Staff took over this case for direct follow-up.")
    note = {"text": f"🙋 Staff takeover: {staff_note}", "timestamp": datetime.utcnow().isoformat(), "author": "Staff"}
    update = {
        "status":         "in_progress",
        "human_takeover": True,
        "takeover_at":    datetime.utcnow().isoformat(),
        "needs_review":   False,
        "auto_resolved":  False,
    }
    try:
        if firebase_initialized and db:
            doc   = db.collection("cases").document(cid).get()
            notes = doc.to_dict().get("notes", []) + [note]
            update["notes"] = notes
            db.collection("cases").document(cid).update(update)
        else:
            for c in memory_cases:
                if c.get("id") == cid:
                    c.update(update)
                    c.setdefault("notes", []).append(note)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════
# RESOURCE API
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/resources", methods=["GET"])
@api_staff_required
def get_resources(): return jsonify(get_all_resources())

@app.route("/api/resources", methods=["POST"])
@api_staff_required
def create_resource():
    data = request.json or {}
    for f in ["name", "type", "category"]:
        if not data.get(f): return jsonify({"error": f"Missing: {f}"}), 400
    r = {"name": data["name"].strip(), "type": data["type"], "category": data["category"],
         "notes": data.get("notes", ""), "active": True,
         "created_at": datetime.utcnow().isoformat(),
         "low_stock_threshold": int(data.get("low_stock_threshold", 3))}
    if data["type"] in ("quantity", "voucher"):
        r["quantity"] = int(data.get("quantity", 0)); r["unit"] = data.get("unit", "units")
        if data["type"] == "voucher": r["value"] = data.get("value", "")
    elif data["type"] == "appointment":
        r["staff_member"] = data.get("staff_member", "")
        r["slots"] = [{"datetime": s, "booked": False} for s in data.get("slots", []) if s]
    elif data["type"] == "custom":
        r["description"] = data.get("description", ""); r["available"] = True; r["allocation_count"] = 0
    saved = save_resource_db(r)
    return (jsonify(saved), 201) if saved else (jsonify({"error": "Failed"}), 500)

@app.route("/api/resources/<rid>", methods=["PATCH"])
@api_staff_required
def patch_resource(rid):
    data = request.json or {}
    allowed = {"name","quantity","notes","active","slots","staff_member","value","unit","low_stock_threshold","description","available","category"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates: return jsonify({"error": "Nothing to update"}), 400
    update_resource_db(rid, updates); return jsonify({"success": True})

@app.route("/api/resources/<rid>", methods=["DELETE"])
@api_staff_required
def remove_resource(rid):
    delete_resource_db(rid); return jsonify({"success": True})

@app.route("/api/resources/<rid>/restock", methods=["POST"])
@api_staff_required
def restock_resource(rid):
    qty = int((request.json or {}).get("quantity", 0))
    if qty <= 0: return jsonify({"error": "Must be positive"}), 400
    r = next((x for x in get_all_resources() if x.get("id") == rid), None)
    if not r: return jsonify({"error": "Not found"}), 404
    new_qty = r.get("quantity", 0) + qty
    update_resource_db(rid, {"quantity": new_qty})
    return jsonify({"success": True, "new_quantity": new_qty})

@app.route("/api/resources/<rid>/add_slot", methods=["POST"])
@api_staff_required
def add_slot(rid):
    slot_dt = (request.json or {}).get("datetime", "").strip()
    if not slot_dt: return jsonify({"error": "datetime required"}), 400
    r = next((x for x in get_all_resources() if x.get("id") == rid), None)
    if not r: return jsonify({"error": "Not found"}), 404
    update_resource_db(rid, {"slots": r.get("slots", []) + [{"datetime": slot_dt, "booked": False}]})
    return jsonify({"success": True})

@app.route("/api/allocations", methods=["GET"])
@api_staff_required
def get_allocations():
    try:
        if firebase_initialized and db:
            docs = db.collection("allocations").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100).stream()
            return jsonify([{"id": d.id, **d.to_dict()} for d in docs])
        return jsonify(list(reversed(memory_allocs[-100:])))
    except Exception as e: return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════
# CASES API
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/cases", methods=["GET"])
@api_staff_required
def get_cases():
    try:
        if firebase_initialized and db:
            docs = db.collection("cases").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(200).stream()
            return jsonify([{"id": d.id, **d.to_dict()} for d in docs])
        return jsonify(list(reversed(memory_cases[-200:])))
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<cid>/status", methods=["PATCH"])
@api_staff_required
def update_case_status(cid):
    status = (request.json or {}).get("status")
    if status not in {"new","in_progress","resolved","auto_resolved"}:
        return jsonify({"error": "Invalid status"}), 400
    try:
        if firebase_initialized and db:
            db.collection("cases").document(cid).update({"status": status})
        else:
            for c in memory_cases:
                if c.get("id") == cid: c["status"] = status
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/cases/<cid>/notes", methods=["POST"])
@api_staff_required
def add_case_note(cid):
    note_text = ((request.json or {}).get("note") or "").strip()
    if not note_text: return jsonify({"error": "Empty note"}), 400
    note = {"text": note_text, "timestamp": datetime.utcnow().isoformat(), "author": "Staff"}
    try:
        if firebase_initialized and db:
            doc = db.collection("cases").document(cid).get()
            notes = doc.to_dict().get("notes", []) + [note]
            db.collection("cases").document(cid).update({"notes": notes})
        else:
            for c in memory_cases:
                if c.get("id") == cid: c.setdefault("notes", []).append(note)
        return jsonify({"success": True, "note": note})
    except Exception as e: return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════
# ANALYTICS API
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/analytics/summary", methods=["GET"])
@api_staff_required
def analytics_summary():
    try:
        cases = [d.to_dict() for d in db.collection("cases").stream()] if firebase_initialized and db else memory_cases
        needs = {}; langs = {}; daily = {}
        urg = {"high":0,"medium":0,"low":0}
        stat = {"new":0,"in_progress":0,"resolved":0,"auto_resolved":0}
        crisis_count = 0
        for c in cases:
            n=c.get("need_type","other"); needs[n]=needs.get(n,0)+1
            l=c.get("language","en");    langs[l]=langs.get(l,0)+1
            u=c.get("urgency","low");    urg[u]=urg.get(u,0)+1
            s=c.get("status","new");     stat[s]=stat.get(s,0)+1
            if c.get("crisis_flag") or c.get("is_crisis"): crisis_count+=1
            ts=c.get("timestamp","")
            if ts: day=ts[:10]; daily[day]=daily.get(day,0)+1
        auto_res = stat.get("auto_resolved",0)
        minutes_saved = auto_res * 23
        return jsonify({
            "total":len(cases),"needs":needs,"languages":langs,"urgency":urg,"status":stat,
            "top_need":max(needs,key=needs.get) if needs else "N/A",
            "daily":dict(sorted(daily.items())[-14:]),
            "auto_resolved":auto_res,
            "impact":{
                "auto_resolved":auto_res,
                "auto_resolve_rate":round(auto_res/len(cases)*100) if cases else 0,
                "minutes_saved":minutes_saved,
                "hours_saved":round(minutes_saved/60,1),
                "crisis_cases":crisis_count,
                "languages_used":len([l for l,c in langs.items() if c>0]),
                "thumbs_up":sum(1 for c in cases if c.get("satisfaction")=="up"),
                "thumbs_down":sum(1 for c in cases if c.get("satisfaction")=="down"),
                "needs_review":sum(1 for c in cases if c.get("needs_review")),
                "human_takeovers":sum(1 for c in cases if c.get("human_takeover")),
            }
        })
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/analytics/insight", methods=["POST"])
@api_staff_required
def analytics_insight():
    stats = (request.json or {}).get("stats", {})
    try:
        prompt = f"""You are a nonprofit operations analyst reviewing CommunityVoice data.
Give a 3-4 sentence insight and one specific actionable recommendation. Under 130 words.
Data: {json.dumps(stats, indent=2)}"""
        insight = call_ai(prompt)
        return jsonify({"insight": insight})
    except Exception as e: return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════
def generate_referrals(case_data, language="en"):
    try:
        lang_note = {"es":"in Spanish","fr":"in French","zh":"in Chinese","ar":"in Arabic"}.get(language,"in English")
        prompt = f"""Nonprofit case: need={case_data.get("need_type")}, urgency={case_data.get("urgency")}.
Suggest 3 realistic local resource types {lang_note}.
Respond ONLY with JSON: [{{"type":"...","description":"..."}}]"""
        text = call_ai(prompt)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        result = json.loads(text.strip())
        return result[:3] if isinstance(result, list) else []
    except Exception as e:
        print(f"generate_referrals error: {e}"); return []

def update_case_field(cid, field, value):
    try:
        if firebase_initialized and db:
            db.collection("cases").document(cid).update({field: value})
        else:
            for c in memory_cases:
                if c.get("id") == cid: c[field] = value
    except Exception as e: print(f"update_case_field: {e}")

def save_case(case_data):
    try:
        if firebase_initialized and db:
            ref = db.collection("cases").document()
            ref.set(case_data); case_data["id"] = ref.id
        else:
            case_data["id"] = str(uuid.uuid4()); memory_cases.append(case_data)
        return True
    except Exception as e:
        print(f"save_case: {e}"); return False

@app.route("/health")
def health():
    return jsonify({"status":"ok","firebase":firebase_initialized,
                    "ai":GEMINI_PRIMARY,
                    "timestamp":datetime.utcnow().isoformat()})

@app.route("/api/config/maps")
@staff_required
def maps_config():
    """Safely expose Maps API key to authenticated staff only."""
    key = os.environ.get("MAPS_API_KEY", "")
    return jsonify({"key": key})

@app.route("/api/network/orgs", methods=["GET"])
@api_staff_required
def get_network_orgs_api():
    """Get all partner organizations."""
    try:
        if firebase_initialized and db:
            docs = db.collection("network_orgs").stream()
            return jsonify([{"id": d.id, **d.to_dict()} for d in docs])
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/network/orgs/<oid>/toggle", methods=["POST"])
@api_staff_required
def toggle_org_sharing(oid):
    """Toggle sharing status for a partner org."""
    try:
        sharing = (request.json or {}).get("sharing", True)
        if firebase_initialized and db:
            db.collection("network_orgs").document(oid).update({"sharing": sharing})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/network/fulfillments", methods=["GET"])
@api_staff_required
def get_network_fulfillments():
    """Get recent cross-NGO fulfillment log."""
    try:
        if firebase_initialized and db:
            docs = db.collection("network_fulfillments").order_by(
                "timestamp", direction=firestore.Query.DESCENDING).limit(20).stream()
            return jsonify([{"id": d.id, **d.to_dict()} for d in docs])
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Seed partner orgs on startup
seed_network_orgs()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    print(f"\n🚀 CommunityVoice v5 → http://127.0.0.1:{port}")
    print(f"   Staff portal  → http://127.0.0.1:{port}/staff/login\n")
    app.run(debug=debug, host="0.0.0.0", port=port)