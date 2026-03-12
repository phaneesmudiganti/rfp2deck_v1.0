from __future__ import annotations
from datetime import datetime
from typing import Dict, List
from rfp2deck.core.schemas import (
    RFPUnderstanding,
    DeckPlan,
    TraceabilityReport,
    TraceabilityItem,
)


def build_traceability_report(
    understanding: RFPUnderstanding, deck: DeckPlan
) -> TraceabilityReport:
    # Create map from req id -> slides mentioning it (via rfps refs).
    slide_refs = {}
    for s in deck.slides:
        for ref in s.rfps:
            slide_refs.setdefault(ref, []).append(s.slide_id)

    coverage: List[TraceabilityItem] = []
    uncovered = []
    for r in understanding.requirements:
        slides = slide_refs.get(r.id, [])
        coverage.append(
            TraceabilityItem(
                requirement_id=r.id, requirement_text=r.text, covered_on_slides=slides
            )
        )
        if r.priority == "must" and not slides:
            uncovered.append(r.id)

    return TraceabilityReport(
        deck_title=deck.deck_title,
        generated_at=datetime.utcnow().isoformat() + "Z",
        coverage=coverage,
        uncovered_requirements=uncovered,
    )
