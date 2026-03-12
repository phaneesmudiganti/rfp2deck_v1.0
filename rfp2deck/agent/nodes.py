from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from rfp2deck.agent.prompts import (
    DECK_PLAN_PROMPT,
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
    TraceabilityItem,
    TraceabilityReport,
)
from rfp2deck.llm.structured import response_as_schema
from rfp2deck.qa.coverage import build_traceability_report


def understand_rfp(state: AgentState) -> AgentState:
    prompt = RFP_UNDERSTAND_PROMPT.format(rfp_text=state.rfp_text[:120000])
    understanding = response_as_schema(prompt, RFPUnderstanding, reasoning_effort="high")
    state.understanding = understanding
    return state


# -----------------------------
# v3: quality enforcement helpers
# -----------------------------
REQUIRED_ARCHETYPES = [
    # (allowed archetype literal, slide title)
    ("Solution Overview", "Executive Summary"),
    ("Customer Context", "Our Understanding of the Objective"),
    ("Requirements", "Key Requirements & Success Criteria"),
    ("Solution Overview", "Solution Approach Overview"),
    ("Architecture", "Reference Architecture"),
    ("Delivery Plan", "Delivery Approach & Governance"),
    ("Timeline", "Implementation Roadmap"),
    ("Risks", "Risks & Mitigations"),
    ("Team", "Delivery Team"),
    ("Commercials", "Commercials"),
    ("Next Steps", "Next Steps"),
]


def _diagram_prompt(kind: str) -> str:
    if kind == "architecture":
        return (
            "Create a clean corporate Azure reference architecture diagram. "
            "Three horizontal layers: Channels/Consumers, Services/API, Data/Governance. "
            "Include labeled boxes: Entra ID, API Management, Event Hub, Data Lake, Purview, Key Vault. "
            "Use arrows for ingress/egress. White background. No logos."
        )
    if kind == "timeline":
        return (
            "Create a clean timeline diagram with 3 phases: MVP, Extension, Scale/Hardening. "
            "Add milestone markers M1–M6. White background. No logos."
        )
    if kind == "data_model":
        return (
            "Create a conceptual data domain diagram for a canonical learner profile. "
            "Boxes: Learner Identity, Skills, Credentials, Roles/Occupations, Proficiency, Activity/Signals, Consent/Provenance. "
            "Show relationships with arrows. White background. No logos."
        )
    return "Create a clean corporate diagram. White background. No logos."


def _appendix_arch_diagram(
    view_name: str, understanding: RFPUnderstanding | None = None
) -> DiagramSpec:
    """Create a professional enterprise-style diagram prompt for appendix architecture views."""
    context = ""
    if understanding:
        cust = (
            getattr(understanding, "customer_name", None)
            or getattr(understanding, "customer", None)
            or "Customer"
        )
        goal = getattr(understanding, "goal", None) or getattr(understanding, "summary", None) or ""
        if not goal:
            obj = getattr(understanding, "objectives", None)
            if isinstance(obj, list):
                goal = " / ".join([str(x) for x in obj[:3]])
            elif isinstance(obj, str):
                goal = obj
        context = f" Customer: {cust}. Goal: {str(goal).strip()[:240]}."
    return DiagramSpec(
        kind="architecture",
        prompt=(
            f"Create a clean, professional {view_name} diagram for an RFP proposal deck."
            f"{context} Use an enterprise consulting style: white background, crisp boxes/arrows, "
            f"clear labels, minimal text. Show major components and data/control flows. "
            f"Azure-first where relevant. No clutter."
        ),
        image_path=None,
        approved=False,
    )


