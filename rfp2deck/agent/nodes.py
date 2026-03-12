from __future__ import annotations

"""
LangGraph node implementations for the RFP → Deck agent.

This module:
- Extracts an RFP understanding (structured)
- Builds an executive narrative spine
- Plans a deck (DeckPlan)
- Applies quality enforcement (required slides, ordering, text polish, diagrams)
- Produces a traceability report

Design goal: produce a consulting-grade bid-defense / full-proposal deck plan
that renders cleanly into a standardized template.
"""

import json
import re
from typing import List

from rfp2deck.agent.prompts import (
    DECK_PLAN_V2_PROMPT,
    EXEC_NARRATIVE_PROMPT,
    RFP_UNDERSTAND_PROMPT,
    SECTION_PLAN_PROMPT,
    SLIDE_COMPRESSION_PROMPT,
)
from rfp2deck.agent.state import AgentState
from rfp2deck.core.schemas import (
    DeckPlan,
    DiagramSpec,
    ExecutiveNarrative,
    RFPUnderstanding,
    SectionPlan,
    SlideSpec,
)
from rfp2deck.llm.structured import response_as_schema
from rfp2deck.qa.coverage import build_traceability_report


# -----------------------------
# Node 1: Understand the RFP
# -----------------------------
def understand_rfp(state: AgentState) -> AgentState:
    prompt = RFP_UNDERSTAND_PROMPT.format(rfp_text=state.rfp_text[:120000])
    state.understanding = response_as_schema(prompt, RFPUnderstanding, reasoning_effort="high")
    return state


# -----------------------------
# Node 2: Executive narrative
# -----------------------------
def build_executive_narrative(state: AgentState) -> AgentState:
    understanding_json = state.understanding.model_dump_json(indent=2) if state.understanding else "{}"
    prompt = EXEC_NARRATIVE_PROMPT.format(
        understanding_json=understanding_json,
        retrieved_context=(state.retrieved_context or "")[:12000],
    )
    state.narrative = response_as_schema(prompt, ExecutiveNarrative, reasoning_effort="high")
    return state


# -----------------------------
# Required slide skeleton
# -----------------------------
REQUIRED_ARCHETYPES: List[tuple[str, str]] = [
    # (allowed archetype literal, slide title)
    ("Solution Overview", "Executive Summary"),
    ("Customer Context", "Current State & Key Pain Points"),
    ("Customer Context", "Our Understanding of the Objective"),
    ("Requirements", "Key Requirements & Success Criteria"),
    ("Solution Overview", "Solution Approach Overview"),
    ("Architecture", "Reference Architecture"),
    ("Delivery Plan", "Delivery Approach & Governance"),
    ("Timeline", "Implementation Roadmap"),
    ("Risks", "Risks & Mitigations"),
    ("Team", "Proposed Delivery Team"),
    ("Commercials", "Commercials"),
    ("Next Steps", "Next Steps"),
]


def _tight_id(text: str) -> str:
    """Create a stable, safe identifier from free-form text."""
    t = (text or "").strip().lower()
    t = t.replace("—", "-").replace("→", "-")
    # Keep letters, numbers, underscore, hyphen, and space.
    t = re.sub(r"[^a-z0-9_\- ]+", "", t)
    t = t.replace(" ", "_")
    return t[:64] if len(t) > 64 else t


def _diagram_prompt(kind: str) -> str:
    if kind == "architecture":
        return (
            "Create a clean enterprise architecture diagram in consulting style. "
            "White background, crisp boxes/arrows, minimal text. "
            "Show layers (channels, services/API, data/governance) and labeled flows."
        )
    if kind == "timeline":
        return (
            "Create a clean roadmap timeline with phases and milestone markers. "
            "White background, crisp shapes, minimal text. No logos."
        )
    if kind == "data_model":
        return (
            "Create a clean conceptual data model diagram showing key entities/domains and relationships. "
            "White background, crisp boxes/arrows, minimal text. No logos."
        )
    if kind == "org":
        return (
            "Create a professional delivery team org chart. "
            "White background. Roles in boxes with reporting/coordination lines. Minimal text."
        )
    return "Create a clean corporate diagram. White background. No logos."


