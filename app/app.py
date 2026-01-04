import os
import uuid
import json
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
from app.rag import RAGService
from app.sources import EvidenceFinder
from app.llm import ChatLLM
from fpdf import FPDF


app = Flask(__name__, static_folder='../static', template_folder='../templates')
CORS(app)

# In-memory session store (swap to Redis/Flask-Session if you like)
SESSIONS = {}

# Initialize services
chroma_dir = os.getenv("CHROMA_DIR", ".chroma_db")
history_pdf = os.getenv("CASE_HISTORY_PDF", "./data/case_history.pdf")
exam_pdf = os.getenv("CASE_EXAM_PDF", "./data/case_exam.pdf")
assigned_dx = os.getenv("ASSIGNED_DIAGNOSIS", "Pneumonia")
cases_path = os.getenv("CASES_PATH", "./data/cases.json")
cases_dir = Path(os.getenv("CASES_DIR", "./data/cases"))

RAG_SERVICES = {}
CASES = {}
llm = ChatLLM()
sources = EvidenceFinder()

def _write_pdf(text: str, output_path: Path) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    safe_text = (text or "").encode("latin-1", "replace").decode("latin-1")
    for line in safe_text.splitlines():
        pdf.multi_cell(0, 8, line)
    pdf.output(str(output_path))

def _normalize_case_path(path_value: str) -> str:
    if not path_value:
        return ""
    return str(Path(path_value).resolve())