def ensure_diagrams_for_key_slides(
    deck_plan: DeckPlan, understanding: RFPUnderstanding | None = None
) -> DeckPlan:
    """Guarantee that key slides carry DiagramSpec prompts so Step-2 can generate previews.
    Guarded approval remains required (approved defaults to False)."""

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
        arch = (getattr(s, "archetype", "") or "").strip().lower()
        title = (getattr(s, "title", "") or "").strip()

        if arch == "architecture" and getattr(s, "diagram", None) is None:
            view = title or "Architecture"
            s.diagram = DiagramSpec(
                kind="architecture",
                prompt=(
                    f"Create a clean, professional {view} diagram for {cust}. "
                    f"{('Context: ' + summary + '. ') if summary else ''}"
                    "Use enterprise consulting style: white background, crisp boxes/arrows, minimal text. "
                    "Show key components and labeled flows. Azure-first where relevant. No clutter."
                ),
                image_path=None,
                approved=False,
            )

        if arch == "team" and getattr(s, "diagram", None) is None:
            s.diagram = DiagramSpec(
                kind="org_chart",
                prompt=(
                    f"Create a professional team org chart for delivering the engagement for {cust}. "
                    "Show roles and accountability lanes: Executive Sponsor, Delivery Manager, Solution Architect, "
                    "Data Architect, Security Lead, DevOps/Platform Engineer, Data Engineer, QA, Business Analyst. "
                    "Use clean boxes and reporting/coordination arrows. White background. Minimal text."
                ),
                image_path=None,
                approved=False,
            )

    return deck_plan


def ensure_required_slides(deck_plan: DeckPlan) -> DeckPlan:
    """Ensure a professional bid-defense skeleton exists using allowed archetypes.
    Adds missing universally-required sections and creates a table-based acceptance criteria slide.
    """

    def _norm(s: str) -> str:
        return (s or "").strip().lower()

    def _has_archetype(archetype: str) -> bool:
        return any(_norm(s.archetype) == _norm(archetype) for s in deck_plan.slides)

    def _has_title_contains(substr: str) -> bool:
        sub = _norm(substr)
        return any(sub in _norm(s.title) for s in deck_plan.slides)

    def _add(
        archetype: str,
        title: str,
        bullets: List[str] | None = None,
        *,
        table: dict | None = None,
        notes: str | None = None,
        diagram: DiagramSpec | None = None,
    ):
        slide_id = "auto_" + _norm(title).replace("—", "-").replace("→", "-").replace(
            "(", ""
        ).replace(")", "").replace(" ", "_")
        deck_plan.slides.append(
            SlideSpec(
                slide_id=slide_id,
                title=title,
                archetype=archetype,
                bullets=bullets or [],
                table=table,
                notes=notes,
                diagram=diagram,
            )
        )

    # Title should exist
    if not _has_archetype("Title"):
        _add(
            "Title",
            "Proposal — Bid Defense",
            ["Prepared for: Customer", "Prepared by: HCL", "Date:"],
        )

    # Agenda (must be early)
    if not _has_archetype("Agenda"):
        _add(
            "Agenda",
            "Agenda",
            [
                "Executive Summary",
                "Customer Context",
                "Requirements & Success Criteria",
                "Solution Overview",
                "Architecture",
                "Delivery Plan & Timeline",
                "Risks",
                "Team",
                "Commercials",
                "Next Steps",
            ],
        )

    # Executive Summary (Solution Overview archetype)
    if not _has_title_contains("executive summary"):
        _add(
            "Solution Overview",
            "Executive Summary",
            [
                "Accelerate readiness with a governed canonical learner profile.",
                "De-risk delivery via contract-first schemas and milestone approvals.",
                "Embed security, privacy, and explainability from day one.",
                "Deliver implementation-ready artifacts, not theoretical designs.",
            ],
        )

    # Customer Context (at least 2 slides)
    cc_slides = [s for s in deck_plan.slides if _norm(s.archetype) == "customer context"]
    if len(cc_slides) == 0:
        _add(
            "Customer Context",
            "Pearson Objectives & Decision Drivers",
            [
                "What success looks like for SIE and Learner Data Profile initiatives.",
                "Key stakeholders, constraints, and decision criteria for approval.",
                "Operating assumptions and scope boundaries from the RFP.",
            ],
        )
        _add(
            "Customer Context",
            "Current Landscape & Constraints",
            [
                "Systems, data sources, and integration touchpoints impacting the LDP.",
                "Security, privacy, governance, and regulatory constraints.",
                "Risks/complexities to control early via contract-first approach.",
            ],
        )
    elif len(cc_slides) == 1:
        _add(
            "Customer Context",
            "Current Landscape & Constraints",
            [
                "Systems, data sources, and integration touchpoints impacting the LDP.",
                "Security, privacy, governance, and regulatory constraints.",
                "Risks/complexities to control early via contract-first approach.",
            ],
        )

    # Requirements: ensure an acceptance criteria table slide exists
    if not any((_norm(s.archetype) == "requirements" and s.table) for s in deck_plan.slides):
        _add(
            "Requirements",
            "Definition of Success — Acceptance Criteria & Evidence",
            bullets=[],
            table={
                "headers": [
                    "Acceptance Criterion",
                    "Evidence / Artifact",
                    "Approver",
                    "When",
                ],
                "rows": [
                    [
                        "Canonical LDP defined",
                        "Data model + glossary + conventions",
                        "Pearson SIE leads",
                        "M1/M2",
                    ],
                    [
                        "Contracts versioned",
                        "Schema registry + version policy",
                        "Architecture board",
                        "M2",
                    ],
                    [
                        "Security & privacy by design",
                        "Threat model + controls mapping",
                        "Security",
                        "M2/M3",
                    ],
                    [
                        "Implementation-ready outputs",
                        "HLD/LLD + reference patterns",
                        "Delivery owners",
                        "M3+ ",
                    ],
                ],
            },
            notes="Use this as the bid-defense success rubric; keep it crisp.",
        )

    # Ensure always-present sections
    if not _has_archetype("Architecture"):
        _add(
            "Architecture",
            "Reference Architecture Overview",
            ["End-to-end view of contract-first canonical model and integrations."],
            diagram=_diagram_prompt(
                "architecture",
                "End-to-end contract-first learner data profile reference architecture.",
            ),
        )
    if not _has_archetype("Delivery Plan"):
        _add(
            "Delivery Plan",
            "Delivery Plan & Governance",
            ["Phased delivery with milestone reviews, sign-offs, and change control."],
        )
    if not _has_archetype("Timeline"):
        _add(
            "Timeline",
            "Timeline & Milestones",
            ["High-level timeline for M1–M6 with review gates and decision points."],
        )
    if not _has_archetype("Risks"):
        _add(
            "Risks",
            "Risks & Mitigations",
            ["Key risks, mitigations, and governance controls."],
        )
    if not _has_archetype("Team"):
        _add(
            "Team",
            "Delivery Team",
            ["Program leadership, architecture, data governance, and security roles."],
        )
    if not _has_archetype("Commercials"):
        _add(
            "Commercials",
            "Commercials",
            [
                "Option A: Milestone-based fixed price",
                "Option B: T&M with capped milestones",
                "Option C: Outcome-based hybrid",
                "Assumptions: access, SMEs, environments, and approvals.",
            ],
        )
    if not _has_archetype("Next Steps"):
        _add(
            "Next Steps",
            "Next Steps",
            [
                "Confirm scope + milestones",
                "Agree governance + sign-off cadence",
                "Kickoff and mobilize team",
            ],
        )

    return deck_plan


