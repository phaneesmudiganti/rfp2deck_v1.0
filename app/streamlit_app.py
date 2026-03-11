from __future__ import annotations

from pathlib import Path
import sys
import os
import streamlit as st

# Map Streamlit secrets to environment variables
for key in st.secrets:
    os.environ[key] = str(st.secrets[key])

# Ensure local package imports work when running via `streamlit run app/streamlit_app.py`
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rfp2deck.core.config import settings
from rfp2deck.core.logging import setup_logging
from rfp2deck.core.schemas import DeckPlan, TraceabilityReport
from rfp2deck.ingestion.pdf_parser import parse_pdf
from rfp2deck.ingestion.docx_parser import parse_docx
from rfp2deck.ingestion.deck_analyzer import analyze_pptx_template
from rfp2deck.rag.indexer import chunk_text, build_faiss_index, save_index, load_index
from rfp2deck.rag.retriever import retrieve
from rfp2deck.agent.graph import build_graph
from rfp2deck.agent.state import AgentState
from rfp2deck.rendering.pptx_renderer import render_deck_from_template
from rfp2deck.diagrams.generator import generate_diagram_png

setup_logging()
st.set_page_config(page_title="RFP → Proposal Deck Agent", layout="wide")
settings.ensure_dirs()

st.title("RFP → Proposal Deck Generator (Standard Template)")

# ----------------------------
# Session state defaults
# ----------------------------
st.session_state.setdefault("wizard_step", 1)  # 1,2,3
st.session_state.setdefault("deck_plan", None)
st.session_state.setdefault("report", None)
st.session_state.setdefault("tpl_path", None)
st.session_state.setdefault("rfp_paths", None)
st.session_state.setdefault("template_info", None)
st.session_state.setdefault("retrieved_context", None)
st.session_state.setdefault("diagrams_generated", False)  # ran generation at least once

# Embedded standard template path (no UI upload required)
STANDARD_TEMPLATE = PROJECT_ROOT / "templates" / "standard_proposal_template_v1.pptx"

# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    st.header("Settings")

    st.subheader("Deck Mode")
    deck_mode = st.radio(
        "Select Output Mode",
        options=["Bid Defense (Core Only)", "Full Proposal (Core + Appendix)"],
        index=0,
    )
    st.session_state.deck_mode = deck_mode
    st.caption(f"Selected mode: {deck_mode}")

    st.write("Models are configured via `.env`.")
    st.code(
        f"Reasoning model: {settings.model_reasoning}\n"
        f"Fast model: {settings.model_fast}\n"
        f"Embeddings: {settings.embeddings_model}"
    )

    enable_diagrams = st.checkbox("Enable diagram generation (guarded + approval)", value=True)
    diagram_model = st.text_input("Diagram model", value="gpt-image-1")
    diagram_size = st.selectbox("Diagram size", options=["1024x1024", "1024x768", "768x1024"], index=0)

    build_index = st.checkbox("Build/Update RAG index from uploaded reference text (optional)", value=False)
    st.caption("Tip: upload a TXT file of reusable assets/proposal boilerplates to build a quick index.")

    st.divider()
    st.caption("Template")
    if STANDARD_TEMPLATE.exists():
        st.success(f"Using embedded template: {STANDARD_TEMPLATE.name}")
    else:
        st.error("Embedded template missing. Ensure templates/standard_proposal_template_v1.pptx exists.")

    if st.button("Reset wizard", use_container_width=True):
        keys = [
            "wizard_step",
            "deck_plan",
            "report",
            "tpl_path",
            "rfp_paths",
            "template_info",
            "retrieved_context",
            "diagrams_generated",
        ]
        for k in keys:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