def _appendix_arch_diagram(view_name: str, understanding: RFPUnderstanding | None = None) -> DiagramSpec:
    """Appendix deep-dive diagrams (functional/application/technical/data)."""
    cust = "Customer"
    context = ""
    if understanding:
        cust = (
            getattr(understanding, "customer_name", None)
            or getattr(understanding, "customer", None)
            or "Customer"
        )
        summary = (
            getattr(understanding, "summary", None)
            or getattr(understanding, "problem_statement", None)
            or ""
        )
        summary = str(summary).strip()
        if summary:
            context = f" Context: {summary[:220]}."

    return DiagramSpec(
        kind="architecture",
        prompt=(
            f"Create a clean, professional {view_name} diagram for an RFP proposal deck for {cust}."
            f"{context} Use enterprise consulting style: white background, crisp boxes/arrows, "
            f"clear labels, minimal text. Show major components and flows. No clutter."
        ),
        image_path=None,
        approved=False,
    )


def ensure_diagrams_for_key_slides(deck_plan: DeckPlan, understanding: RFPUnderstanding | None = None) -> DeckPlan:
    """Ensure key slides always have DiagramSpec prompts so Step-2 can generate previews."""
    cust = "Customer"
    summary = ""
    if understanding:
        cust = (
            getattr(understanding, "customer_name", None)
            or getattr(understanding, "customer", None)
            or "Customer"
        )
        summary = (
            getattr(understanding, "summary", None)
            or getattr(understanding, "problem_statement", None)
            or ""
        )
        summary = str(summary).strip()

    for s in deck_plan.slides:
        archetype = (getattr(s, "archetype", "") or "").strip().lower()
        title = (getattr(s, "title", "") or "").strip()

        # Architecture visuals
        if archetype == "architecture" and getattr(s, "diagram", None) is None:
            view = title or "Architecture"
            s.diagram = DiagramSpec(
                kind="architecture",
                prompt=(
                    f"Create a clean, professional {view} diagram for {cust}. "
                    f"{('Context: ' + summary + '. ') if summary else ''}"
                    "Enterprise consulting style: white background, crisp boxes/arrows, minimal text. "
                    "Show key components and labeled flows. Azure-first where relevant. No clutter."
                ),
                image_path=None,
                approved=False,
            )

        # Team slide as an org/RACI visual
        if archetype == "team" and getattr(s, "diagram", None) is None:
            s.diagram = DiagramSpec(
                kind="org",
                prompt=(
                    f"Create a professional delivery team org chart for {cust}. "
                    "Include lanes/roles: Executive Sponsor, Engagement Lead, Delivery Manager, "
                    "Solution Architect, Application Architect, Data Architect, Security Lead, "
                    "DevOps/Platform, Developers, Data Engineers, QA, Business Analyst. "
                    "Use clean boxes and coordination arrows. White background. Minimal text."
                ),
                image_path=None,
                approved=False,
            )

        # Timeline slides should be visual if missing
        if archetype == "timeline" and getattr(s, "diagram", None) is None:
            s.diagram = DiagramSpec(
                kind="timeline",
                prompt=_diagram_prompt("timeline"),
                image_path=None,
                approved=False,
            )

    return deck_plan


