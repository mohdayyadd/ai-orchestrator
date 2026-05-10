from agent_orchestrator.graph.workflow import build_demo_graph


def test_demo_graph_runs() -> None:
    g = build_demo_graph()
    out = g.invoke({"step": "init"})
    assert out["step"] == "init->done"