# ----------------------------
# Helpers
# ----------------------------
def save_upload(upload, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(upload.getvalue())
    return dest

def parse_rfp(path: Path) -> tuple[str, dict]:
    if path.suffix.lower() == ".pdf":
        parsed = parse_pdf(path)
        st.success(f"Parsed PDF ({parsed.page_count} pages).")
        return parsed.text, {"name": path.name, "type": "pdf", "pages": parsed.page_count}
    parsed = parse_docx(path)
    st.success(f"Parsed DOCX ({parsed.paragraph_count} paragraphs).")
    return parsed.text, {"name": path.name, "type": "docx", "paragraphs": parsed.paragraph_count}

def parse_rfps(paths: list[Path]) -> tuple[str, list[dict], int, int]:
    texts: list[str] = []
    summaries: list[dict] = []
    total_pages = 0
    total_paragraphs = 0
    for path in paths:
        st.info(f"Parsing {path.name}...")
        text, meta = parse_rfp(path)
        texts.append(text)
        summaries.append(meta)
        if meta.get("type") == "pdf":
            total_pages += int(meta.get("pages", 0))
        else:
            total_paragraphs += int(meta.get("paragraphs", 0))
    return "\n\n".join(texts), summaries, total_pages, total_paragraphs

def normalize_models(deck_plan, report):
    if isinstance(deck_plan, dict):
        deck_plan = DeckPlan.model_validate(deck_plan)
    if report is not None and isinstance(report, dict):
        report = TraceabilityReport.model_validate(report)
    return deck_plan, report

def count_diagrams(plan: DeckPlan):
    total = 0
    approved = 0
    for s in plan.slides:
        if s.diagram and s.diagram.image_path:
            total += 1
            if bool(s.diagram.approved):
                approved += 1
    return total, approved

def wizard_header(step: int):
    labels = ["Upload & Plan", "Diagrams & Approval", "Render & Download"]
    step = max(1, min(3, int(step)))
    idx = step - 1

    chips = []
    for i, name in enumerate(labels, start=1):
        if i < step:
            chips.append(f"✅ **{i}. {name}**")
        elif i == step:
            chips.append(f"🟦 **{i}. {name}**")
        else:
            chips.append(f"⬜ {i}. {name}")
    st.markdown(" | ".join(chips))
    st.progress(idx / 2.0)

    colA, colB, colC, colD = st.columns([1, 1, 1, 2])
    with colA:
        if st.button("← Back", disabled=(step == 1), use_container_width=True):
            st.session_state.wizard_step = max(1, step - 1)
            st.rerun()
    with colB:
        can_go_2 = st.session_state.deck_plan is not None
        if st.button("Go to Step 2", disabled=not can_go_2, use_container_width=True):
            st.session_state.wizard_step = 2
            st.rerun()
    with colC:
        can_go_3 = (st.session_state.deck_plan is not None) and (st.session_state.tpl_path is not None)
        if st.button("Go to Step 3", disabled=not can_go_3, use_container_width=True):
            st.session_state.wizard_step = 3
            st.rerun()
    with colD:
        st.caption("Tip: Streamlit reruns on every click — state is preserved in session_state.")

# Guard: if plan missing, force step 1
if st.session_state.deck_plan is None and st.session_state.wizard_step != 1:
    st.session_state.wizard_step = 1

wizard_header(st.session_state.wizard_step)
st.divider()

# ----------------------------
# STEP 1
# ----------------------------
if st.session_state.wizard_step == 1:
    st.subheader("Step 1 — Upload RFP and Generate Deck Plan (Standard Template)")

    c1, c2 = st.columns(2)
    with c1:
        rfp_files = st.file_uploader(
            "Upload RFP file(s) (PDF/DOCX)",
            type=["pdf", "docx"],
            key="rfp_step1",
            accept_multiple_files=True,
        )
    with c2:
        ref_txt = st.file_uploader("Optional: Reusable content (TXT) for RAG", type=["txt"], key="ref_step1")
        st.caption("Enable 'Build/Update RAG index' in sidebar to index this TXT.")

    with st.form("step1_form"):
        submitted = st.form_submit_button("Generate Plan (Step 1)", type="primary", use_container_width=True)

    if submitted:
        if not STANDARD_TEMPLATE.exists():
            st.error("Embedded template is missing. Please restore templates/standard_proposal_template_v1.pptx")
            st.stop()

        if not rfp_files:
            st.error("Please upload at least one RFP file (PDF or DOCX).")
            st.stop()

        # Save RFP uploads
        rfp_paths: list[Path] = []
        for rfp_file in rfp_files:
            rfp_paths.append(
                save_upload(rfp_file, settings.data_dir / "uploads" / f"rfp_{rfp_file.name}")
            )
        st.session_state.rfp_paths = [str(p) for p in rfp_paths]

        # Use embedded template (copy into data/uploads for reproducibility)
        tpl_copy = settings.data_dir / "uploads" / "tpl_standard_proposal_template_v1.pptx"
        tpl_copy.write_bytes(STANDARD_TEMPLATE.read_bytes())
        st.session_state.tpl_path = str(tpl_copy)

        rfp_text, rfp_summaries, total_pages, total_paragraphs = parse_rfps(rfp_paths)

        if rfp_summaries:
            st.markdown("**RFP upload summary**")
            rows = []
            for s in rfp_summaries:
                if s.get("type") == "pdf":
                    rows.append({"File": s["name"], "Type": "PDF", "Count": f'{s.get("pages", 0)} pages'})
                else:
                    rows.append({"File": s["name"], "Type": "DOCX", "Count": f'{s.get("paragraphs", 0)} paragraphs'})
            st.table(rows)
            st.caption(f"Totals: {total_pages} pages, {total_paragraphs} paragraphs")

        # Analyze template layouts/placeholders
        ti = analyze_pptx_template(tpl_copy)
        template_info = {
            "slide_layout_names": ti.slide_layout_names,
            "masters": ti.masters,
            "placeholder_map": ti.placeholder_map,
        }
        st.session_state.template_info = template_info
        st.info(f"Template analyzed: {len(ti.slide_layout_names)} layouts found.")

        # Optional RAG
        retrieved_context = None
        rag_dir = settings.data_dir / "indexes" / "default_rag"
        if ref_txt and build_index:
            ref_path = save_upload(ref_txt, settings.data_dir / "uploads" / f"ref_{ref_txt.name}")
            ref_text = ref_path.read_text(encoding="utf-8", errors="ignore")
            chunks = chunk_text(ref_text)
            rag = build_faiss_index(chunks)
            save_index(rag, rag_dir)
            st.success(f"Built RAG index with {len(chunks)} chunks.")

        if rag_dir.exists() and (rag_dir / "index.faiss").exists():
            rag = load_index(rag_dir)
            top = retrieve(rag, "reusable proposal content for this RFP", k=6)
            retrieved_context = "\n\n".join([f"[score={c.score:.3f}]\n{c.text}" for c in top])
            st.caption("Retrieved reusable context from local RAG index.")

        st.session_state.retrieved_context = retrieved_context

        # Run agent
        graph = build_graph()
        state = AgentState(rfp_text=rfp_text, template_info=template_info, retrieved_context=retrieved_context)
        state.deck_mode = st.session_state.get('deck_mode')

        final_state = graph.invoke(state)

        if isinstance(final_state, dict):
            deck_plan = final_state.get("deck_plan")
            report = final_state.get("report")
        else:
            deck_plan = getattr(final_state, "deck_plan", None)
            report = getattr(final_state, "report", None)

        if not deck_plan:
            st.error("Failed to produce a deck plan.")
            st.stop()

        deck_plan, report = normalize_models(deck_plan, report)

        st.session_state.deck_plan = deck_plan
        st.session_state.report = report
        st.session_state.diagrams_generated = False  # reset for new run

        # Advance
        st.session_state.wizard_step = 2 if enable_diagrams else 3
        st.success("Step 1 complete. Moving to next step…")
        st.rerun()

    if st.session_state.deck_plan:
        with st.expander("Deck Plan JSON (current session)"):
            st.json(st.session_state.deck_plan.model_dump())
        with st.expander("Traceability Report (current session)"):
            rep = st.session_state.report
            st.json(rep.model_dump() if rep else {})

# ----------------------------
# STEP 2
# ----------------------------
if st.session_state.wizard_step == 2:
    st.subheader("Step 2 — Generate Diagrams and Approve (Guarded)")

    # Diagnostics: show diagram prompt coverage on key slides
    plan = st.session_state.deck_plan
    if plan:
        with st.expander("Diagram Coverage (diagnostics)"):
            total = len(plan.slides)
            with_prompt = sum(1 for s in plan.slides if getattr(s, "diagram", None) is not None)
            st.write(f"Slides: {total} | With diagram prompts: {with_prompt}")
            missing = [f"{s.slide_id}: {s.title} ({s.archetype})" for s in plan.slides if getattr(s, "diagram", None) is None and (str(s.archetype).lower() in ['architecture','team'])]
            if missing:
                st.warning("Missing DiagramSpec on key slides (should be fixed in v4.5.5):")
                st.code("\n".join(missing))
            else:
                st.success("All key slides have diagram prompts.")


    if st.session_state.deck_plan is None:
        st.error("No deck plan found. Please complete Step 1.")
        st.stop()

    plan: DeckPlan = st.session_state.deck_plan

    if not enable_diagrams:
        st.info("Diagram generation disabled in sidebar. You can go to Step 3.")
        if st.button("Proceed to Step 3", type="primary", use_container_width=True):
            st.session_state.wizard_step = 3
            st.rerun()
        st.stop()

    has_diagram_specs = any((s.diagram is not None) for s in plan.slides)
    if not has_diagram_specs:
        st.warning("This plan did not propose any diagrams. You can proceed to Step 3.")
        if st.button("Proceed to Step 3", type="primary", use_container_width=True):
            st.session_state.wizard_step = 3
            st.rerun()
        st.stop()

    colL, colR = st.columns([1, 1])
    with colL:
        gen_clicked = st.button("Generate / Regenerate Diagrams", type="primary", use_container_width=True)
    with colR:
        st.caption("You can regenerate after changing diagram model/size in the sidebar.")

    if gen_clicked:
        diagrams_dir = settings.data_dir / "outputs" / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)

        made = 0
        for s in plan.slides:
            if not s.diagram:
                continue
            out_img = diagrams_dir / f"{s.slide_id}.png"
            try:
                generate_diagram_png(s.diagram.prompt, out_img, model=diagram_model, size=diagram_size)
                s.diagram.image_path = str(out_img)
                made += 1
            except Exception as e:
                st.warning(f"Diagram generation failed for {s.slide_id}: {e}")

        st.session_state.deck_plan = plan
        st.session_state.diagrams_generated = True
        st.success(f"Generated {made} diagram(s). Now approve below.")
        st.rerun()

    any_images = any((s.diagram and s.diagram.image_path) for s in plan.slides)
    if not any_images:
        st.info("No diagram images generated yet. Click **Generate / Regenerate Diagrams** above.")
        st.stop()

    st.markdown("### Diagram Review & Approval")

    with st.form("diagram_approvals_form"):
        for s in plan.slides:
            if not s.diagram or not s.diagram.image_path:
                continue

            st.markdown(
                f"""**{s.slide_id} — {s.title}**  
Kind: `{s.diagram.kind}`"""
            )

            img_path = Path(s.diagram.image_path)
            if img_path.exists():
                st.image(str(img_path), caption=s.diagram.prompt)

            s.diagram.approved = st.checkbox(
                f"Approve diagram for {s.slide_id}",
                value=bool(s.diagram.approved),
                key=f"approve_{s.slide_id}",
            )

        save = st.form_submit_button("Save approvals and continue", type="primary", use_container_width=True)

    if save:
        st.session_state.deck_plan = plan
        total, approved = count_diagrams(plan)
        st.success(f"Approvals saved ({approved}/{total}). Moving to Step 3…")
        st.session_state.wizard_step = 3
        st.rerun()

