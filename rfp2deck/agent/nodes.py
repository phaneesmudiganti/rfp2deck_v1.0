from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from rfp2deck.agent.prompts import (
    DECK_PLAN_V2_PROMPT,
    EXEC_NARRATIVE_PROMPT,
    RFP_UNDERSTAND_PROMPT,
    SECTION_TAXONOMY_PROMPT,
)
from rfp2deck.agent.state import AgentState
from rfp2deck.core.schemas import (
    DeckPlan,
    DiagramSpec,
    ExecutiveNarrative,
    RFPUnderstanding,
    SectionTaxonomy,
    SlideSpec,
    TraceabilityReport,
)
from rfp2deck.llm.structured import response_as_schema
from rfp2deck.qa.coverage import build_traceability_report


def understand_rfp(state: AgentState) -> Dict[str, Any]:
    """Extract a structured understanding of the RFP."""
    prompt = RFP_UNDERSTAND_PROMPT.format(
        rfp_text=state.rfp_text or "",
        rag_context=state.rag_context or "",
    )
    understanding = response_as_schema(prompt, RFPUnderstanding, reasoning_effort="high")
    state.understanding = understanding
    return {"understanding": understanding}


def classify_sections(state: AgentState) -> Dict[str, Any]:
    """Classify RFP into section taxonomy for better subtitle generation & narrative."""
    prompt = SECTION_TAXONOMY_PROMPT.format(
        rfp_text=state.rfp_text or "",
        rag_context=state.rag_context or "",
    )
    section_map = response_as_schema(prompt, SectionTaxonomy, reasoning_effort="medium")
    state.section_map = section_map.model_dump()
    return {"section_map": state.section_map}


def build_narrative(state: AgentState) -> Dict[str, Any]:
    """Build an executive narrative spine for the proposal."""
    prompt = EXEC_NARRATIVE_PROMPT.format(
        understanding_json=state.understanding.model_dump() if state.understanding else {},
        rag_context=state.rag_context or "",
    )
    narrative = response_as_schema(prompt, ExecutiveNarrative, reasoning_effort="high")
    state.narrative = narrative
    return {"narrative": narrative}


def derive_sections(state: AgentState) -> Dict[str, Any]:
    """Back-compat wrapper for older graph wiring."""
    return classify_sections(state)


def _tight_id(text: str) -> str:
    """Create a stable, safe identifier from free-form text."""
    t = (text or "").strip().lower()
    t = t.replace("—", "-").replace("→", "-")
    # Keep letters, numbers, underscore, hyphen, and space.
    # IMPORTANT: Put '-' at the end of the character class to avoid any chance
    # of it being interpreted as a range (some environments accidentally ended
    # up with patterns like "\\-" which can break).
    t = re.sub(r"[^a-z0-9_ -]+", "", t)
    t = t.replace(" ", "_")
    return t[:64] if len(t) > 64 else t


def _appendix_arch_diagram(view_name: str, understanding: RFPUnderstanding) -> DiagramSpec:
    """Create a DiagramSpec for appendix architecture deep dives."""
    customer = getattr(understanding, "customer_name", None) or "Customer"
    # Some schema versions don't include 'goal' – keep this defensive.
    goal = getattr(understanding, "goal", None) or getattr(understanding, "business_objective", None) or ""
    context = f"Customer: {customer}. Goal: {str(goal).strip()[:240]}."
    prompt = (
        f"Create a clear, professional {view_name} architecture diagram.\n"
        f"{context}\n"
        "Style: consulting-grade, readable labels, minimal clutter, white background.\n"
        "Use 6–12 nodes max, grouped, with directional arrows.\n"
        "Add a short title inside the diagram.\n"
    )
    return DiagramSpec(
        prompt=prompt,
        approved=False,
        image_path=None,
    )


