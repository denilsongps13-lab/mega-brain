#!/usr/bin/env python3
from __future__ import annotations

"""Mega Brain desktop UI v4.

Keeps the V3 visual design/animation, but adds a desktop runtime bridge for
provider+memory health checks and surfaces concrete executor diagnostics instead
of the generic "Execução falhou" dialog.
"""

import importlib.util
import queue
import re
import sys
import tempfile
import shutil
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V3_PATH = Path(__file__).with_name("megabrain-ui-v3.pyw")
spec = importlib.util.spec_from_file_location("megabrain_ui_v3", V3_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Não foi possível carregar a interface V3: {V3_PATH}")
v3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v3)

from engine.executor import executor as executor_mod
from engine.executor.executor import TaskExecutor

_original_execute_objective = executor_mod.execute_objective
_original_run_step = TaskExecutor._run_step


def _quoted_note(objective: str) -> str:
    matches = re.findall(r'["“”\']([^"“”\']{1,500})["“”\']', objective)
    if matches:
        return matches[-1].strip()
    return "Mega Brain V3 funcionando"


def _is_desktop_health_objective(objective: str) -> bool:
    low = objective.lower()
    has_memory = "memória" in low or "memoria" in low or "memory" in low
    return "gemini" in low and "groq" in low and has_memory


class DesktopHealthPlanner:
    kind = "desktop-health"

    def plan(self, objective: str, context: dict) -> dict:
        note = _quoted_note(objective)
        return {
            "goal": objective,
            "planner": self.kind,
            "validation": "manual",
            "steps": [
                {"id": "provider-status", "action": "provider_status", "params": {}},
                {"id": "memory-before", "action": "memory_read", "params": {}},
                {"id": "memory-note", "action": "memory_note", "params": {"text": note}},
                {"id": "memory-after", "action": "memory_read", "params": {}},
            ],
        }


def _desktop_run_step(self: TaskExecutor, action: str, params: dict) -> dict:
    if action == "provider_status":
        try:
            from engine.intelligence.pipeline.mce.llm_router import is_provider_available

            gemini = bool(is_provider_available("gemini"))
            groq = bool(is_provider_available("groq"))
            return {
                "ok": True,
                "summary": f"Gemini={'online' if gemini else 'offline'}; Groq={'online' if groq else 'offline'}",
                "gemini": gemini,
                "groq": groq,
            }
        except Exception as exc:
            return {"ok": False, "error": f"provider status failed: {exc}"}
    if action == "memory_read":
        try:
            return {"ok": True, "memory": self.memory.load(), "summary": "memória lida com sucesso"}
        except Exception as exc:
            return {"ok": False, "error": f"memory read failed: {exc}"}
    if action == "memory_note":
        text = str(params.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "memory_note requires params.text"}
        try:
            state = self.memory.record_solution("desktop-note", text)
            return {"ok": True, "summary": f"nota salva: {text}", "memory": state}
        except Exception as exc:
            return {"ok": False, "error": f"memory note failed: {exc}"}
    return _original_run_step(self, action, params)


TaskExecutor._run_step = _desktop_run_step


def desktop_execute_objective(objective: str, *args, **kwargs):
    if _is_desktop_health_objective(str(objective)) and kwargs.get("planner") is None:
        kwargs["planner"] = DesktopHealthPlanner()
    return _original_execute_objective(objective, *args, **kwargs)


executor_mod.execute_objective = desktop_execute_objective


def _failure_text(result: dict) -> str:
    parts: list[str] = []
    err = result.get("error")
    if err:
        parts.append(str(err))
    errors = result.get("errors") or []
    for item in errors[:4]:
        text = str(item).strip()
        if text and text not in parts:
            parts.append(text)
    if not parts:
        for step in reversed(result.get("steps") or []):
            if not step.get("ok"):
                text = step.get("error") or step.get("reason") or step.get("stderr")
                if text:
                    parts.append(str(text))
                    break
    log_path = result.get("execution_log")
    if log_path:
        parts.append(f"Diagnóstico: {log_path}")
    return "\n\n".join(parts) if parts else "Execução falhou sem diagnóstico retornado."


def _success_text(result: dict) -> str:
    lines = ["Execução concluída com sucesso."]
    planner = result.get("planner")
    if planner:
        lines.append(f"Planner: {planner}")
    for step in result.get("steps") or []:
        summary = step.get("summary")
        if summary:
            lines.append(f"• {summary}")
    if len(lines) == 2 and result.get("report_markdown"):
        lines.append(str(result["report_markdown"])[:1600])
    return "\n".join(lines)[:2200]


class App(v3.App):
    def poll(self):
        try:
            while True:
                x = self.phase_q.get_nowait()
                name = x[0]
                if name == "permission":
                    _, reason, ev, holder = x
                    holder[0] = messagebox.askyesno(
                        "Mega Brain — Permissão", reason, parent=self.root
                    )
                    ev.set()
                    continue
                mapping = {
                    "thinking": v3.NeuralHero.THINKING,
                    "planning": v3.NeuralHero.PLANNING,
                    "executing": v3.NeuralHero.EXECUTING,
                    "validating": v3.NeuralHero.EXECUTING,
                    "done": v3.NeuralHero.DONE,
                    "error": v3.NeuralHero.ERROR,
                }
                self.brain.set_state(mapping.get(name, v3.NeuralHero.IDLE))
        except queue.Empty:
            pass

        try:
            while True:
                objective, res = self.result_q.get_nowait()
                ok = bool(res.get("success"))
                self.running = False
                self.runbtn.config(state=v3.tk.NORMAL, text="▶  EXECUTAR")
                self.brain.set_state(v3.NeuralHero.DONE if ok else v3.NeuralHero.ERROR)
                self.input.delete("1.0", "end")
                self.render_recent([
                    (objective, "Concluído" if ok else "Erro", v3.GREEN if ok else v3.RED)
                ])
                if ok:
                    messagebox.showinfo("Mega Brain", _success_text(res), parent=self.root)
                else:
                    messagebox.showerror("Mega Brain — Falha", _failure_text(res), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def selftest():
    # Keep the V3 executor/visual integration selftest.
    v3.selftest()

    # Regression: desktop-only memory actions must execute cleanly without API keys.
    td = Path(tempfile.mkdtemp(prefix="mb_ui_v4_"))
    store = td / ".data"
    try:
        class MemoryPlanner:
            kind = "v4-selftest"

            def plan(self, objective, context):
                return {
                    "goal": objective,
                    "planner": self.kind,
                    "validation": "manual",
                    "steps": [
                        {"id": "n", "action": "memory_note", "params": {"text": "Mega Brain V4 funcionando"}},
                        {"id": "r", "action": "memory_read", "params": {}},
                    ],
                }

        result = desktop_execute_objective(
            "desktop v4 selftest",
            workspace=str(td),
            store_root=str(store),
            planner=MemoryPlanner(),
            permission_mode="block",
        )
        assert result.get("success"), result
        assert any("Mega Brain V4 funcionando" in str(x) for x in result["memory"].get("solutions", []))
        print("MEGA BRAIN UI V4 SELFTEST: PASS")
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        App().run()
