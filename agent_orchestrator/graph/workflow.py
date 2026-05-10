"""Minimal LangGraph wiring (orchestration persistence lives in Postgres tables)."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph


class _DemoState(TypedDict):
    step: str


def _tick(state: _DemoState) -> _DemoState:
    # ASCII-only: Windows consoles often use cp1252 and choke on Unicode arrows.
    return {"step": state.get("step", "init") + "->done"}


def build_demo_graph():
    g = StateGraph(_DemoState)
    g.add_node("tick", _tick)
    g.set_entry_point("tick")
    g.add_edge("tick", END)
    return g.compile()