def _exec_summary_diagram_prompt(slide: SlideSpec) -> str:
    """Create a high-quality prompt for the Executive Summary 3-card graphic."""
    bullets = [b for b in (slide.bullets or []) if (b or "").strip()]
    # Map up to 3 bullets to the three cards; fall back to generic hints if missing.
    body_a = bullets[0] if len(bullets) > 0 else "Key opportunity and client context"
    body_b = bullets[1] if len(bullets) > 1 else "Recommended approach and solution highlights"
    body_c = bullets[2] if len(bullets) > 2 else "Expected business outcomes and impact"

    return (
        "Design a clean, consulting-style Executive Summary graphic with three equal cards.\n"
        "Cards (left to right) titled: OPPORTUNITY, RECOMMENDATION, BUSINESS IMPACT.\n"
        "Use the following body text exactly (no lorem ipsum, no placeholders):\n"
        f"- OPPORTUNITY: {body_a}\n"
        f"- RECOMMENDATION: {body_b}\n"
        f"- BUSINESS IMPACT: {body_c}\n"
        "Style: white background, subtle light-gray card borders, blue header bars, "
        "simple sans-serif font, left-aligned text, generous spacing.\n"
        "Do not add extra icons, charts, or decorative elements. No gradients or shadows. "
        "No hand-drawn or sketch effects. Keep text crisp and readable.\n"
        "Output a single slide-like image sized for 16:9."
    )


def ensure_required_slides(deck_plan: DeckPlan) -> DeckPlan:
    """Ensure required slides exist. Adds missing ones with sensible defaults."""
    existing = {(s.archetype or "").lower(): s for s in deck_plan.slides}
    # Helper: add slide
    def add_slide(
        archetype: str,
        title: str,
        bullets: Optional[List[str]] = None,
        diagram: Optional[DiagramSpec] = None,
    ) -> None:
        deck_plan.slides.append(
            SlideSpec(
                slide_id=f"auto_{_tight_id(title)}",
                title=title,
                archetype=archetype,
                bullets=bullets or [],
                diagram=diagram,
            )
        )

    # Title
    if "title" not in existing:
        add_slide(
            "Title",
            deck_plan.deck_title or "Proposal",
            bullets=[],
        )

    # Agenda
    if "agenda" not in existing:
        add_slide(
            "Agenda",
            "Agenda",
            bullets=[
                "Executive Summary",
                "Our Understanding",
                "Proposed Solution",
                "Architecture",
                "Delivery Plan & Timeline",
                "Commercials",
                "Team",
                "Next Steps",
            ],
        )

    # Exec Summary as Solution Overview (required)
    # (Some models output “Executive Overview” etc; ordering will still handle it.)
    has_exec = any(_is_exec_summary(s) for s in deck_plan.slides)
    if not has_exec:
        add_slide(
            "Solution Overview",
            "Executive Summary",
            bullets=[
                "Opportunity and key objectives",
                "Our recommended approach and solution highlights",
                "Business impact and expected outcomes",
            ],
            diagram=None,
        )

    # Customer Context
    if "customer context" not in existing:
        add_slide(
            "Customer Context",
            "Current State & Context",
            bullets=[
                "Current environment and constraints",
                "Key stakeholder needs and pain points",
                "Why change / why now",
            ],
        )

    # Requirements
    if "requirements" not in existing:
        add_slide(
            "Requirements",
            "Requirements Summary",
            bullets=[
                "Functional requirements (high level)",
                "Non-functional requirements (security, performance, availability)",
                "Success criteria and acceptance",
            ],
        )

    # Architecture
    if "architecture" not in existing:
        add_slide(
            "Architecture",
            "Target Architecture Overview",
            bullets=[
                "High-level component view and integrations",
                "Data flows and key interfaces",
                "Security and compliance considerations",
            ],
            diagram=DiagramSpec(
                prompt="Create a high-level target architecture diagram with components and integrations.",
                approved=False,
                image_path=None,
            ),
        )

    # Delivery Plan
    if "delivery plan" not in existing:
        add_slide(
            "Delivery Plan",
            "Delivery Model & Governance",
            bullets=[
                "Delivery approach (phased, agile, hybrid)",
                "Governance and stakeholder engagement",
                "Quality assurance and reporting cadence",
            ],
            diagram=DiagramSpec(
                prompt="Create a simple delivery governance diagram (client + vendor roles, steering, delivery squads).",
                approved=False,
                image_path=None,
            ),
        )

    # Timeline
    if "timeline" not in existing:
        add_slide(
            "Timeline",
            "Roadmap & Timeline",
            bullets=[
                "Phase 0: Mobilization",
                "Phase 1: Discovery & Design",
                "Phase 2: Build & Integrate",
                "Phase 3: Test & Launch",
                "Phase 4: Hypercare & Transition",
            ],
            diagram=DiagramSpec(
                prompt="Create a horizontal phase timeline (4–6 phases) with milestone icons and durations placeholders.",
                approved=False,
                image_path=None,
            ),
        )

    # Risks
    if "risks" not in existing:
        add_slide(
            "Risks",
            "Risks & Mitigations",
            bullets=[
                "Key delivery and technical risks",
                "Mitigation actions and owners",
                "Assumptions and dependencies",
            ],
        )

    # Team
    if "team" not in existing:
        add_slide(
            "Team",
            "Proposed Team",
            bullets=[
                "Engagement Lead — governance and stakeholder alignment",
                "Solution Architect — end-to-end design and quality",
                "Delivery Lead / PM — plan, cadence, RAID management",
                "Tech Lead(s) — build and integration",
                "QA Lead — test strategy and execution",
                "Data / Security SME — compliance and data controls",
            ],
            diagram=DiagramSpec(
                prompt=(
                    "Create a clean team org chart: Client (left) + Delivery team (right) with 6–10 roles, "
                    "showing reporting lines and key interfaces."
                ),
                approved=False,
                image_path=None,
            ),
        )

    # Commercials (always)
    if "commercials" not in existing:
        add_slide(
            "Commercials",
            "Commercials & Pricing",
            bullets=[
                "Commercial model options (T&M / Fixed / Hybrid)",
                "Assumptions and exclusions",
                "Options to accelerate timeline or reduce risk",
            ],
        )

    # Next Steps
    if "next steps" not in existing:
        add_slide(
            "Next Steps",
            "Next Steps",
            bullets=[
                "Confirm scope and success criteria",
                "Align on plan, governance, and resourcing",
                "Kick-off and mobilization",
            ],
        )

    return deck_plan


