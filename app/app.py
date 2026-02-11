import json
import os
import re
import uuid
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

from app.rag import RAGService
from app.sources import EvidenceFinder
from app.llm import ChatLLM

load_dotenv()

app = Flask(__name__, static_folder='../static', template_folder='../templates')
CORS(app)

# In-memory session store (swap to Redis/Flask-Session if you like)
SESSIONS = {}
RAG_CACHE = {}

# Initialize services
chroma_dir = os.getenv("CHROMA_DIR", ".chroma_db")
cases_config_path = os.getenv("CASES_CONFIG", "./data/cases.json")
default_history_pdf = os.getenv("CASE_HISTORY_PDF", "./data/case_history.pdf")
default_exam_pdf = os.getenv("CASE_EXAM_PDF", "./data/case_exam.pdf")
default_assigned_dx = os.getenv("ASSIGNED_DIAGNOSIS", "Pneumonia")

llm = ChatLLM()
sources = EvidenceFinder()


def _sanitize_namespace_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value or "default")


def _default_case_config() -> dict:
    return {
        "essential_tremor": {
            "label": "Essential Tremor",
            "history_pdf": default_history_pdf,
            "exam_pdf": default_exam_pdf,
            "assigned_diagnosis": default_assigned_dx,
        }
    }


def _load_cases() -> dict:
    config_path = Path(cases_config_path)
    if not config_path.exists():
        return _default_case_config()

    with config_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    cases = payload.get("cases", payload)
    if not isinstance(cases, dict) or not cases:
        return _default_case_config()

    normalized = {}
    for case_id, case in cases.items():
        if not isinstance(case, dict):
            continue
        normalized[case_id] = {
            "label": case.get("label", case_id.replace("_", " ").title()),
            "history_pdf": case.get("history_pdf", default_history_pdf),
            "exam_pdf": case.get("exam_pdf", default_exam_pdf),
            "assigned_diagnosis": case.get("assigned_diagnosis", default_assigned_dx),
        }

    return normalized or _default_case_config()


CASES = _load_cases()
DEFAULT_CASE_ID = next(iter(CASES.keys()))


PATIENT_SYSTEM = (
    "You are a *standardized patient* in a simulation. Answer ONLY using the provided case context and keep answers short (1 sentence max), concise and realistic. "
    "Stay fully in character as the patient and answer in first person ONLY using provided case context. "
    "Give only one piece of information at a time, keep it very short, and don't give more than asked for. "
    "Do not invent facts. If asked about info not in context, say you don't know. "
    "Avoid giving diagnoses or lab values unless context includes them. "
    "If the user greets you (e.g., 'hi'/'hello'), respond like a patient with a brief Hi."
)

ATTENDING_SYSTEM = (
    "You are the *attending physician* supervising a resident in a simulation. "
    "Be concise, Socratic, and educational. Cite case context where relevant. "
    "In the EXAM phase, answer ONLY from exam context. If not available, advise what would typically be checked but mark as 'not provided in case'."
)

FINAL_SYSTEM = (
    "You are the attending delivering a final assessment. "
    "Compare the resident's diagnosis vs the assigned correct diagnosis. "
    "Use relevant quotes from chat (history/exam) and add short evidence bullets from trusted sources (PubMed preferred; also NIH/CDC/WHO/Mayo/JH). "
    "Keep tone supportive. Provide 3–6 citations max for information used towards your assessment."
)

ATTENDING_TREATMENT_KICKOFF = (
    "You are the attending physician supervising a resident. "
    "Ask the resident to propose an INITIAL TREATMENT PLAN for this specific patient. "
    "Prompt for: a structured treatment plan. Keep it concise and structured."
    #"Prompt for: diagnostics (including labs/imaging), initial management steps, medications with dosing/route, "
    #"consults, monitoring, and admission/disposition. Keep it concise and structured."
)

ATTENDING_TREATMENT_ASSESS_SYSTEM = (
    "You are the attending physician evaluating the resident’s proposed treatment plan for THIS patient. "
    "You must base your assessment ONLY on: (1) the chat/case context provided and (2) the evidence block provided, "
    "which is restricted to PubMed/NIH/CDC/WHO and major institutions (Mayo Clinic, Johns Hopkins). "
    "If evidence is insufficient or conflicting, say so explicitly.\n\n"
    "Deliverables:\n"
    "1) Brief strengths of the plan\n"
    "2) Gaps/risks (what to fix)\n"
    "3) Evidence-backed recommendations (with inline bracketed cites, e.g., [PubMed:PMID], [CDC], [NIH], [Mayo], [JHM])\n"
    "4) Clear verdict line starting with 'Assessment:'\n"
    "Avoid speculation beyond the evidence block."
)