def _load_cases() -> None:
    cases_dir.mkdir(parents=True, exist_ok=True)
    CASES.clear()
    CASES["default"] = {
        "id": "default",
        "title": "Default case",
        "history_path": _normalize_case_path(history_pdf),
        "exam_path": _normalize_case_path(exam_pdf),
        "assigned_dx": assigned_dx
    }
    if not os.path.exists(cases_path):
        return
    try:
        with open(cases_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return
    for item in data:
        case_id = item.get("id")
        if not case_id or case_id == "default":
            continue
        CASES[case_id] = {
            "id": case_id,
            "title": item.get("title", f"Case {case_id}"),
            "history_path": _normalize_case_path(item.get("history_path")),
            "exam_path": _normalize_case_path(item.get("exam_path")),
            "assigned_dx": item.get("assigned_dx", "Not provided")
        }

def _save_cases() -> None:
    payload = []
    for case_id, case in CASES.items():
        if case_id == "default":
            continue
        payload.append({
            "id": case_id,
            "title": case.get("title"),
            "history_path": case.get("history_path"),
            "exam_path": case.get("exam_path"),
            "assigned_dx": case.get("assigned_dx", "Not provided")
        })
    with open(cases_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

def _get_case(case_id: str):
    return CASES.get(case_id) or CASES.get("default")

def _get_rag(case_id: str, namespace: str) -> RAGService:
    key = f"{case_id}:{namespace}"
    if key not in RAG_SERVICES:
        service = RAGService(chroma_dir=chroma_dir, namespace=f"{case_id}_{namespace}")
        case = _get_case(case_id)
        if namespace == "history":
            service.ensure_index(case.get("history_path"))
        else:
            service.ensure_index(case.get("exam_path"))
        RAG_SERVICES[key] = service
    return RAG_SERVICES[key]

_load_cases()
# Build indices if needed for default case
_get_rag("default", "history")
_get_rag("default", "exam")

PATIENT_SYSTEM = (
    "You are a *standardized patient* in a simulation. Answer ONLY using the provided case context and keep answers concise, short (1 sentence max) and realistic."
    "Do not invent facts. If asked about info not in context, say you don't know or weren't told. "
    "Avoid giving diagnoses or lab values unless context includes them."
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
    "Keep tone supportive. Provide 3–6 citations max."
)

ATTENDING_TREATMENT_KICKOFF = (
    "You are the attending physician supervising a resident. "
    "Ask the resident to propose an INITIAL TREATMENT PLAN for this specific patient. "
    "Prompt for: diagnostics (including labs/imaging), initial management steps, medications with dosing/route, "
    "consults, monitoring, and admission/disposition. Keep it concise and structured."
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

ATTENDING_FINAL_QA_SYSTEM = (
    "You are the attending answering follow-up TEACHING questions. "
    "You must limit answers to: (1) the chat/case context and (2) trusted evidence (PubMed/NIH/CDC/WHO/Mayo/JHM). "
    "If something is outside those sources or not supported, say 'Not enough evidence from allowed sources to answer.' "
    "Cite briefly in brackets when you use external evidence."
)

ATTENDING_SUMMARY_SYSTEM = (
    "You are the attending concluding the encounter. Provide a concise teaching summary with headings:\n"
    "• Key History Points\n• Key Physical Exam Findings\n• Final Diagnosis & Why\n"
    "• Treatment Highlights (what to start/avoid)\n• 3 Teaching Pearls\n• 2 Common Pitfalls\n"
    "Cite trusted sources in brackets only if/when you reference them."
)

def _get_or_create_session(session_id=None, case_id=None):
    if not session_id:
        session_id = str(uuid.uuid4())
    normalized_case_id = case_id if case_id in CASES else "default"
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "stage": "HISTORY",
            "chat": [],   # list of {role, content}
            "hx_summary": "",
            "dx_candidate": "",
            "case_id": normalized_case_id
        }
    elif case_id:
        SESSIONS[session_id]["case_id"] = normalized_case_id
    return session_id, SESSIONS[session_id]

@app.post('/api/session/start')
def start_session():
    payload = request.get_json(force=True) or {}
    case_id = payload.get("case_id") or "default"
    session_id, data = _get_or_create_session(case_id=case_id)
    return jsonify({"session_id": session_id, "case_id": data.get("case_id", "default")})

@app.post('/api/session/reset')
def reset_session():
    SESSIONS.clear()
    return jsonify({"ok": True})

# --- Patient (History) ---
@app.post('/api/patient/chat')
def patient_chat():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message","")
    # Retrieve context from history RAG
    context = _get_rag(data.get("case_id", "default"), "history").search(user_msg, k=4)
    sys = PATIENT_SYSTEM + f"\n\nCASE CONTEXT (history):\n{context}"
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role":"user","content":user_msg}], temperature=0.4)
    data["chat"].append({"role":"user","content":user_msg})
    data["chat"].append({"role":"assistant","content":reply, "speaker":"patient"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "patient"})

# --- Attending workflow ---
@app.post('/api/attending/open')
def attending_open():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    data["stage"] = "HX_DISCUSS"
    prompt = ("I'm here. In one minute, summarize the key positives/negatives from history "
              "and tell me your top 2–3 diagnoses with rationale.")
    return jsonify({"session_id": session_id, "reply": prompt, "role": "attending"})

@app.post('/api/attending/history_discuss')
def attending_history_discuss():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message","")
    # Use both chat so far + a history-focused coaching response
    sys = ATTENDING_SYSTEM + "\nYou are discussing the resident's initial differential based on HISTORY only."
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role":"user","content":user_msg}], temperature=0.3)
    data["chat"].append({"role":"user","content":user_msg})
    data["chat"].append({"role":"assistant","content":reply, "speaker":"attending"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending"})

@app.post('/api/attending/exam_intro')
def attending_exam_intro():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    data["stage"] = "EXAM"
    intro = ("Let's focus on the physical exam. Ask me targeted questions. "
             "I will answer using the exam context for this case.")
    return jsonify({"session_id": session_id, "reply": intro, "role": "attending"})

@app.post('/api/attending/exam_chat')
def attending_exam_chat():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message","")
    context = _get_rag(data.get("case_id", "default"), "exam").search(user_msg, k=4)
    sys = ATTENDING_SYSTEM + f"\n\nCASE CONTEXT (exam):\n{context}"
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role":"user","content":user_msg}], temperature=0.35)
    data["chat"].append({"role":"user","content":user_msg})
    data["chat"].append({"role":"assistant","content":reply, "speaker":"attending"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending"})

@app.post('/api/attending/final_prompt')
def attending_final_prompt():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    data["stage"] = "DX_DISCUSS"
    return jsonify({"session_id": session_id, "reply": "What's your leading diagnosis and 2–3 alternatives? Brief justification for each.", "role": "attending"})

@app.post('/api/attending/final_collect')
def attending_final_collect():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message","")
    data["dx_candidate"] = user_msg

    # Build a concise history/exam recap from chat so far
    recap = llm.chat(
        system="Summarize the salient history and exam facts from the following dialogue for the case. Be bullet-y and short.",
        messages=[{"role":"user","content":"\n\n".join([m.get("content","") for m in data["chat"]])}],
        temperature=0.0
    )

    # Evidence finder: fetch 3–6 references (PubMed first)
    case = _get_case(data.get("case_id", "default"))
    dx = case.get("assigned_dx", "Not provided")
    evidence = sources.find_evidence(dx, recap, max_items=5)

    # Final compare
    sys = FINAL_SYSTEM
    final_reply = llm.chat(
        system=sys,
        messages=[
            {"role":"user","content": f"Resident final note: {user_msg}"},
            {"role":"user","content": f"Assigned correct diagnosis: {dx}"},
            {"role":"user","content": f"Case recap (history+exam):\n{recap}"},
            {"role":"user","content": f"External evidence (title + url each line):\n" + "\n".join([f"- {e['title']} — {e['url']}" for e in evidence])}
        ],
        temperature=0.2
    )

    data["stage"] = "FINAL"
    data["chat"].append({"role":"user","content":user_msg})
    data["chat"].append({"role":"assistant","content":final_reply, "speaker":"attending"})
    return jsonify({"session_id": session_id, "reply": final_reply, "role": "attending", "advance_to": "FINAL"})

#---------------------------
#ADD: Start treatment plan (attending prompts the resident)
@app.post('/api/attending/start_treatment')
def attending_start_treatment():
    payload = request.get_json() or {}
    case_id = payload.get("case_id") or "default"
    session_id = payload.get("session_id") or str(uuid.uuid4())
    data = SESSIONS.setdefault(session_id, {"chat": [], "stage": "HISTORY", "case_id": case_id})
    data["case_id"] = case_id

    msg = llm.chat(
        system=ATTENDING_TREATMENT_KICKOFF,
        messages=data["chat"],
        temperature=0.2
    )
    data["chat"].append({"role": "assistant", "content": msg, "speaker": "attending"})
    data["stage"] = "TREATMENT"
    return jsonify({"session_id": session_id, "reply": msg, "role": "attending", "advance_to": "TREATMENT"})


#ADD: Resident submits plan -> attending evaluates using trusted sources only ---
@app.post('/api/attending/treatment_assess')
def attending_treatment_assess():
    payload = request.get_json() or {}
    case_id = payload.get("case_id") or "default"
    session_id = payload.get("session_id") or str(uuid.uuid4())
    data = SESSIONS.setdefault(session_id, {"chat": [], "stage": "HISTORY", "case_id": case_id})
    data["case_id"] = case_id

    plan = payload.get("message", "").strip()
    data["chat"].append({"role": "user", "content": plan})

    # Build a compact case context from the chat so far (patient + attending messages only)
    case_ctx_parts = []
    for m in data["chat"]:
        if m.get("speaker") in ("patient", "attending"):
            case_ctx_parts.append(m["content"])
    case_context = "\n\n".join(case_ctx_parts[-12:])  # last ~12 turns to keep prompt small

    # Gather trusted evidence (PubMed/NIH/CDC/WHO/Mayo/JHM)
    # EvidenceFinder handles domain restriction and PubMed lookups.
    evidence_items = sources.gather_evidence(plan, max_items=6)
    evidence_block = "\n".join([f"- {e.get('title','')} — {e.get('url','')}" for e in evidence_items])

    system = (
        ATTENDING_TREATMENT_ASSESS_SYSTEM +
        f"\n\n--- CASE CONTEXT ---\n{case_context}\n\n--- EVIDENCE (trusted only) ---\n{evidence_block}\n"
    )
    reply = llm.chat(system=system, messages=[{"role": "user", "content": plan}], temperature=0.2)

    data["chat"].append({"role": "assistant", "content": reply, "speaker": "attending"})
    data["treatment_plan"] = plan
    data["treatment_assessment"] = reply
    data["stage"] = "FINAL"  # move into open teaching Q&A
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending", "advance_to": "FINAL"})
#---------------------------

@app.post('/api/attending/final_followups')
def attending_final_followups():
    payload = request.get_json(force=True)
    session_id, data = _get_or_create_session(payload.get("session_id"), payload.get("case_id"))
    user_msg = payload.get("message","")
    sys = ATTENDING_SYSTEM + " You are now answering follow-up teaching questions after the final assessment."
    reply = llm.chat(system=sys, messages=data["chat"] + [{"role":"user","content":user_msg}], temperature=0.3)
    data["chat"].append({"role":"user","content":user_msg})
    data["chat"].append({"role":"assistant","content":reply, "speaker":"attending"})
    return jsonify({"session_id": session_id, "reply": reply, "role": "attending"})

#------------------------
# --- ADD: Finalize encounter (attending teaching wrap-up) ---
@app.post('/api/attending/finalize_encounter')
def attending_finalize_encounter():
    payload = request.get_json() or {}
    case_id = payload.get("case_id") or "default"
    session_id = payload.get("session_id") or str(uuid.uuid4())
    data = SESSIONS.setdefault(session_id, {"chat": [], "stage": "HISTORY", "case_id": case_id})
    data["case_id"] = case_id

    summary = llm.chat(system=ATTENDING_SUMMARY_SYSTEM, messages=data["chat"], temperature=0.2)
    data["chat"].append({"role": "assistant", "content": summary, "speaker": "attending"})
    return jsonify({"session_id": session_id, "reply": summary, "role": "attending"})

@app.post('/api/cases/list')
def list_cases():
    payload = []
    for case_id, case in CASES.items():
        payload.append({
            "id": case_id,
            "title": case.get("title", case_id)
        })
    return jsonify({"cases": payload})

@app.post('/api/cases/create')
def create_case():
    payload = request.get_json(force=True) or {}
    title = (payload.get("title") or "Custom case").strip()
    history_text = payload.get("history_text", "")
    exam_text = payload.get("exam_text", "")
    assigned_diagnosis = (payload.get("assigned_diagnosis") or "Not provided").strip()
    case_id = str(uuid.uuid4())
    case_path = cases_dir / case_id
    case_path.mkdir(parents=True, exist_ok=True)

    history_txt_path = case_path / "history.txt"
    exam_txt_path = case_path / "exam.txt"
    history_pdf_path = case_path / "history.pdf"
    exam_pdf_path = case_path / "exam.pdf"

    history_txt_path.write_text(history_text, encoding="utf-8")
    exam_txt_path.write_text(exam_text, encoding="utf-8")
    _write_pdf(history_text, history_pdf_path)
    _write_pdf(exam_text, exam_pdf_path)

    CASES[case_id] = {
        "id": case_id,
        "title": title,
        "history_path": str(history_txt_path.resolve()),
        "exam_path": str(exam_txt_path.resolve()),
        "assigned_dx": assigned_diagnosis
    }
    _save_cases()
    _get_rag(case_id, "history")
    _get_rag(case_id, "exam")

    return jsonify({
        "case": {"id": case_id, "title": title},
        "downloads": {
            "history_txt": f"/api/cases/{case_id}/history.txt",
            "exam_txt": f"/api/cases/{case_id}/exam.txt",
            "history_pdf": f"/api/cases/{case_id}/history.pdf",
            "exam_pdf": f"/api/cases/{case_id}/exam.pdf"
        }
    })

@app.get('/api/cases/<case_id>/<filename>')
def download_case_file(case_id, filename):
    case = _get_case(case_id)
    if not case or case.get("id") == "default":
        return jsonify({"error": "Case not found"}), 404
    case_path = cases_dir / case_id
    file_path = case_path / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(case_path, filename, as_attachment=True)
#------------------------
# Static hosting for the single-page UI
@app.get('/')
def index():
    return app.send_static_file('index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