def ensure_required_slides(deck_plan: DeckPlan) -> DeckPlan:
    """Ensure a consulting-grade skeleton exists using allowed archetypes."""
    def norm(x: str) -> str:
        return (x or "").strip().lower()

    def has_archetype(a: str) -> bool:
        return any(norm(s.archetype) == norm(a) for s in deck_plan.slides)

    def has_title_exact(title: str) -> bool:
        t = norm(title)
        return any(norm(s.title) == t for s in deck_plan.slides)

    def add_slide(
        archetype: str,
        title: str,
        bullets: List[str] | None = None,
        diagram: DiagramSpec | None = None,
        table: dict | None = None,
        notes: str | None = None,
    ) -> None:
        deck_plan.slides.append(
            SlideSpec(
                slide_id=f"auto_{_tight_id(title)}",
                title=title,
                archetype=archetype,
                bullets=bullets or [],
                diagram=diagram,
                table=table,
                notes=notes,
            )
        )

    # Title / Agenda if missing
    if not has_archetype("Title"):
        add_slide(
            "Title",
            "Proposal — Bid Defense",
            ["Prepared for: Customer", "Prepared by: HCL", "Date: "],
        )

    if not has_archetype("Agenda"):
        add_slide(
            "Agenda",
            "Agenda",
            [
                "Executive Summary",
                "Current State & Objectives",
                "Requirements & Success Criteria",
                "Solution Overview",
                "Architecture",
                "Delivery Plan & Roadmap",
                "Risks, Team, Commercials, Next Steps",
            ],
        )

    # Required archetype/title pairs
    for archetype, title in REQUIRED_ARCHETYPES:
        if not has_title_exact(title):
            bullets: List[str] = []
            diagram: DiagramSpec | None = None

            if title == "Executive Summary":
                bullets = [
                    "Outcome: accelerate delivery with governed target architecture and roadmap",
                    "Approach: milestone-based delivery with strong governance and risk control",
                    "Value: faster time-to-value, reduced delivery risk, audit-ready compliance",
                    "Next: align on scope, milestones, and decision points",
                ]
            elif title == "Current State & Key Pain Points":
                bullets = [
                    "Current constraints, operational friction, and delivery bottlenecks",
                    "Risk drivers: data, integration, security/compliance, and change impact",
                    "What must improve to meet business outcomes and timelines",
                ]
            elif title == "Reference Architecture":
                bullets = [
                    "Target architecture aligned to RFP scope and non-functional requirements",
                    "Secure integration and governance by design",
                    "Extensible foundation to support future capabilities",
                ]
                diagram = DiagramSpec(kind="architecture", prompt=_diagram_prompt("architecture"), image_path=None, approved=False)
            elif title == "Implementation Roadmap":
                bullets = [
                    "Phased milestones with measurable deliverables",
                    "Early de-risking: discovery, prototypes, and architecture decisions",
                    "Progressive hardening: security, performance, and operations readiness",
                ]
                diagram = DiagramSpec(kind="timeline", prompt=_diagram_prompt("timeline"), image_path=None, approved=False)
            elif title == "Proposed Delivery Team":
                bullets = [
                    "Balanced leadership + architecture + engineering + QA capability",
                    "Clear ownership and accountability across workstreams",
                    "Onshore/offshore mix aligned to delivery cadence and governance",
                ]
                diagram = DiagramSpec(kind="org", prompt=_diagram_prompt("org"), image_path=None, approved=False)
            elif title == "Commercials":
                bullets = [
                    "Commercial model aligned to scope, milestones, and governance",
                    "Transparent assumptions, dependencies, and change control",
                    "Commercial options available for delivery pace and risk profile",
                ]

            add_slide(archetype, title, bullets=bullets, diagram=diagram)

    return deck_plan


# -----------------------------
# Ordering + polish
# -----------------------------
def _is_exec_summary(slide: SlideSpec) -> bool:
    t = (getattr(slide, "title", "") or "").strip().lower()
    return t == "executive summary" or t.startswith("executive summary")


def _context_priority(title: str) -> int:
    t = (title or "").strip().lower()
    if "current state" in t or "pain" in t:
        return 0
    if "objective" in t or "understanding" in t:
        return 1
    return 2


def _arch_priority(title: str) -> int:
    t = (title or "").strip().lower()
    # If you generate appendix deep-dives, keep them in a sensible order
    if "functional" in t:
        return 0
    if "application" in t or "integration" in t:
        return 1
    if "technical" in t or "infrastructure" in t:
        return 2
    if "data" in t:
        return 3
    if "reference" in t:
        return 4
    return 5


