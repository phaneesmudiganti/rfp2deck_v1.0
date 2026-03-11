from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from rfp2deck.core.schemas import RFPUnderstanding, DeckPlan, TraceabilityReport, ExecutiveNarrative, SectionPlan

class AgentState(BaseModel):
    narrative: Optional[ExecutiveNarrative] = None
    rfp_text: str
    template_info: Dict[str, Any]
    retrieved_context: Optional[str] = None
    understanding: Optional[RFPUnderstanding] = None
    section_plan: Optional[SectionPlan] = None
    deck_plan: Optional[DeckPlan] = None
    pptx_path: Optional[str] = None
    report: Optional[TraceabilityReport] = None
    deck_mode: Optional[str] = None
    debug: Dict[str, Any] = {}