def enforce_slide_budget(
    deck_plan: DeckPlan,
    min_slides: int = 14,
    max_slides: int = 18,
    deck_mode: str | None = None,
    understanding: RFPUnderstanding | None = None,
) -> DeckPlan:
    """Mode-aware sizing:
    - Bid Defense: clamp to 14–18 slides
    - Full Proposal: core (14–18) + appendix (10–20) including architecture deep dives.
    Appendix diagrams remain guarded (approved=False)."""

    def key(s: SlideSpec) -> str:
        return (s.archetype or "").strip().lower()

    deck_plan.slides = [
        s for s in deck_plan.slides if not (s.slide_id or "").startswith("divider_")
    ]

    if deck_mode and ("Full Proposal" in str(deck_mode) or str(deck_mode).startswith("Full")):
        core = deck_plan.model_copy(deep=True)
        core.slides = [s for s in deck_plan.slides]
        protected = {"title", "agenda", "team", "commercials", "next steps"}

        while len(core.slides) > max_slides:
            removed = False
            for i in range(len(core.slides) - 1, -1, -1):
                if key(core.slides[i]) not in protected:
                    core.slides.pop(i)
                    removed = True
                    break
            if not removed:
                break

        while len(core.slides) < min_slides:
            idx = len(core.slides) + 1
            core.slides.append(
                SlideSpec(
                    slide_id=f"core_support_{idx}",
                    title=f"Supporting Detail {idx}",
                    archetype="Content",
                    bullets=["Supporting detail for Q&A (core)."],
                    diagram=None,
                )
            )

        appendix: list[SlideSpec] = []

        views = [
            ("Functional Architecture", "Functional Architecture"),
            ("Application Architecture", "Application Architecture"),
            ("Technical Architecture", "Technical Architecture"),
            ("Data Architecture", "Data Architecture"),
        ]
        for title, view_name in views:
            appendix.append(
                SlideSpec(
                    slide_id="appendix_" + view_name.lower().replace(" ", "_"),
                    title=title,
                    archetype="Architecture",
                    bullets=[
                        "Deep-dive view to support technical Q&A.",
                        "Key components, responsibilities, and interfaces.",
                        "Operational/security/governance considerations.",
                    ],
                    diagram=_appendix_arch_diagram(view_name, understanding=understanding),
                )
            )

        core_ids = {s.slide_id for s in core.slides}
        extras = [s for s in deck_plan.slides if s.slide_id not in core_ids]
        prio = {
            "architecture": 0,
            "requirements": 1,
            "delivery plan": 2,
            "timeline": 3,
            "customer context": 4,
            "content": 5,
        }
        extras.sort(key=lambda s: prio.get(key(s), 99))

        for s in extras:
            if len(appendix) >= 20:
                break
            if any(
                (s.title or "").strip().lower() == (a.title or "").strip().lower() for a in appendix
            ):
                continue
            s2 = s.model_copy(deep=True) if hasattr(s, "model_copy") else s
            s2.slide_id = "appendix_" + (s2.slide_id or "extra")
            appendix.append(s2)

        while len(appendix) < 10:
            idx = len(appendix) + 1
            appendix.append(
                SlideSpec(
                    slide_id=f"appendix_support_{idx}",
                    title=f"Appendix — Supporting Detail {idx}",
                    archetype="Content",
                    bullets=["Additional backup material for Q&A."],
                    diagram=None,
                )
            )

        deck_plan.slides = core.slides + appendix
        return deck_plan

    protected = {"title", "agenda", "team", "commercials", "next steps"}

    while len(deck_plan.slides) > max_slides:
        removed = False
        for i in range(len(deck_plan.slides) - 1, -1, -1):
            if key(deck_plan.slides[i]) not in protected:
                deck_plan.slides.pop(i)
                removed = True
                break
        if not removed:
            break

    while len(deck_plan.slides) < min_slides:
        idx = len(deck_plan.slides) + 1
        deck_plan.slides.append(
            SlideSpec(
                slide_id=f"appendix_{idx}",
                title=f"Appendix — Supporting Detail {idx}",
                archetype="Content",
                bullets=["Additional supporting material for Q&A."],
                diagram=None,
            )
        )

    return deck_plan