ATTENDING_SUMMARY_SYSTEM = (
    "You are the attending concluding the encounter. Provide a concise teaching summary with headings:\n"
    "• Key History Points\n• Key Physical Exam Findings\n• Final Diagnosis & Why\n"
    "• Treatment Highlights (what to start/avoid)\n• 3 Teaching Pearls\n• 2 Common Pitfalls\n"
    "Cite trusted sources in brackets only if/when you reference them."
)


def _get_case(case_id=None):
    selected_case_id = case_id if case_id in CASES else DEFAULT_CASE_ID
    return selected_case_id, CASES[selected_case_id]


def _get_case_rag(case_id: str, phase: str) -> RAGService:
    key = (case_id, phase)
    if key in RAG_CACHE:
        return RAG_CACHE[key]

    case = CASES[case_id]
    pdf_path = case["history_pdf"] if phase == "history" else case["exam_pdf"]
    namespace = f"{_sanitize_namespace_part(case_id)}_{phase}"
    rag = RAGService(chroma_dir=chroma_dir, namespace=namespace)
    rag.ensure_index(pdf_path)
    RAG_CACHE[key] = rag
    return rag


def _get_or_create_session(session_id=None, case_id=None):
    resolved_case_id, _ = _get_case(case_id)

    if not session_id:
        session_id = str(uuid.uuid4())

    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "stage": "HISTORY",
            "case_id": resolved_case_id,
            "chat": [],   # list of {role, content}
            "hx_summary": "",
            "dx_candidate": ""
        }

    return session_id, SESSIONS[session_id]


@app.get('/api/cases')
def list_cases():
    return jsonify({
        "default_case_id": DEFAULT_CASE_ID,
        "cases": [
            {"id": case_id, "label": case["label"]}
            for case_id, case in CASES.items()
        ]
    })


@app.post('/api/session/start')
def start_session():
    payload = request.get_json(silent=True) or {}
    case_id = payload.get("case_id")
    session_id, data = _get_or_create_session(case_id=case_id)
    selected_case_id = data["case_id"]
    case = CASES[selected_case_id]
    return jsonify({
        "session_id": session_id,
        "case_id": selected_case_id,
        "case_label": case["label"],
    })


@app.post('/api/session/reset')
def reset_session():
    SESSIONS.clear()
    return jsonify({"ok": True})


# --- Patient (History) ---
@app.post('/api/patient/chat')
def patient_chat():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message", "")
    case_id = data["case_id"]

    # Retrieve context from case-specific history RAG
    rag_history = _get_case_rag(case_id, "history")
    context = rag_history.search(user_msg, k=4)

    sys = PATIENT_SYSTEM + f"\n\nCASE CONTEXT (history):\n{context}"
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role": "user", "content": user_msg}], temperature=0.4)
    data["chat"].append({"role": "user", "content": user_msg})
    data["chat"].append({"role": "assistant", "content": reply, "speaker": "patient"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "patient", "case_id": case_id})


# --- Attending workflow ---
@app.post('/api/attending/open')
def attending_open():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    data["stage"] = "HX_DISCUSS"
    prompt = (
        "I'm here. In one minute, summarize the key positives/negatives from history "
        "and tell me your top 2–3 diagnoses with rationale."
    )
    return jsonify({"session_id": session_id, "reply": prompt, "role": "attending"})