# --------------------------
# Ordering helpers
# --------------------------
def _is_exec_summary(slide: SlideSpec) -> bool:
    t = (getattr(slide, "title", "") or "").strip().lower()
    # Models sometimes emit variants like "Executive Overview" or "Summary & Recommendation".
    if t == "executive summary" or t.startswith("executive summary"):
        return True
    return (
        "executive overview" in t
        or "summary & recommendation" in t
        or "summary and recommendation" in t
        or ("executive" in t and "summary" in t)
    )


def order_deck(deck_plan: DeckPlan) -> DeckPlan:
    """Order slides into a consulting-style narrative. Keeps relative order within an archetype."""
    order = [
        "Title",
        "Agenda",
        "Solution Overview",  # Exec Summary lives here
        "Customer Context",
        "Requirements",
        "Architecture",
        "Delivery Plan",
        "Timeline",
        "Risks",
        "Case Studies",
        "Team",
        "Commercials",
        "Next Steps",
        "Content",
    ]
    rank = {a.lower(): i for i, a in enumerate(order)}

    def section_priority(slide: SlideSpec) -> int:
        # Within Solution Overview, force Exec Summary first.
        if (slide.archetype or "").lower() == "solution overview":
            return 0 if _is_exec_summary(slide) else 1
        # For Customer Context: prefer "Current State" before generic.
        if (slide.archetype or "").lower() == "customer context":
            t = (slide.title or "").lower()
            return 0 if "current" in t or "context" in t else 1
        return 0

    indexed = list(enumerate(deck_plan.slides))
    indexed.sort(
        key=lambda ix: (
            rank.get((ix[1].archetype or "").lower(), 999),
            section_priority(ix[1]),
            ix[0],
        )
    )
    deck_plan.slides = [s for _, s in indexed]
    return deck_plan


def polish_deck_text(deck_plan: DeckPlan) -> DeckPlan:
    """Light text normalization for a cleaner consulting tone."""
    for s in deck_plan.slides:
        if not s.bullets:
            continue
        new_bullets = []
        for b in s.bullets:
            t = (b or "").strip()
            t = t.replace("  ", " ")
            t = t.rstrip(".")
            if t:
                new_bullets.append(t)
        s.bullets = new_bullets[:8]  # keep crisp
    return deck_plan


