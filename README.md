# RFP → Proposal Deck Agent (Streamlit + LangGraph + OpenAI)

A modular starter project that turns:
- an **RFP** in **PDF** or **DOCX**
- a **PowerPoint template/strawman** (**PPTX**)
- (optional) a reusable content **TXT** corpus for **RAG**

…into:
- a **generated proposal deck** (**PPTX**) rendered deterministically from your template
- a **traceability report** mapping RFP requirements → slides
- (optional) **generated diagrams**, inserted only after **human approval**

## What’s included in this version
- ✅ **Template placeholder binder** (per slide archetype) via `TemplateBinder`
- ✅ **Diagram generation module** + **guarded approval flow** (Streamlit review checkboxes)
- ✅ **Font/overflow detection** (heuristic) + auto font shrink-to-fit when writing text

---

## Project structure

```
rfp2deck_agent/
  app/
    streamlit_app.py                 # Streamlit UI (3-step flow)
  rfp2deck/
    core/
      config.py                      # Settings / env loading
      logging.py                     # Rich logging
      schemas.py                     # Pydantic schemas (Structured Outputs)
    ingestion/
      pdf_parser.py                  # PDF → text (PyMuPDF)
      docx_parser.py                 # DOCX → text (python-docx)
      deck_analyzer.py               # PPTX template analysis (layouts/placeholders)
    rag/
      embeddings.py                  # OpenAI embeddings
      indexer.py                     # chunking + FAISS index build/save/load
      retriever.py                   # top-k retrieval
    llm/
      openai_client.py               # OpenAI SDK client helper
      structured.py                  # Responses API call with strict JSON schema output
    agent/
      state.py                       # Agent state (Pydantic)
      prompts.py                     # Prompt templates
      nodes.py                       # Graph nodes
      graph.py                       # LangGraph compilation
    diagrams/
      generator.py                   # OpenAI image generation → PNG
    qa/
      coverage.py                    # requirement coverage / traceability report
      overflow.py                    # heuristic overflow detection + font fitting
    rendering/
      template_binder.py             # archetype → layout/placeholder binding
      pptx_renderer.py               # deterministic PPTX rendering (+ diagrams + fit-to-box)
  requirements.txt
  .env.example
  README.md
```

---

## Setup

### Requirements
- Python 3.10+ recommended
- OpenAI API key

### 1) Create and activate a virtual environment

**macOS/Linux**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```

### 3) Configure environment
```bash
cp .env.example .env
```

Edit `.env` and set:
- `OPENAI_API_KEY=...`
- (optional) model overrides:
  - `OPENAI_MODEL_REASONING=gpt-5.2`
  - `OPENAI_MODEL_FAST=gpt-5-mini`
  - `OPENAI_EMBEDDINGS_MODEL=text-embedding-3-large`
- (optional) app data directory:
  - `APP_DATA_DIR=.data`

---

## Run the app
```bash
streamlit run app/streamlit_app.py
```

---

## Using the UI (3-step flow)

### Step 1: Generate Plan
Upload:
- RFP (PDF/DOCX)
- Template deck (PPTX)
(Optional) reference content TXT for RAG

Click **Step 1: Generate Plan** to get:
- deck plan JSON (slides, archetypes, bullets)
- traceability report JSON

### Step 2: Generate Diagrams (preview)
If enabled in the sidebar:
- Click **Step 2: Generate Diagrams (preview)**
- Review generated images and **approve per slide**
- Only approved diagrams will be inserted into the final PPTX

### Step 3: Render PPTX
Click **Step 3: Render PPTX** to:
- render the deck using deterministic `python-pptx`
- apply fit-to-box font shrinking
- insert approved diagrams

Then download:
- `generated_proposal.pptx`
- `traceability.json`

---

## Template binder details
`rfp2deck/rendering/template_binder.py`:
- selects layouts by `layout_hint` (exact match) or archetype-based heuristics
- binds to template placeholders (title/body/picture) using placeholder indices

This avoids hardcoding coordinates when your template already provides consistent placeholders.

---

## Diagram generation & guardrails
- The agent can propose `diagram.prompt` for slides like **Architecture** or **Timeline**
- The generator creates PNGs under `.data/outputs/diagrams/`
- The UI enforces **explicit approval** via checkboxes
- The renderer inserts diagrams only when `diagram.approved == True`

---

## Font / overflow detection
Since `python-pptx` doesn’t have a real layout engine, the project uses a heuristic estimator:
- estimates line wrapping by box size + font size
- shrinks font until it likely fits (down to a minimum)

See `rfp2deck/qa/overflow.py`.

---

## Next upgrades (recommended)
- Add strict archetype→layout mapping per customer template variant
- Improve placeholder detection (use placeholder type constants)
- Add true overflow detection using server-side rendering (Office/LibreOffice)
- Add diagram “grammar” (fixed palette + node/edge schema) instead of free-form prompts
- Add auth, audit logs, and an evaluation harness with golden RFPs
