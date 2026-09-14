"""Report generation — human + machine readable run summaries."""
from __future__ import annotations

from typing import Any


def build_report(result: dict, context: dict) -> str:
    """Markdown summary of a completed executor run."""
    lines: list[str] = []
    lines.append("# Mega Brain — Run Report")
    lines.append(f"- **Project:** {context.get('project')} ({context.get('root')})")
    lines.append(f"- **Objective:** {result.get('objective')}")
    lines.append(f"- **Status:** {'OK' if result.get('success') else 'PARTIAL'}")
    lines.append(f"- **Planner:** {result.get('planner')}")
    validation = result.get("validation") or {}
    lines.append(f"- **Validation:** {validation.get('kind')} -> {validation.get('ok')}")
    lines.append("")
    lines.append("## Steps")
    for step in result.get("steps", []):
        status = "OK" if step.get("ok") else ("BLOCKED" if step.get("blocked") else "FAIL")
        lines.append(
            f"- `{step.get('step_id')}` [{status}] {step.get('action')}"
            + (f" :: {step.get('error') or step.get('reason') or ''}" if status != "OK" else "")
        )
        if step.get("action") == "diagnostics":
            for entry in step.get("diagnostics", []):
                if not entry.get("ok"):
                    lines.append(f"  - {entry.get('timestamp')} {entry.get('action')} attempt={entry.get('attempt')} exit={entry.get('exit_code')}: {entry.get('error')}")
    touched = [
        s.get("path")
        for s in result.get("steps", [])
        if s.get("action") in ("read", "write", "edit") and s.get("ok") and s.get("path")
    ]
    if touched:
        lines.append("")
        lines.append("## Files touched")
        lines += [f"- `{p}`" for p in dict.fromkeys(touched)]
    if result.get("errors"):
        lines.append("")
        lines.append("## Errors recorded")
        lines += [f"- `{e}`" for e in result["errors"][:10]]
    if result.get("next_steps"):
        lines.append("")
        lines.append("## Next steps")
        lines += [f"- {n}" for n in result["next_steps"][:10]]
    lines.append("")
    lines.append(f"**Execution log:** `{result.get('execution_log')}`")
    lines.append(f"**Memory:** `{result.get('memory_dir')}`")
    lines.append(f"**Tokens:** up to {result.get('max_attempts')} attempts per failure, "
                 "permission mode " + str(result.get("permission_mode")))
    return "\n".join(lines)


__all__ = ["build_report"]