def build_exec_narrative(state: AgentState) -> AgentState:
    prompt = EXEC_NARRATIVE_PROMPT.format(
        understanding_json=(
            state.understanding.model_dump_json(indent=2) if state.understanding else "{}"
        ),
        retrieved_context=(state.retrieved_context or "")[:12000],
    )
    narrative = response_as_schema(prompt, ExecutiveNarrative, reasoning_effort="high")
    state.narrative = narrative  # type: ignore[attr-defined]
    return state


def compress_deck_plan(state: AgentState) -> AgentState:
    if not state.deck_plan:
        return state
    prompt = SLIDE_COMPRESSION_PROMPT.format(
        deck_plan_json=state.deck_plan.model_dump_json(indent=2)
    )
    compressed = response_as_schema(prompt, DeckPlan, reasoning_effort="high")

    old_by_id = {s.slide_id: s for s in state.deck_plan.slides}
    for s in compressed.slides:
        old = old_by_id.get(s.slide_id)
        if old and old.diagram and s.diagram:
            s.diagram.image_path = old.diagram.image_path
            s.diagram.approved = old.diagram.approved

    state.deck_plan = compressed
    return state


def derive_sections(state: AgentState) -> AgentState:
    """Derive an RFP-specific section taxonomy (within 14–18 slides), including Team and Commercials."""
    understanding_json = (
        state.understanding.model_dump_json(indent=2) if state.understanding else "{}"
    )
    prompt = SECTION_PLAN_PROMPT.format(
        understanding_json=understanding_json,
        retrieved_context=(state.retrieved_context or "")[:12000],
    )
    section_plan = response_as_schema(prompt, SectionPlan, reasoning_effort="high")
    # Defensive clamp (in case model drifts)
    try:
        target = int(getattr(section_plan, "slide_count_target", 16) or 16)
    except Exception:
        target = 16
    section_plan.slide_count_target = max(14, min(18, target))
    state.section_plan = section_plan
    return state


