#!/usr/bin/env python3
"""Mega Brain Desktop Interface — dark modern chat UI with real runtime integration.

Usage:
    pythonw megabrain-ui.pyw          (normal — opens window, no console)
    python  megabrain-ui.pyw          (with console — debug / selftest)
    python  megabrain-ui.pyw --selftest  (headless: run hooks + exit 0/1)
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap: make sure engine is importable regardless of how this file is
# invoked (pythonw, python, double-click).  ``engine.paths.ROOT`` uses
# ``__file__`` internally but being explicit about sys.path doesn't hurt.
# ─────────────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent           # payload root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)  # nail cwd for npm / git operations run by the executor

# Dark palette
_BG      = "#0f1117"
_BG2     = "#1a1d27"
_BG3     = "#232733"
_FG      = "#e2e6ed"
_FG2     = "#8b8fa3"
_GREEN   = "#2ea043"
_YELLOW  = "#d29922"
_RED     = "#cf222e"
_CYAN    = "#3fb5b6"
_ACCENT  = "#5b7fff"
_INPUT_BG= "#171b24"
_PLACEHOLDER = "#555a6e"

PHASE_LABELS = {
    "thinking":   "Pensando...",
    "planning":   "Planejando...",
    "executing":  "Executando...",
    "validating": "Validando...",
}

# ═════════════════════════════════════════════════════════════════════════════
# Self-test mode (no GUI needed)
# ═════════════════════════════════════════════════════════════════════════════
def _selftest() -> None:
    """Run headless integration test for the engine hooks. Exit 0/1."""
    import tempfile, traceback
    from engine.executor.executor import execute_objective
    from engine.executor.context import load_project_context

    print("[selftest] verifying engine imports OK")

    # 1 — phase_observer
    phases: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="mb_ui_test_"))
    ok = True
    try:
        def _rec(name: str, payload):
            phases.append(name)

        class _Stub:
            kind = "stub"
            def plan(self, objective, ctx):
                return {"goal": objective, "steps": [
                    {"id": "s1", "action": "context", "params": {}},
                    {"id": "s2", "action": "write", "params": {"path": "ok.txt", "content": "x"}},
                ], "validation": "manual", "planner": "stub"}

        res = execute_objective("ui selftest", workspace=str(tmp), planner=_Stub(),
                               phase_observer=_rec, confirmer=lambda r: False)
        assert res["success"], f"execute failed: {res.get('errors')}"
        expected = ["thinking", "planning", "executing", "executing", "validating", "done"]
        assert phases == expected, f"phases={phases}"
        assert (tmp / "ok.txt").read_text(encoding="utf-8") == "x"
        print("[selftest] phase_observer .............. OK")

        # 2 — load_project_context
        ctx = load_project_context(str(_ROOT))
        assert ctx.get("python"), "python not detected"
        print("[selftest] project_context .............. OK")

        # 3 — provider status
        from engine.intelligence.pipeline.mce.llm_router import is_provider_available
        gemini = is_provider_available("gemini")
        groq   = is_provider_available("groq")
        print(f"[selftest] providers: gemini={gemini} groq={groq}")

        # 4 — memory persistence
        from engine.executor.memory import ProjectMemory
        mem = ProjectMemory(str(tmp))
        mem.record_task("selftest task", ok=True)
        state = mem.load()
        assert state["completed"][-1]["task"] == "selftest task"
        print("[selftest] memory persistence ........... OK")

        # 5 — permission confirmer wiring
        from engine.executor.permissions import PermissionGate
        calls: list[str] = []
        gate = PermissionGate(tmp, mode="ask", confirmer=lambda r: calls.append(r) or True)
        v = gate.check_step("delete", {"path": str(tmp / "sub" / "x.txt")})
        allowed, needs_confirm, reason = gate.decide(v)
        assert allowed is True and calls and "sub" in calls[-1]
        gate_deny = PermissionGate(tmp, mode="ask", confirmer=lambda r: False)
        allowed2, _, _ = gate_deny.decide(gate_deny.check_step("write", {"path": str(tmp / "y.txt")}))
        assert allowed2 is True  # write/run on safe paths is allowed, no confirm
        print("[selftest] permission confirmer .......... OK")

    except Exception:
        traceback.print_exc()
        ok = False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n[selftest] RESULT: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


# ═════════════════════════════════════════════════════════════════════════════
# Engine wrappers (called from worker thread, results via queue)
# ═════════════════════════════════════════════════════════════════════════════
def _worker_context(result_q: queue.Queue):
    try:
        from engine.executor.context import load_project_context
        ctx = load_project_context(str(_ROOT))
        result_q.put(("context", ctx))
    except Exception as exc:
        result_q.put(("context", {"error": str(exc)}))


def _worker_execute(objective: str, phase_q: queue.Queue, result_q: queue.Queue):
    try:
        from engine.executor.executor import execute_objective

        def observer(name: str, payload):
            phase_q.put((name, payload))

        def confirmer(reason: str) -> bool:
            ev, holder = threading.Event(), [False]
            phase_q.put(("__permission__", {"reason": reason, "event": ev, "holder": holder}))
            ev.wait(timeout=300)
            return bool(holder[0])

        res = execute_objective(
            objective,
            permission_mode="ask",
            phase_observer=observer,
            confirmer=confirmer,
        )
        result_q.put(("execute", res))
    except Exception as exc:
        result_q.put(("execute", {"success": False, "error": str(exc)}))


def _worker_save_keys(gemini: str, groq: str, result_q: queue.Queue):
    """Surgically update GEMINI_API_KEY / GROQ_API_KEY in .env (no values printed)."""
    try:
        env_path = _ROOT / ".env"
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        for key, val in (("GEMINI_API_KEY", gemini), ("GROQ_API_KEY", groq)):
            idx = next((i for i, l in enumerate(lines) if l.startswith(key + "=")), None)
            entry = f"{key}={val}"
            if idx is not None:
                lines[idx] = entry
            else:
                lines.append(entry)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Clear env cache so re-read picks up new values
        for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)
        result_q.put(("save_keys", {"ok": True}))
    except Exception as exc:
        result_q.put(("save_keys", {"ok": False, "error": str(exc)}))


def _worker_test_provider(provider: str, result_q: queue.Queue):
    try:
        from engine.intelligence.pipeline.mce.llm_router import _run_gemini, _run_groq
        run = _run_gemini if provider == "gemini" else _run_groq
        start = time.time()
        text = run(f"Say PONG only. No explanation.", max_output_tokens=20)
        elapsed = round(time.time() - start, 1)
        result_q.put(("test_provider", {"ok": True, "provider": provider, "elapsed": elapsed, "text": text}))
    except Exception as exc:
        result_q.put(("test_provider", {"ok": False, "provider": provider, "error": str(exc)}))


def _read_masked_key(env_var: str) -> tuple[bool, int]:
    """Return (has_key, length) without printing the value."""
    val = os.environ.get(env_var, "")
    if val:
        return True, len(val)
    # Re-read from .env file
    env_path = _ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(env_var + "="):
                    candidate = line.split("=", 1)[1].strip()
                    if candidate:
                        os.environ.setdefault(env_var, candidate)
                        return True, len(candidate)
        except OSError:
            pass
    return False, 0


def _read_env_value(env_var: str) -> str:
    """Read raw value from .env for Settings fields. NEVER printed to UI."""
    val = os.environ.get(env_var, "")
    if val:
        return val
    env_path = _ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(env_var + "="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return ""


# ═════════════════════════════════════════════════════════════════════════════
# Main Application
# ═════════════════════════════════════════════════════════════════════════════
class MegaBrainApp:
    """Dark tkinter GUI for the Mega Brain local runtime."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Mega Brain")
        self.root.configure(bg=_BG)
        self.root.geometry("960x720")
        self.root.minsize(760, 560)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._phase_q: queue.Queue = queue.Queue()
        self._result_q: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False

        self._chat_log: list[str] = []
        self._current_view = tk.StringVar(value="chat")
        self._views: dict[str, tk.Frame] = {}

        self._ctx: dict[str, Any] = {}
        self._status_labels: dict[str, tk.Label] = {}

        from engine import paths
        from neural_brain import load_settings
        self._animation_path = paths.DATA / "megabrain" / "ui-animation.json"
        self._animation_settings = load_settings(self._animation_path)
        self._build_ui()
        self.root.after(100, self._poll_queues)
        self.root.after(500, self._load_initial_status)

    # ──────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root

        # Top header
        hdr = tk.Frame(r, bg=_BG2, bd=0, highlightthickness=0)
        hdr.pack(fill=tk.X, side=tk.TOP)
        tk.Label(hdr, text="MEGA BRAIN", font=("Segoe UI", 16, "bold"),
                 fg=_FG, bg=_BG2, padx=16, pady=8).pack(side=tk.LEFT)
        self._status_labels["mb"] = self._badge(hdr, "● Mega Brain Online", _GREEN)
        self._status_labels["gemini"] = self._badge(hdr, "Gemini: ...", _FG2)
        self._status_labels["groq"] = self._badge(hdr, "Groq: ...", _FG2)
        self._status_labels["memory"] = self._badge(hdr, "Memoria: ...", _FG2)

        # Body: sidebar + content
        body = tk.Frame(r, bg=_BG, bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sb = tk.Frame(body, bg=_BG2, width=180, bd=0, highlightthickness=0)
        sb.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 1), pady=0)
        sb.pack_propagate(False)
        for label, key in [
            ("Nova tarefa", "chat"),
            ("Memoria", "memory"),
            ("Contexto", "context"),
            ("Status", "status"),
            ("Configuracoes", "settings"),
        ]:
            b = tk.Button(sb, text=label, font=("Segoe UI", 11), fg=_FG, bg=_BG2,
                          activeforeground=_ACCENT, activebackground=_BG3,
                          bd=0, anchor="w", padx=16, pady=8,
                          command=lambda k=key: self._switch_view(k))
            b.pack(fill=tk.X)

        # Content container
        self._content = tk.Frame(body, bg=_BG, bd=0, highlightthickness=0)
        self._content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_chat_view()
        self._build_memory_view()
        self._build_context_view()
        self._build_status_view()
        self._build_settings_view()
        self._switch_view("chat")

    def _badge(self, parent, text, color):
        lbl = tk.Label(parent, text=text, font=("Segoe UI", 10), fg=color,
                       bg=_BG2, padx=10, pady=6)
        lbl.pack(side=tk.LEFT)
        return lbl

    # ── Chat view ─────────────────────────────────────────────────────────
    def _build_chat_view(self):
        f = tk.Frame(self._content, bg=_BG, bd=0, highlightthickness=0)
        self._views["chat"] = f

        from neural_brain import NeuralBrain
        self._brain_canvas = tk.Canvas(f, bg=_BG, height=240, highlightthickness=0)
        self._brain_canvas.pack(fill=tk.X)
        self._brain = NeuralBrain(self._brain_canvas, self._animation_settings)
        self._chat_text = tk.Text(f, height=8, bg=_BG, fg=_FG, insertbackground=_FG,
                                  font=("Consolas", 11), wrap=tk.WORD,
                                  state=tk.DISABLED, padx=12, pady=12,
                                  highlightthickness=0, bd=0,
                                  selectbackground=_ACCENT)
        scroll = tk.Scrollbar(f, command=self._chat_text.yview)
        self._chat_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._chat_text.pack(fill=tk.BOTH, expand=True)

        self._chat_text.tag_configure("user", foreground=_CYAN, font=("Consolas", 11, "bold"))
        self._chat_text.tag_configure("system", foreground=_FG2)
        self._chat_text.tag_configure("phase", foreground=_YELLOW)
        self._chat_text.tag_configure("ok", foreground=_GREEN)
        self._chat_text.tag_configure("error", foreground=_RED)
        self._chat_text.tag_configure("title", foreground=_FG, font=("Consolas", 12, "bold"))

        # Input area
        inp = tk.Frame(f, bg=_BG, bd=0, highlightthickness=0)
        inp.pack(fill=tk.X, padx=12, pady=(4, 12))
        self._input = tk.Text(inp, bg=_INPUT_BG, fg=_FG, insertbackground=_FG,
                              font=("Segoe UI", 12), height=3, wrap=tk.WORD,
                              highlightthickness=1, highlightbackground=_BG3,
                              highlightcolor=_ACCENT, bd=0, padx=10, pady=8)
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", lambda e: "break")
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        self._send_btn = tk.Button(inp, text="EXECUTAR", font=("Segoe UI", 11, "bold"),
                                   fg=_FG, bg=_ACCENT, activeforeground="#fff",
                                   activebackground="#4a64d9", bd=0, padx=20, pady=10,
                                   command=self._send_task)
        self._send_btn.pack(side=tk.RIGHT, fill=tk.Y)
        self._placeholder_shown = True
        self._input.bind("<FocusIn>", self._clear_placeholder)
        self._input.bind("<FocusOut>", self._show_placeholder)
        self._input.bind("<Key>", self._on_key)
        self._show_placeholder()

    def _show_placeholder(self, event=None):
        if self._input.get("1.0", tk.END).strip() == "" and self._placeholder_shown:
            self._input.configure(fg=_PLACEHOLDER)
            self._input.insert("1.0", "O que voce quer que o Mega Brain faca?")
            self._input.tag_add("ph", "1.0", tk.END)

    def _clear_placeholder(self, event=None):
        if self._placeholder_shown:
            self._input.delete("1.0", tk.END)
            self._input.configure(fg=_FG)
            self._placeholder_shown = False

    def _on_key(self, event):
        if self._placeholder_shown and event.keysym not in ("Shift_L", "Shift_R"):
            self._clear_placeholder()

    def _on_enter(self, event):
        if event.state & 0x0001:  # Shift held → newline, not send
            return
        self._send_task()
        return "break"

    def _append_chat(self, text: str, tag: str = ""):
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.insert(tk.END, text + "\n", tag)
        self._chat_text.see(tk.END)
        self._chat_text.configure(state=tk.DISABLED)

    def _send_task(self):
        if self._running:
            return
        obj = self._input.get("1.0", tk.END).strip()
        if not obj or (obj == "O que voce quer que o Mega Brain faca?"):
            return
        self._input.delete("1.0", tk.END)
        self._input.configure(state=tk.DISABLED)
        self._send_btn.configure(state=tk.DISABLED, text="Executando...")
        self._append_chat(f"> {obj}", "user")
        self._running = True
        self._worker = threading.Thread(target=_worker_execute, args=(obj, self._phase_q, self._result_q), daemon=True)
        self._worker.start()

    # ── Memory view ───────────────────────────────────────────────────────
    def _build_memory_view(self):
        f = tk.Frame(self._content, bg=_BG, bd=0, highlightthickness=0)
        self._views["memory"] = f
        tk.Label(f, text="MEMORIA DO PROJETO", font=("Segoe UI", 14, "bold"),
                 fg=_FG, bg=_BG, anchor="w", padx=16, pady=10).pack(fill=tk.X)
        self._mem_text = tk.Text(f, bg=_BG, fg=_FG, font=("Consolas", 10), wrap=tk.WORD,
                                 state=tk.DISABLED, padx=16, pady=8, highlightthickness=0, bd=0)
        self._mem_text.pack(fill=tk.BOTH, expand=True)
        self._mem_text.tag_configure("title", foreground=_CYAN, font=("Consolas", 11, "bold"))
        self._mem_text.tag_configure("item", foreground=_FG)
        self._mem_text.tag_configure("dim", foreground=_FG2)
        btn = tk.Button(f, text="Atualizar", font=("Segoe UI", 10), fg=_FG, bg=_BG3,
                        activebackground=_ACCENT, bd=0, padx=12, pady=4,
                        command=self._refresh_memory)
        btn.pack(padx=16, pady=6, anchor="w")

    def _refresh_memory(self):
        self._mem_text.configure(state=tk.NORMAL)
        self._mem_text.delete("1.0", tk.END)
        self._mem_text.insert(tk.END, "Carregando...\n", "dim")
        self._mem_text.configure(state=tk.DISABLED)
        threading.Thread(target=self._load_memory, daemon=True).start()

    def _load_memory(self):
        try:
            from engine.executor.memory import ProjectMemory
            mem = ProjectMemory(str(_ROOT))
            state = mem.load()
            events = mem.recent_events(limit=30)
            md = mem.summary_markdown()
            self.root.after(0, self._render_memory, state, events, md)
        except Exception as exc:
            self.root.after(0, self._render_memory_error, str(exc))

    def _render_memory(self, state, events, md):
        self._mem_text.configure(state=tk.NORMAL)
        self._mem_text.delete("1.0", tk.END)
        self._mem_text.insert(tk.END, md + "\n\n", "item")
        if events:
            self._mem_text.insert(tk.END, "--- Eventos recentes ---\n", "title")
            for ev in events[-20:]:
                ts = ev.get("ts", "")[:16]
                kind = ev.get("kind", "")
                detail = ev.get("text") or ev.get("task") or ev.get("objective") or ev.get("error") or ""
                self._mem_text.insert(tk.END, f"  [{ts}] {kind}: {detail[:100]}\n", "item")
        self._mem_text.configure(state=tk.DISABLED)

    def _render_memory_error(self, msg):
        self._mem_text.configure(state=tk.NORMAL)
        self._mem_text.delete("1.0", tk.END)
        self._mem_text.insert(tk.END, f"Erro ao carregar memoria: {msg}\n", "error")
        self._mem_text.configure(state=tk.DISABLED)

    # ── Context view ──────────────────────────────────────────────────────
    def _build_context_view(self):
        f = tk.Frame(self._content, bg=_BG, bd=0, highlightthickness=0)
        self._views["context"] = f
        tk.Label(f, text="CONTEXTO", font=("Segoe UI", 14, "bold"),
                 fg=_FG, bg=_BG, anchor="w", padx=16, pady=10).pack(fill=tk.X)
        self._ctx_text = tk.Text(f, bg=_BG, fg=_FG, font=("Consolas", 10), wrap=tk.WORD,
                                 state=tk.DISABLED, padx=16, pady=8, highlightthickness=0, bd=0)
        self._ctx_text.pack(fill=tk.BOTH, expand=True)
        self._ctx_text.tag_configure("label", foreground=_CYAN)
        self._ctx_text.tag_configure("value", foreground=_FG)
        self._ctx_text.tag_configure("dim", foreground=_FG2)
        self._ctx_text.tag_configure("err", foreground=_RED)
        btn = tk.Button(f, text="Atualizar", font=("Segoe UI", 10), fg=_FG, bg=_BG3,
                        activebackground=_ACCENT, bd=0, padx=12, pady=4,
                        command=self._refresh_context)
        btn.pack(padx=16, pady=6, anchor="w")

    def _refresh_context(self):
        self._ctx_text.configure(state=tk.NORMAL)
        self._ctx_text.delete("1.0", tk.END)
        self._ctx_text.insert(tk.END, "Carregando...\n", "dim")
        self._ctx_text.configure(state=tk.DISABLED)
        threading.Thread(target=_worker_context, args=(self._result_q,), daemon=True).start()

    def _render_context(self, ctx):
        self._ctx = ctx
        t = self._ctx_text
        t.configure(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        if "error" in ctx:
            t.insert(tk.END, f"Erro: {ctx['error']}\n", "err")
        else:
            for label, key in [
                ("Projeto", "project"),
                ("Workspace", "workspace"),
                ("Git repo", "is_git_repo"),
                ("Branch", "branch"),
                ("Ultimo commit", "last_commit"),
                ("Arquivos alterados", "dirty_files"),
                ("Python", "python"),
                ("Memoria store", "store_dir"),
            ]:
                t.insert(tk.END, f"{label}: ", "label")
                t.insert(tk.END, f"{ctx.get(key, '-')}\n", "value")
            # Resume
            resume = ctx.get("resume", {})
            t.insert(tk.END, "\n--- Ultima tarefa ---\n", "label")
            t.insert(tk.END, f"Objetivo: {resume.get('last_objective') or '-'}\n", "value")
            t.insert(tk.END, f"Corrente: {resume.get('current_objective') or '-'}\n", "value")
            ns = resume.get("next_steps") or []
            if ns:
                t.insert(tk.END, "Proximos passos:\n", "label")
                for s in ns:
                    t.insert(tk.END, f"  - {s}\n", "value")
        t.configure(state=tk.DISABLED)

    # ── Status view ───────────────────────────────────────────────────────
    def _build_status_view(self):
        f = tk.Frame(self._content, bg=_BG, bd=0, highlightthickness=0)
        self._views["status"] = f
        tk.Label(f, text="STATUS DO RUNTIME", font=("Segoe UI", 14, "bold"),
                 fg=_FG, bg=_BG, anchor="w", padx=16, pady=10).pack(fill=tk.X)
        self._status_text = tk.Text(f, bg=_BG, fg=_FG, font=("Consolas", 10), wrap=tk.WORD,
                                    state=tk.DISABLED, padx=16, pady=8, highlightthickness=0, bd=0)
        self._status_text.pack(fill=tk.BOTH, expand=True)
        self._status_text.tag_configure("ok", foreground=_GREEN)
        self._status_text.tag_configure("off", foreground=_RED)
        self._status_text.tag_configure("label", foreground=_CYAN)
        self._status_text.tag_configure("dim", foreground=_FG2)
        btn = tk.Button(f, text="Atualizar", font=("Segoe UI", 10), fg=_FG, bg=_BG3,
                        activebackground=_ACCENT, bd=0, padx=12, pady=4,
                        command=self._refresh_status)
        btn.pack(padx=16, pady=6, anchor="w")

    def _refresh_status(self):
        self._status_text.configure(state=tk.NORMAL)
        self._status_text.delete("1.0", tk.END)
        self._status_text.insert(tk.END, "Verificando...\n", "dim")
        self._status_text.configure(state=tk.DISABLED)
        threading.Thread(target=_worker_context, args=(self._result_q,), daemon=True).start()

    def _render_status(self, ctx):
        self._ctx = ctx
        t = self._status_text
        t.configure(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        if "error" in ctx:
            t.insert(tk.END, f"Erro: {ctx['error']}\n", "off")
            t.configure(state=tk.DISABLED)
            return

        gemini = ctx.get("llm_gemini", False)
        groq   = ctx.get("llm_groq", False)
        llm_ok = ctx.get("llm_available", False)

        t.insert(tk.END, "Python: ", "label")
        t.insert(tk.END, f"{ctx.get('python', 'missing')}\n", "ok" if ctx.get("python") else "off")
        t.insert(tk.END, "Workspace: ", "label")
        t.insert(tk.END, f"{ctx.get('root', '-')}\n", "ok" if ctx.get("workspace") else "off")
        t.insert(tk.END, "Git: ", "label")
        t.insert(tk.END, f"{'repo ativo' if ctx.get('is_git_repo') else 'sem repo'}\n", "dim")
        t.insert(tk.END, "Memoria store: ", "label")
        t.insert(tk.END, f"{ctx.get('store_dir', '-')}\n", "ok" if ctx.get("store_dir") else "off")
        t.insert(tk.END, "\n--- Provedores LLM ---\n", "label")
        t.insert(tk.END, f"Gemini: ", "label")
        t.insert(tk.END, f"{'Online' if gemini else 'Offline'}\n", "ok" if gemini else "off")
        t.insert(tk.END, f"Groq:   ", "label")
        t.insert(tk.END, f"{'Online' if groq else 'Offline'}\n", "ok" if groq else "off")
        t.insert(tk.END, f"Router: ", "label")
        t.insert(tk.END, f"{'ONLINE' if llm_ok else 'OFFLINE (deterministic)'}\n", "ok" if llm_ok else "off")
        t.configure(state=tk.DISABLED)
        self._update_header(ctx)

    def _update_header(self, ctx):
        gemini = ctx.get("llm_gemini", False)
        groq   = ctx.get("llm_groq", False)
        self._status_labels["gemini"].configure(
            text=f"Gemini: {'Online' if gemini else 'Offline'}",
            fg=_GREEN if gemini else _RED)
        self._status_labels["groq"].configure(
            text=f"Groq: {'Online' if groq else 'Offline'}",
            fg=_GREEN if groq else _RED)
        # Memory badge
        try:
            from engine.executor.memory import ProjectMemory
            mem = ProjectMemory(str(_ROOT))
            has = mem.load().get("updated_at") is not None
            self._status_labels["memory"].configure(
                text=f"Memoria: {'Ativa' if has else 'Inativa'}",
                fg=_GREEN if has else _YELLOW)
        except Exception:
            self._status_labels["memory"].configure(text="Memoria: Erro", fg=_RED)

    # ── Settings view ─────────────────────────────────────────────────────
    def _build_settings_view(self):
        f = tk.Frame(self._content, bg=_BG, bd=0, highlightthickness=0)
        self._views["settings"] = f
        tk.Label(f, text="CONFIGURACOES", font=("Segoe UI", 14, "bold"),
                 fg=_FG, bg=_BG, anchor="w", padx=16, pady=10).pack(fill=tk.X)

        inner = tk.Frame(f, bg=_BG, padx=16, pady=8)
        inner.pack(fill=tk.X)

        from neural_brain import save_settings
        enabled = tk.BooleanVar(value=self._animation_settings['enabled'])
        reduced = tk.BooleanVar(value=self._animation_settings['reduce'])
        intensity = tk.StringVar(value=self._animation_settings['intensity'])
        def update_animation(*_):
            self._animation_settings.update(enabled=enabled.get(), reduce=reduced.get(), intensity=intensity.get())
            save_settings(self._animation_path, self._animation_settings)
        tk.Checkbutton(inner, text="Animacao neural", variable=enabled, command=update_animation,
                       bg=_BG, fg=_FG, selectcolor=_BG3).pack(anchor="w")
        tk.Checkbutton(inner, text="Reduce animations", variable=reduced, command=update_animation,
                       bg=_BG, fg=_FG, selectcolor=_BG3).pack(anchor="w")
        ttk.Combobox(inner, textvariable=intensity, values=("Low", "Medium", "High"),
                     state="readonly", width=12).pack(anchor="w")
        intensity.trace_add("write", update_animation)

        for label, env_var in [("GEMINI_API_KEY", "GEMINI_API_KEY"), ("GROQ_API_KEY", "GROQ_API_KEY")]:
            tk.Label(inner, text=label + ":", font=("Segoe UI", 11, "bold"),
                     fg=_FG, bg=_BG).pack(anchor="w", pady=(8, 0))
            row = tk.Frame(inner, bg=_BG)
            row.pack(fill=tk.X, pady=2)
            entry = tk.Entry(row, font=("Consolas", 11), bg=_INPUT_BG, fg=_FG,
                             insertbackground=_FG, highlightthickness=1,
                             highlightbackground=_BG3, highlightcolor=_ACCENT,
                             bd=0, show="*", width=52)
            entry.pack(side=tk.LEFT, padx=(0, 8))
            # Store raw value in memory; show placeholder
            entry.insert(0, _read_env_value(env_var))
            if not _read_env_value(env_var):
                entry.configure(fg=_PLACEHOLDER, show="")
                entry.insert(0, "(vazio)")
                entry._placeholder = True
            else:
                entry._placeholder = False

            test_btn = tk.Button(row, text="Testar", font=("Segoe UI", 10), fg=_FG, bg=_BG3,
                                 activebackground=_ACCENT, bd=0, padx=10, pady=2,
                                 command=lambda p=env_var.split("_")[0].lower(): self._test_provider(p))
            test_btn.pack(side=tk.LEFT)
            setattr(self, f"_entry_{env_var.lower()}", entry)

        # Save button
        btn_row = tk.Frame(inner, bg=_BG)
        btn_row.pack(fill=tk.X, pady=(16, 0))
        tk.Button(btn_row, text="Salvar chaves", font=("Segoe UI", 11, "bold"),
                  fg="#fff", bg=_GREEN, activebackground="#269a38",
                  bd=0, padx=16, pady=6,
                  command=self._save_settings).pack(side=tk.LEFT)
        self._settings_status = tk.Label(btn_row, text="", font=("Segoe UI", 10),
                                         fg=_FG2, bg=_BG)
        self._settings_status.pack(side=tk.LEFT, padx=12)

    def _save_settings(self):
        entries = {}
        for env_var in ("GEMINI_API_KEY", "GROQ_API_KEY"):
            entry: tk.Entry = getattr(self, f"_entry_{env_var.lower()}")
            val = entry.get().strip()
            if getattr(entry, "_placeholder", False):
                val = ""
            entries[env_var] = val

        threading.Thread(target=_worker_save_keys,
                         args=(entries["GEMINI_API_KEY"], entries["GROQ_API_KEY"], self._result_q),
                         daemon=True).start()

    def _test_provider(self, provider: str):
        self._settings_status.configure(text=f"Testando {provider}...", fg=_YELLOW)
        threading.Thread(target=_worker_test_provider,
                         args=(provider, self._result_q), daemon=True).start()

    # ── View switching ────────────────────────────────────────────────────
    def _switch_view(self, key: str):
        for child in self._content.winfo_children():
            child.pack_forget()
        view = self._views[key]
        view.pack(fill=tk.BOTH, expand=True)
        self._current_view.set(key)
        self._brain.visible = key == "chat"
        if key == "memory":
            self._refresh_memory()
        elif key == "context":
            self._refresh_context()
        elif key == "status":
            self._refresh_status()

    # ── Queue polling ─────────────────────────────────────────────────────
    def _poll_queues(self):
        # Permission dialog
        try:
            while True:
                name, payload = self._phase_q.get_nowait()
                if name == "__permission__" and payload:
                    self._show_permission_dialog(payload)
                elif name in PHASE_LABELS:
                    self._brain.set_state(name)
                    self._append_chat(f"  {PHASE_LABELS[name]}", "phase")
                elif name == "done":
                    pass  # handled via result_q
        except queue.Empty:
            pass

        # Results
        try:
            while True:
                kind, data = self._result_q.get_nowait()
                if kind == "execute":
                    self._on_execute_done(data)
                elif kind == "context":
                    self._render_context(data)
                    self._render_status(data)
                elif kind == "save_keys":
                    if data.get("ok"):
                        self._settings_status.configure(text="Salvo com sucesso.", fg=_GREEN)
                        self._load_initial_status()
                    else:
                        self._settings_status.configure(text=f"Erro: {data.get('error')}", fg=_RED)
                elif kind == "test_provider":
                    prov = data.get("provider", "")
                    if data.get("ok"):
                        self._settings_status.configure(
                            text=f"{prov.upper()}: OK ({data.get('elapsed')}s)", fg=_GREEN)
                    else:
                        self._settings_status.configure(
                            text=f"{prov.upper()}: FALHOU — {data.get('error', '')[:80]}", fg=_RED)
        except queue.Empty:
            pass

        self.root.after(60, self._poll_queues)

    def _on_execute_done(self, data: dict):
        self._running = False
        self._input.configure(state=tk.NORMAL)
        self._send_btn.configure(state=tk.NORMAL, text="EXECUTAR")
        success = data.get("success", False)
        self._brain.set_state("COMPLETED" if success else "ERROR")
        errors = data.get("errors") or []
        report = data.get("report_markdown", "")
        planner = data.get("planner", "?")

        if success:
            self._append_chat("Concluido.", "ok")
        else:
            self._append_chat("Erro.", "error")

        self._append_chat(f"Planner: {planner}", "system")

        if errors:
            self._append_chat("Erros:", "error")
            for e in errors[:5]:
                self._append_chat(f"  - {e}", "error")
        if report:
            self._append_chat(report, "system")
        self._append_chat("", "system")

    def _show_permission_dialog(self, payload: dict):
        reason = payload.get("reason", "Acao perigosa detectada")
        ev = payload.get("event")
        holder = payload.get("holder")
        if ev is None or holder is None:
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Acao requer autorizacao")
        dlg.configure(bg=_BG2)
        dlg.geometry("480x220")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="Acao requer autorizacao", font=("Segoe UI", 14, "bold"),
                 fg=_YELLOW, bg=_BG2, pady=12).pack()
        tk.Label(dlg, text=reason[:200], font=("Segoe UI", 10),
                 fg=_FG, bg=_BG2, wraplength=440, padx=16, pady=8).pack()

        btn_row = tk.Frame(dlg, bg=_BG2)
        btn_row.pack(pady=12)

        def answer(v):
            holder[0] = v
            ev.set()
            dlg.destroy()

        tk.Button(btn_row, text="CANCELAR", font=("Segoe UI", 11), fg=_FG, bg=_BG3,
                  activebackground=_RED, bd=0, padx=20, pady=6,
                  command=lambda: answer(False)).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text="AUTORIZAR", font=("Segoe UI", 11, "bold"), fg="#fff", bg=_GREEN,
                  activebackground="#269a38", bd=0, padx=20, pady=6,
                  command=lambda: answer(True)).pack(side=tk.LEFT, padx=8)

    # ── Initial load ──────────────────────────────────────────────────────
    def _load_initial_status(self):
        threading.Thread(target=_worker_context, args=(self._result_q,), daemon=True).start()

    def _on_close(self):
        if self._running:
            if not messagebox.askokcancel("Sair", "Uma tarefa esta em execucao. Deseja sair mesmo?"):
                return
        self._brain.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ═════════════════════════════════════════════════════════════════════════════
# Entry
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        app = MegaBrainApp()
        app.run()