@app.post('/api/attending/history_discuss')
def attending_history_discuss():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message", "")
    sys = ATTENDING_SYSTEM + "\nYou are discussing the resident's initial differential based on HISTORY only."
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role": "user", "content": user_msg}], temperature=0.3)
    data["chat"].append({"role": "user", "content": user_msg})
    data["chat"].append({"role": "assistant", "content": reply, "speaker": "attending"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending"})


@app.post('/api/attending/exam_intro')
def attending_exam_intro():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    data["stage"] = "EXAM"
    intro = (
        "Let's focus on the physical exam. Ask me targeted questions. "
        "I will answer using the exam context for this case."
    )
    return jsonify({"session_id": session_id, "reply": intro, "role": "attending"})


@app.post('/api/attending/exam_chat')
def attending_exam_chat():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message", "")
    case_id = data["case_id"]

    rag_exam = _get_case_rag(case_id, "exam")
    context = rag_exam.search(user_msg, k=4)
    sys = ATTENDING_SYSTEM + f"\n\nCASE CONTEXT (exam):\n{context}"
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role": "user", "content": user_msg}], temperature=0.35)
    data["chat"].append({"role": "user", "content": user_msg})
    data["chat"].append({"role": "assistant", "content": reply, "speaker": "attending"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending"})


@app.post('/api/attending/final_prompt')
def attending_final_prompt():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    data["stage"] = "DX_DISCUSS"
    return jsonify({
        "session_id": session_id,
        "reply": "What's your leading diagnosis and 2–3 alternatives? Brief justification for each.",
        "role": "attending",
    })


@app.post('/api/attending/final_collect')
def attending_final_collect():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message", "")
    data["dx_candidate"] = user_msg

    recap = llm.chat(
        system="Summarize the salient history and exam facts from the following dialogue for the case. Be bullet-y and short.",
        messages=[{"role": "user", "content": "\n\n".join([m.get("content", "") for m in data["chat"]])}],
        temperature=0.0,
    )

    case = CASES[data["case_id"]]
    dx = case["assigned_diagnosis"]
    evidence = sources.find_evidence(dx, recap, max_items=5)

    final_reply = llm.chat(
        system=FINAL_SYSTEM,
        messages=[
            {"role": "user", "content": f"Resident final note: {user_msg}"},
            {"role": "user", "content": f"Assigned correct diagnosis: {dx}"},
            {"role": "user", "content": f"Case recap (history+exam):\n{recap}"},
            {
                "role": "user",
                "content": "External evidence (title + url each line):\n"
                + "\n".join([f"- {e['title']} — {e['url']}" for e in evidence]),
            },
        ],
        temperature=0.2,
    )

    data["stage"] = "FINAL"
    data["chat"].append({"role": "user", "content": user_msg})
    data["chat"].append({"role": "assistant", "content": final_reply, "speaker": "attending"})
    return jsonify({"session_id": session_id, "reply": final_reply, "role": "attending", "advance_to": "FINAL"})


@app.post('/api/attending/start_treatment')
def attending_start_treatment():
    payload = request.get_json() or {}
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))

    msg = llm.chat(system=ATTENDING_TREATMENT_KICKOFF, messages=data["chat"], temperature=0.2)
    data["chat"].append({"role": "assistant", "content": msg, "speaker": "attending"})
    data["stage"] = "TREATMENT"
    return jsonify({"session_id": session_id, "reply": msg, "role": "attending", "advance_to": "TREATMENT"})


@app.post('/api/attending/treatment_assess')
def attending_treatment_assess():
    payload = request.get_json() or {}
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))

    plan = payload.get("message", "").strip()
    data["chat"].append({"role": "user", "content": plan})

    case_ctx_parts = []
    for m in data["chat"]:
        if m.get("speaker") in ("patient", "attending"):
            case_ctx_parts.append(m["content"])
    case_context = "\n\n".join(case_ctx_parts[-12:])

    evidence_items = sources.gather_evidence(plan, max_items=6)
    evidence_block = "\n".join([f"- {e.get('title', '')} — {e.get('url', '')}" for e in evidence_items])

    system = (
        ATTENDING_TREATMENT_ASSESS_SYSTEM
        + f"\n\n--- CASE CONTEXT ---\n{case_context}\n\n--- EVIDENCE (trusted only) ---\n{evidence_block}\n"
    )
    reply = llm.chat(system=system, messages=[{"role": "user", "content": plan}], temperature=0.2)

    data["chat"].append({"role": "assistant", "content": reply, "speaker": "attending"})
    data["treatment_plan"] = plan
    data["treatment_assessment"] = reply
    data["stage"] = "FINAL"
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending", "advance_to": "FINAL"})


@app.post('/api/attending/final_followups')
def attending_final_followups():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message", "")
    sys = ATTENDING_SYSTEM + " You are now answering follow-up teaching questions after the final assessment."
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role": "user", "content": user_msg}], temperature=0.3)
    data["chat"].append({"role": "user", "content": user_msg})
    data["chat"].append({"role": "assistant", "content": reply, "speaker": "attending"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending"})


@app.post('/api/attending/finalize_encounter')
def attending_finalize_encounter():
    payload = request.get_json() or {}
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))

    summary = llm.chat(system=ATTENDING_SUMMARY_SYSTEM, messages=data["chat"], temperature=0.2)
    data["chat"].append({"role": "assistant", "content": summary, "speaker": "attending"})
    return jsonify({"session_id": session_id, "reply": summary, "role": "attending"})


# Static hosting for the single-page UI
@app.get('/')
def index():
    return app.send_static_file('index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