def order_deck(deck_plan: DeckPlan) -> DeckPlan:
    """Order slides into a professional narrative. Keeps relative order within the same archetype."""
    order = [
        "Title",
        "Agenda",
        "Solution Overview",  # includes Executive Summary
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
    indexed.sort(key=lambda ix: (rank.get((ix[1].archetype or "").lower(), 999), ix[0]))
    deck_plan.slides = [s for _, s in indexed]
    return deck_plan


import re


def _strip_milestone_prefix(title: str) -> str:
    return re.sub(r"^M\d+\s*[—:-]\s*", "", title or "")


def _tighten_title(title: str, max_words: int = 10) -> str:
    t = (title or "").strip()
    if not t:
        return t
    words = t.split()
    if len(words) <= max_words:
        return t
    return " ".join(words[:max_words]).rstrip("—-:") + "…"


def _tighten_bullet(b: str, max_words: int = 14) -> str:
    s = " ".join(str(b).replace("\n", " ").split()).strip()
    if not s:
        return s
    if s.endswith("."):
        s = s[:-1]
    words = s.split()
    if len(words) <= max_words:
        return s
    return " ".join(words[:max_words]).rstrip("—-:") + "…"


def polish_deck_text(deck_plan: DeckPlan) -> DeckPlan:
    for sl in deck_plan.slides:
        sl.title = _tighten_title(_strip_milestone_prefix(sl.title), 10)
        bullets = sl.bullets or []

        # Executive Summary strengthening
        if sl.archetype == "Solution Overview" and "executive" in sl.title.lower():
            bullets = [
                "Accelerate SIE readiness with a governed canonical learner profile.",
                "De-risk delivery via contract-first schemas and milestone approvals.",
                "Embed security, privacy, and explainability from day one.",
                "Deliver implementation-ready artifacts, not theoretical designs.",
            ]

        max_bullets = 4
        if sl.archetype in ("Requirements", "Risks"):
            max_bullets = 5

        bullets = bullets[:max_bullets]
        sl.bullets = [_tighten_bullet(b, 14) for b in bullets if str(b).strip()]
    return deck_plan


def insert_section_dividers(deck_plan: DeckPlan) -> DeckPlan:
    """v4.4: Section dividers are disabled by default to stay within 14–18 slide bid-defense budget.
    (Section framing is handled via strong titles + first slide in each section.)"""
    return deck_plan


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
        understanding_json=(
            state.understanding.model_dump_json(indent=2) if state.understanding else "{}"
        ),
        narrative_json=narrative_json,
    )

    deck_plan = response_as_schema(prompt, DeckPlan, reasoning_effort="high")
    deck_plan = ensure_required_slides(deck_plan)
    deck_plan = order_deck(deck_plan)
    deck_plan = polish_deck_text(deck_plan)
    deck_plan = enforce_slide_budget(
        deck_plan, 14, 18, deck_mode=state.deck_mode, understanding=state.understanding
    )
    deck_plan = ensure_diagrams_for_key_slides(deck_plan, understanding=state.understanding)

    state.deck_plan = deck_plan
    return state


def qa_and_report(state: AgentState) -> AgentState:
    if not state.understanding or not state.deck_plan:
        return state
    report = build_traceability_report(state.understanding, state.deck_plan)
    state.report = report
    return state
