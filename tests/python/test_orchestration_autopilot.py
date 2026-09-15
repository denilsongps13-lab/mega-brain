from engine.orchestration import Autopilot, QualityGate, SwarmRole


def test_roles_are_specialized():
    assert {r.value for r in SwarmRole} == {"planner", "executor", "tester", "reviewer", "security"}


def test_quality_gate_collects_failures_without_crashing():
    gate = QualityGate().add("ok", lambda: True).add("bad", lambda: {"ok": False, "error": "coverage"})
    results = gate.run()
    assert results[0].ok is True
    assert results[1].ok is False
    assert results[1].detail == "coverage"


def test_quality_gate_catches_exception():
    def boom():
        raise RuntimeError("lint failed")
    result = QualityGate().add("lint", boom).run()[0]
    assert result.ok is False
    assert "lint failed" in result.detail


def test_autopilot_repairs_until_success():
    calls = []
    def execute(objective):
        calls.append(objective)
        if len(calls) == 1:
            return {"success": False, "errors": ["tests failed"]}
        return {"success": True, "errors": []}
    result = Autopilot(execute).run("ship feature")
    assert result["success"] is True
    assert result["cycles"] == 2
    assert "tests failed" in calls[1]


def test_autopilot_is_bounded_to_three_cycles():
    result = Autopilot(lambda _: {"success": False, "errors": ["same cause"]}, max_cycles=99).run("x")
    assert result["success"] is False
    assert result["cycles"] == 3