def order_deck(deck_plan: DeckPlan) -> DeckPlan:
    """
    Order slides into a consulting narrative.

    Global archetype flow:
    Title → Agenda → Executive Summary → Context → Requirements → Solution → Architecture
    → Delivery → Timeline → Risks → Case Studies → Team → Commercials → Next Steps → Content

    Within archetypes, apply priorities (e.g., Current State first in Customer Context).
    """
    order = [
        "Title",
        "Agenda",
        "Solution Overview",
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

    indexed = list(enumerate(deck_plan.slides))

    def sort_key(ix):
        i, s = ix
        archetype = (getattr(s, "archetype", "") or "").lower()
        title = (getattr(s, "title", "") or "")

        base = rank.get(archetype, 999)

        # Special-case within Solution Overview: Exec Summary always first
        intra = 10
        if archetype == "solution overview":
            intra = 0 if _is_exec_summary(s) else 1

        # Customer Context: Current State → Objective → other
        if archetype == "customer context":
            intra = _context_priority(title)

        # Architecture: functional → application → technical → data → reference → other
        if archetype == "architecture":
            intra = _arch_priority(title)

        return (base, intra, i)

    indexed.sort(key=sort_key)
    deck_plan.slides = [s for _, s in indexed]
    return deck_plan


def _strip_milestone_prefix(title: str) -> str:
    return re.sub(r"^M\\d+\\s*[—:-]\\s*", "", title or "")


def _tighten_title(title: str, max_words: int = 10) -> str:
    t = (title or "").strip()
    if not t:
        return t
    words = t.split()
    if len(words) <= max_words:
        return t
    return " ".join(words[:max_words]).rstrip("—-:") + "…"


def _tighten_bullet(b: str, max_words: int = 14) -> str:
    s = " ".join(str(b).replace("\\n", " ").split()).strip()
    if not s:
        return s
    if s.endswith("."):
        s = s[:-1]
    words = s.split()
    if len(words) <= max_words:
        return s
    return " ".join(words[:max_words]).rstrip("—-:") + "…"


def polish_deck_text(deck_plan: DeckPlan) -> DeckPlan:
    """Apply consistent consulting edit rules."""
    for sl in deck_plan.slides:
        sl.title = _tighten_title(_strip_milestone_prefix(sl.title), 10)

        bullets = sl.bullets or []

        # Executive Summary: keep strong, consulting-style bullets
        if sl.archetype == "Solution Overview" and "executive" in (sl.title or "").lower():
            bullets = [
                "Accelerate delivery with a governed target architecture and roadmap",
                "De-risk execution via milestone-based delivery and decision gates",
                "Embed security, privacy, and compliance from day one",
                "Deliver implementation-ready artifacts, not theoretical designs",
            ]

        max_bullets = 4
        if sl.archetype in ("Requirements", "Risks"):
            max_bullets = 5

        bullets = bullets[:max_bullets]
        sl.bullets = [_tighten_bullet(b, 14) for b in bullets if str(b).strip()]

    return deck_plan


# -----------------------------
# Section plan (optional node)
# -----------------------------
def derive_sections(state: AgentState) -> AgentState:
    """Derive an RFP-specific section taxonomy (within 14–18 slides), incl. Team & Commercials."""
    understanding_json = state.understanding.model_dump_json(indent=2) if state.understanding else "{}"
    prompt = SECTION_PLAN_PROMPT.format(
        understanding_json=understanding_json,
        retrieved_context=(state.retrieved_context or "")[:12000],
    )
    section_plan = response_as_schema(prompt, SectionPlan, reasoning_effort="high")

    # Defensive clamp
    target = int(getattr(section_plan, "slide_count_target", 16) or 16)
    section_plan.slide_count_target = max(14, min(18, target))

    state.section_plan = section_plan
    return state


# -----------------------------
# Compression (optional node)
# -----------------------------
def compress_deck_plan(state: AgentState) -> AgentState:
    if not state.deck_plan:
        return state

    prompt = SLIDE_COMPRESSION_PROMPT.format(deck_plan_json=state.deck_plan.model_dump_json(indent=2))
    compressed = response_as_schema(prompt, DeckPlan, reasoning_effort="high")

    # Preserve diagram approvals/paths
    old_by_id = {s.slide_id: s for s in state.deck_plan.slides}
    for s in compressed.slides:
        old = old_by_id.get(s.slide_id)
        if old and old.diagram and s.diagram:
            s.diagram.image_path = old.diagram.image_path
            s.diagram.approved = old.diagram.approved

    state.deck_plan = compressed
    return state


# -----------------------------
# Node 3: Plan the deck
# -----------------------------
def plan_deck(state: AgentState) -> AgentState:
    ti = state.template_info or {}
    layout_names = ti.get("slide_layout_names", [])
    placeholder_map = ti.get("placeholder_map", {})

    narrative_json = "{}"
    if getattr(state, "narrative", None) is not None:
        narrative_json = state.narrative.model_dump_json(indent=2)  # type: ignore[attr-defined]

    prompt = DECK_PLAN_V2_PROMPT.format(
        layout_names=json.dumps(layout_names, ensure_ascii=False),
        placeholder_map=json.dumps(placeholder_map, ensure_ascii=False)[:6000],
        retrieved_context=(state.retrieved_context or "")[:12000],
        understanding_json=(state.understanding.model_dump_json(indent=2) if state.understanding else "{}"),
        narrative_json=narrative_json,
    )

    deck_plan = response_as_schema(prompt, DeckPlan, reasoning_effort="high")

    deck_plan = ensure_required_slides(deck_plan)
    deck_plan = order_deck(deck_plan)
    deck_plan = polish_deck_text(deck_plan)
    deck_plan = ensure_diagrams_for_key_slides(deck_plan, understanding=state.understanding)

    state.deck_plan = deck_plan
    return state


# -----------------------------
# Node 4: QA + Traceability
# -----------------------------
def qa_and_report(state: AgentState) -> AgentState:
    if not state.understanding or not state.deck_plan:
        return state
    state.report = build_traceability_report(state.understanding, state.deck_plan)
    return state