def ensure_diagrams_for_key_slides(deck_plan: DeckPlan, understanding: RFPUnderstanding | None = None) -> DeckPlan:
    """Ensure diagrams exist (as guarded approvals) for key slides."""
    for s in deck_plan.slides:
        arch = (s.archetype or "").lower()
        title = (s.title or "").lower()

        if arch in {"architecture", "delivery plan", "timeline", "team", "solution overview"}:
            if s.diagram is None:
                prompt = ""
                if arch == "architecture":
                    prompt = "Create a high-level target architecture diagram with components, integrations, and data flow."
                elif arch == "delivery plan":
                    prompt = "Create a delivery governance diagram showing client & vendor roles, cadence, and escalation."
                elif arch == "timeline":
                    prompt = "Create a horizontal phase roadmap with 4–6 phases and milestone icons."
                elif arch == "team":
                    prompt = "Create a team org chart showing key roles (6–10) and reporting lines."
                elif arch == "solution overview":
                    if _is_exec_summary(s):
                        # Exec Summary is better rendered as native PPTX text, not an image.
                        prompt = ""
                    else:
                        prompt = "Create a solution overview diagram showing major building blocks and value streams."

                if prompt:
                    s.diagram = DiagramSpec(prompt=prompt, approved=False, image_path=None)
            elif arch == "solution overview" and _is_exec_summary(s):
                # Remove any legacy Exec Summary diagram to keep it text-native.
                s.diagram = None

        # Appendix architecture deep dives (if present as Content slides)
        if "appendix" in title and understanding is not None:
            if s.diagram is None:
                s.diagram = _appendix_arch_diagram("Appendix Overview", understanding)

    return deck_plan


def build_traceability(state: AgentState) -> Dict[str, Any]:
    """Build a traceability report mapping requirements to slides."""
    if state.understanding is None or state.deck_plan is None:
        return {"traceability_report": None}
    report = build_traceability_report(
        understanding=state.understanding,
        deck=state.deck_plan,
    )
    state.traceability_report = report
    return {"traceability_report": report}


def qa_and_report(state: AgentState) -> Dict[str, Any]:
    """Back-compat wrapper that stores report under the expected key."""
    if state.understanding is None or state.deck_plan is None:
        return {"report": None}
    report = build_traceability_report(
        understanding=state.understanding,
        deck=state.deck_plan,
    )
    state.report = report
    return {"report": report}


def plan_deck(state: AgentState) -> Dict[str, Any]:
    """Plan a deck from RFP + optional RAG context."""
    template_info = state.template_info or {}
    layout_names = template_info.get("slide_layout_names", [])
    placeholder_map = template_info.get("placeholder_map", {})
    understanding_json = (
        state.understanding.model_dump() if state.understanding is not None else {}
    )
    narrative_json = state.narrative.model_dump() if state.narrative is not None else {}

    prompt = DECK_PLAN_V2_PROMPT.format(
        layout_names=layout_names,
        placeholder_map=placeholder_map,
        rag_context=state.rag_context or "",
        understanding_json=understanding_json,
        narrative_json=narrative_json,
    )

    deck_plan = response_as_schema(prompt, DeckPlan, reasoning_effort="high")

    deck_plan = ensure_required_slides(deck_plan)
    deck_plan = order_deck(deck_plan)
    deck_plan = polish_deck_text(deck_plan)
    deck_plan = ensure_diagrams_for_key_slides(deck_plan, understanding=state.understanding)

    state.deck_plan = deck_plan
    return {"deck_plan": deck_plan}


def run(state: AgentState) -> Dict[str, Any]:
    """Entry point used by the LangGraph pipeline."""
    understand_rfp(state)
    classify_sections(state)
    plan_deck(state)
    build_traceability(state)
    return {
        "understanding": state.understanding,
        "deck_plan": state.deck_plan,
        "traceability_report": state.traceability_report,
        "section_map": state.section_map,
    }
