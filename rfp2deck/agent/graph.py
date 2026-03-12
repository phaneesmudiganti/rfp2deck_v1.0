from __future__ import annotations
from langgraph.graph import StateGraph, END
from rfp2deck.agent.state import AgentState
from rfp2deck.agent.nodes import (
    understand_rfp,
    derive_sections,
    plan_deck,
    qa_and_report,
)


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("understand_rfp", understand_rfp)
    g.add_node("derive_sections", derive_sections)
    g.add_node("plan_deck", plan_deck)
    g.add_node("qa_and_report", qa_and_report)

    g.set_entry_point("understand_rfp")
    g.add_edge("understand_rfp", "derive_sections")
    g.add_edge("derive_sections", "plan_deck")
    g.add_edge("plan_deck", "qa_and_report")
    g.add_edge("qa_and_report", END)
    return g.compile()
