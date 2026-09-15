from engine.orchestration import GuardianQA, Mission, MissionStatus, MissionStep, mission_from_execution


def test_guardian_verifies_success_with_evidence():
    mission = Mission(
        objective="ship safely",
        status=MissionStatus.RUNNING,
        steps=[MissionStep("tests", MissionStatus.VERIFIED, ["exit_code: 0"])],
        result={"success": True},
    )
    gate = GuardianQA().verify(mission)
    assert gate.ok is True
    assert gate.problems == ()


def test_guardian_rejects_missing_evidence():
    mission = Mission(
        objective="ship safely",
        steps=[MissionStep("tests", MissionStatus.VERIFIED)],
        result={"success": True},
    )
    gate = GuardianQA().verify(mission)
    assert gate.ok is False
    assert "tests: missing evidence" in gate.problems


def test_guardian_rejects_executor_failure_even_if_step_looks_verified():
    mission = Mission(
        objective="x",
        steps=[MissionStep("tests", MissionStatus.VERIFIED, ["exit_code: 0"])],
        result={"success": False},
    )
    gate = GuardianQA().verify(mission)
    assert gate.ok is False
    assert "executor did not report success" in gate.problems


def test_execution_conversion_uses_latest_attempt_and_verifies():
    result = {
        "success": True,
        "steps": [
            {"step_id": "tests", "action": "run_tests", "attempt": 1, "ok": False, "stderr": "failed"},
            {"step_id": "tests", "action": "run_tests", "attempt": 2, "ok": True, "exit_code": 0, "summary": "passed"},
        ],
    }
    mission = mission_from_execution("fix then test", result)
    assert mission.status is MissionStatus.VERIFIED
    assert len(mission.steps) == 1
    assert mission.steps[0].status is MissionStatus.VERIFIED
    assert any("passed" in item for item in mission.steps[0].evidence)


def test_execution_conversion_never_turns_failure_into_verified():
    result = {
        "success": False,
        "steps": [{"step_id": "tests", "ok": False, "exit_code": 1, "stderr": "boom"}],
    }
    mission = mission_from_execution("broken", result)
    assert mission.status is MissionStatus.FAILED
    assert GuardianQA().verify(mission).ok is False


def test_empty_success_is_not_verified():
    mission = mission_from_execution("nothing ran", {"success": True, "steps": []})
    assert mission.status is MissionStatus.FAILED
