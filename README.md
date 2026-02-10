# Patient–Resident–Attending Chatbot (Flask + HTML/JS)

An educational website that simulates a clinical case in three phases:
1) **History**: You (resident) question the *patient*; answers come from a case history PDF using RAG.
2) **Attending (discussion + exam)**: You page the *attending*, state your impressions, then ask targeted questions about the physical exam; answers come from a second PDF using RAG.
3) **Final assessment**: You give your final differential; the attending confirms/denies against a preset diagnosis and provides evidence with citations (PubMed/NIH/CDC/WHO/Mayo/JH).

> **Disclaimer**: For education only. Not medical advice. Do not use for real patient care.

## Quickstart

```bash
# 1) Create and activate a venv (recommended)
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Configure environment
cp .env.example .env
# Edit .env to set OPENAI_API_KEY, PDFs, and ASSIGNED_DIAGNOSIS

# 4) Add your PDFs
#   - data/case_history.pdf  (patient history facts)
#   - data/case_exam.pdf     (physical exam facts)

# 5) Run the server
flask --app app/app.py --debug run

# 6) Open the UI
# Visit http://127.0.0.1:5000
```

## How it works

- **RAG** with Chroma: PDFs are chunked and embedded; we search the most relevant chunks to ground the model.
- **Roles**: Two distinct system prompts—*Patient* (history) and *Attending* (exam/discussion).
- **Trusted sources**: For the final explanation we query PubMed via NCBI Entrez and optionally surface NIH/CDC/WHO/Mayo/JH pages.
- **Privacy**: All PDFs stay local; external queries are limited to literature/citations. You may disable external lookups in `.env`.

## Multiple cases (dropdown selector)

The app now supports multiple selectable cases via a UI dropdown and a backend case registry.

Create `data/cases.json` with one entry per case:

```json
{
  "cases": {
    "essential_tremor": {
      "label": "Essential Tremor",
      "history_pdf": "./data/case_history.pdf",
      "exam_pdf": "./data/case_exam.pdf",
      "assigned_diagnosis": "Essential Tremor"
    },
    "parkinsons": {
      "label": "Parkinson Disease",
      "history_pdf": "./data/parkinsons_history.pdf",
      "exam_pdf": "./data/parkinsons_exam.pdf",
      "assigned_diagnosis": "Parkinson Disease"
    }
  }
}
```

Notes:
- Each case needs separate history/exam PDFs.
- The frontend calls `GET /api/cases` to populate the dropdown.
- Starting or switching a case creates a fresh session scoped to that case.
- RAG indexes are built lazily per case/phase when first used.