# ----------------------------
# STEP 3
# ----------------------------
if st.session_state.wizard_step == 3:
    st.subheader("Step 3 — Render PPTX and Download Outputs")

    if st.session_state.deck_plan is None or st.session_state.tpl_path is None:
        st.error("Missing required state. Please complete Step 1 first.")
        st.stop()

    plan: DeckPlan = st.session_state.deck_plan
    tpl_path = Path(st.session_state.tpl_path)

    total, approved = count_diagrams(plan)
    cols = st.columns(3)
    cols[0].metric("Slides", value=len(plan.slides))
    cols[1].metric("Diagrams generated", value=total)
    cols[2].metric("Diagrams approved", value=approved)

    if enable_diagrams and total > 0 and approved == 0:
        st.warning("No diagrams are approved. They will NOT be inserted into the PPTX.")

    render_now = st.button("Render PPTX", type="primary", use_container_width=True)

    if render_now:
        out_pptx = settings.data_dir / "outputs" / "generated_proposal.pptx"
        render_deck_from_template(plan, tpl_path, out_pptx)

        report_path = settings.data_dir / "reports" / "traceability.json"
        if st.session_state.report:
            report_path.write_text(st.session_state.report.model_dump_json(indent=2), encoding="utf-8")

        st.success("Rendered PPTX successfully.")

        with open(out_pptx, "rb") as f:
            st.download_button(
                "Download PPTX",
                data=f,
                file_name=out_pptx.name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )

        if report_path.exists():
            with open(report_path, "rb") as f:
                st.download_button(
                    "Download Traceability Report (JSON)",
                    data=f,
                    file_name=report_path.name,
                    mime="application/json",
                    use_container_width=True,
                )

    with st.expander("Deck Plan JSON (current session)"):
        st.json(plan.model_dump())
    rep = st.session_state.report
    with st.expander("Traceability Report (current session)"):
        st.json(rep.model_dump() if rep else {})
