#!/usr/bin/env python3
"""Mega Brain Desktop Interface — dark modern chat UI with real runtime integration.

Usage:
    pythonw megabrain-ui.pyw          (normal — opens window, no console)
    python  megabrain-ui.pyw          (with console — debug / selftest)
    python  megabrain-ui.pyw --selftest  (headless: run hooks + exit 0/1)
"""
from __future__ import annotations

import json
import math
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

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

_ANIM_SETTINGS_FILE = ".data/megabrain/ui-animation.json"
_ANIM_DEFAULTS = {"enabled": True, "intensity": "medium", "reduce": False}


def _load_anim_settings() -> dict:
    try:
        p = _ROOT / _ANIM_SETTINGS_FILE
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            out = dict(_ANIM_DEFAULTS)
            out.update({k: data[k] for k in _ANIM_DEFAULTS if k in data})
            return out
    except Exception:
        pass
    return dict(_ANIM_DEFAULTS)


def _save_anim_settings(settings: dict) -> None:
    try:
        p = _ROOT / _ANIM_SETTINGS_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        pass


def _selftest() -> None:
    """Run headless integration test for the engine hooks. Exit 0/1."""
    import tempfile, traceback
    from engine.executor.executor import execute_objective
    from engine.executor.context import load_project_context

    print("[selftest] verifying engine imports OK")
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

        ctx = load_project_context(str(_ROOT))
        assert ctx.get("python"), "python not detected"
        print("[selftest] project_context .............. OK")

        from engine.intelligence.pipeline.mce.llm_router import is_provider_available
        gemini = is_provider_available("gemini")
        groq   = is_provider_available("groq")
        print(f"[selftest] providers: gemini={gemini} groq={groq}")

        from engine.executor.memory import ProjectMemory
        mem = ProjectMemory(str(tmp))
        mem.record_task("selftest task", ok=True)
        state = mem.load()
        assert state["completed"][-1]["task"] == "selftest task"
        print("[selftest] memory persistence ........... OK")

        from engine.executor.permissions import PermissionGate
        calls: list[str] = []
        gate = PermissionGate(tmp, mode="ask", confirmer=lambda r: calls.append(r) or True)
        v = gate.check_step("delete", {"path": str(tmp / "sub" / "x.txt")})
        allowed, needs_confirm, reason = gate.decide(v)
        assert allowed is True and calls and "sub" in calls[-1]
        gate_deny = PermissionGate(tmp, mode="ask", confirmer=lambda r: False)
        allowed2, _, _ = gate_deny.decide(gate_deny.check_step("write", {"path": str(tmp / "y.txt")}))
        assert allowed2 is True
        print("[selftest] permission confirmer .......... OK")

        _save_anim_settings({"enabled": False, "intensity": "low", "reduce": True})
        loaded = _load_anim_settings()
        assert loaded["enabled"] is False and loaded["intensity"] == "low" and loaded["reduce"] is True
        _save_anim_settings(_ANIM_DEFAULTS)
        loaded2 = _load_anim_settings()
        assert loaded2["enabled"] is True and loaded2["intensity"] == "medium"
        print("[selftest] animation settings ............ OK")

    except Exception:
        traceback.print_exc()
        ok = False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n[selftest] RESULT: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


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
        text = run("Say PONG only. No explanation.", max_output_tokens=20)
        elapsed = round(time.time() - start, 1)
        result_q.put(("test_provider", {"ok": True, "provider": provider, "elapsed": elapsed, "text": text}))
    except Exception as exc:
        result_q.put(("test_provider", {"ok": False, "provider": provider, "error": str(exc)}))


def _read_env_value(env_var: str) -> str:
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


class _BrainAnimation:
    IDLE      = "idle"
    THINKING  = "thinking"
    PLANNING  = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR     = "error"

    _RGB_BASE  = (91, 127, 255)
    _RGB_GREEN = (46, 160, 67)
    _RGB_RED   = (207, 34, 46)

    def __init__(self, canvas: tk.Canvas, settings: dict):
        self._c = canvas
        self.state = self.IDLE
        self._apply_settings(settings)
        self._nodes: list[tuple[float, float, float, float]] = []
        self._conns: list[tuple[int, int, float]] = []
        self._parts: list[dict] = []
        self._anim_id = None
        self._running = False
        self._visible = True
        self._focused = True
        self._t0 = time.time()
        self._state_t = 0.0
        self._last_w = 0
        self._last_h = 0

    def _apply_settings(self, s: dict):
        self.enabled = s.get("enabled", True)
        self.intensity = s.get("intensity", "medium")
        self.reduce = s.get("reduce", False)
        m = {"low": (18, 4, 12, 3), "high": (55, 24, 28, 6),
             "medium": (36, 12, 20, 4)}
        self._nc, self._pc, self._fps, self._gr = m.get(self.intensity, m["medium"])

    def update_settings(self, s: dict):
        self._apply_settings(s)
        self._nodes.clear()
        self._conns.clear()
        self._parts.clear()

    def _build_topology(self, w: int, h: int):
        self._nodes.clear(); self._conns.clear(); self._parts.clear()
        if w < 50 or h < 50:
            return
        cx, cy = w / 2, h / 2
        bw = min(w * 0.88, h * 0.82)
        bh = bw * 0.78
        half = self._nc // 2
        for side in (-1, 1):
            for _ in range(half):
                a = random.uniform(0, 6.2831)
                r = math.sqrt(random.uniform(0, 1))
                x = cx + side * bw * 0.22 + r * math.cos(a) * bw * 0.36
                y = cy + r * math.sin(a) * bh * 0.44
                self._nodes.append((x, y, random.uniform(0, 6.2831),
                                    random.uniform(1.4, 3.0)))
        maxd = min(w, h) * 0.22
        for i in range(len(self._nodes)):
            for j in range(i + 1, len(self._nodes)):
                d = math.hypot(self._nodes[i][0] - self._nodes[j][0],
                               self._nodes[i][1] - self._nodes[j][1])
                if d < maxd:
                    self._conns.append((i, j, d))
        for _ in range(self._pc):
            self._new_part()

    def _new_part(self):
        if self._conns:
            c = random.choice(self._conns)
            self._parts.append({"c": c, "p": random.random(),
                                "s": random.uniform(0.004, 0.014),
                                "r": random.uniform(1.0, 2.2)})

    def start(self):
        self._running = True; self._t0 = time.time(); self._tick()

    def stop(self):
        self._running = False
        if self._anim_id:
            try:
                self._c.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def pause(self):
        self._visible = False

    def resume(self):
        self._visible = True

    def focus_out(self):
        self._focused = False

    def focus_in(self):
        self._focused = True

    def set_state(self, state: str):
        self.state = state
        self._state_t = time.time()

    def _tick(self):
        if not self._running:
            return
        now = time.time()
        fps = max(8, self._fps // 2 if self.reduce else self._fps)
        if not self._focused:
            fps = max(6, fps // 2)
        dt = 1.0 / fps
        if now - self._t0 < dt:
            self._anim_id = self._c.after(int(dt * 500), self._tick)
            return
        self._t0 = now
        if not self._visible:
            self._anim_id = self._c.after(300, self._tick)
            return
        self._draw()
        self._anim_id = self._c.after(int(dt * 1000), self._tick)

    @staticmethod
    def _hex(r: int, g: int, b: int) -> str:
        return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"

    def _draw(self):
        self._c.delete("brain")
        if not self.enabled:
            return
        w = self._c.winfo_width()
        h = self._c.winfo_height()
        if w < 50 or h < 50:
            return
        if (not self._nodes or abs(w - self._last_w) > 40 or abs(h - self._last_h) > 40):
            self._build_topology(w, h)
            self._last_w = w
            self._last_h = h

        t = time.time()
        cyc = 5.0
        br = 0.7 + 0.3 * (0.5 + 0.5 * math.sin(6.2831 * t / cyc))
        if self.state == self.THINKING:
            br = 0.8 + 0.2 * (0.5 + 0.5 * math.sin(6.2831 * t / cyc))
        elif self.state == self.PLANNING:
            br = 0.75 + 0.25 * (0.5 + 0.5 * math.sin(6.2831 * t / cyc * 1.15))
        elif self.state == self.EXECUTING:
            br = 0.82 + 0.18 * (0.5 + 0.5 * math.sin(6.2831 * t / (cyc * 0.6)))
        elif self.state == self.COMPLETED:
            if t - self._state_t < 1.0:
                br = 1.0
            else:
                self.state = self.IDLE
        elif self.state == self.ERROR:
            if t - self._state_t >= 1.0:
                self.state = self.IDLE

        base = self._RGB_BASE
        if self.state == self.COMPLETED and t - self._state_t < 1.0:
            bl = min(1.0, t - self._state_t)
            clr = tuple(int(base[i] + (self._RGB_GREEN[i] - base[i]) * bl) for i in range(3))
        elif self.state == self.ERROR and t - self._state_t < 1.0:
            bl = min(1.0, t - self._state_t)
            clr = tuple(int(base[i] + (self._RGB_RED[i] - base[i]) * bl) for i in range(3))
        else:
            clr = base

        hc = [int(c * br * 0.25) for c in clr]
        for i, j, _ in self._conns:
            self._c.create_line(
                self._nodes[i][0], self._nodes[i][1],
                self._nodes[j][0], self._nodes[j][1],
                fill=self._hex(*hc), width=1, tags="brain")

        for x, y, ph, sz in self._nodes:
            wave = 0.5 + 0.5 * math.sin(6.2831 * t / 3.2 + ph)
            nb = br * (0.45 + 0.55 * wave)
            gb = nb * 0.4
            rad = sz + self._gr * 1.8
            self._c.create_oval(
                x - rad, y - rad, x + rad, y + rad,
                fill=self._hex(int(clr[0] * gb), int(clr[1] * gb), int(clr[2] * gb)),
                outline="", tags="brain")
            cr = sz * 0.7
            self._c.create_oval(
                x - cr, y - cr, x + cr, y + cr,
                fill=self._hex(int(clr[0] * nb), int(clr[1] * nb), int(clr[2] * nb)),
                outline="", tags="brain")

        speed_mult = 1.35 if self.state == self.EXECUTING else 1.0
        for p in self._parts:
            p["p"] += p["s"] * speed_mult
            if p["p"] >= 1.0:
                p["p"] -= 1.0
                if self._conns:
                    p["c"] = random.choice(self._conns)
            ci, cj, _ = p["c"]
            px = self._nodes[ci][0] + (self._nodes[cj][0] - self._nodes[ci][0]) * p["p"]
            py = self._nodes[ci][1] + (self._nodes[cj][1] - self._nodes[ci][1]) * p["p"]
            pb = br * 0.7
            self._c.create_oval(
                px - p["r"], py - p["r"], px + p["r"], py + p["r"],
                fill=self._hex(int(clr[0] * pb), int(clr[1] * pb), int(clr[2] * pb)),
                outline="", tags="brain")


class MegaBrainApp:
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
        self._current_view = tk.StringVar(value="chat")
        self._views: dict[str, tk.Frame] = {}
        self._ctx: dict[str, Any] = {}
        self._status_labels: dict[str, tk.Label] = {}
        self._brain: _BrainAnimation | None = None

        self._build_ui()
        self._brain = _BrainAnimation(self._brain_canvas, _load_anim_settings())
        self._brain.start()

        self.root.bind("<Unmap>", self._on_unmap)
        self.root.bind("<Map>", self._on_map)
        self.root.bind("<FocusIn>", self._on_focus_in)
        self.root.bind("<FocusOut>", self._on_focus_out)
        self.root.after(100, self._poll_queues)
        self.root.after(500, self._load_initial_status)

    def _build_ui(self):
        r = self.root
        hdr = tk.Frame(r, bg=_BG2, bd=0, highlightthickness=0)
        hdr.pack(fill=tk.X, side=tk.TOP)
        tk.Label(hdr, text="MEGA BRAIN", font=("Segoe UI", 16, "bold"),
                 fg=_FG, bg=_BG2, padx=16, pady=8).pack(side=tk.LEFT)
        self._status_labels["mb"] = self._badge(hdr, "● Mega Brain Online", _GREEN)
        self._status_labels["gemini"] = self._badge(hdr, "Gemini: ...", _FG2)
        self._status_labels["groq"] = self._badge(hdr, "Groq: ...", _FG2)
        self._status_labels["memory"] = self._badge(hdr, "Memoria: ...", _FG2)

        body = tk.Frame(r, bg=_BG, bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True)
        sb = tk.Frame(body, bg=_BG2, width=180, bd=0, highlightthickness=0)
        sb.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 1), pady=0)
        sb.pack_propagate(False)
        for label, key in [
            ("Nova tarefa", "chat"), ("Memoria", "memory"),
            ("Contexto", "context"), ("Status", "status"),
            ("Configuracoes", "settings"),
        ]:
            tk.Button(sb, text=label, font=("Segoe UI", 11), fg=_FG, bg=_BG2,
                      activeforeground=_ACCENT, activebackground=_BG3,
                      bd=0, anchor="w", padx=16, pady=8,
                      command=lambda k=key: self._switch_view(k)).pack(fill=tk.X)

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

    def _build_chat_view(self):
        f = tk.Frame(self._content, bg=_BG, bd=0, highlightthickness=0)
        self._views["chat"] = f

        # Keep the neural canvas permanently visible in the upper half of chat.
        hero = tk.Frame(f, bg=_BG, height=300)
        hero.pack(fill=tk.BOTH, expand=True)
        hero.pack_propagate(False)
        self._brain_canvas = tk.Canvas(hero, bg=_BG, highlightthickness=0, bd=0)
        self._brain_canvas.pack(fill=tk.BOTH, expand=True)
        self._brain_canvas.create_text(
            18, 16, anchor="nw", text="NÚCLEO NEURAL",
            fill=_FG2, font=("Segoe UI", 10, "bold"), tags="overlay")

        lower = tk.Frame(f, bg=_BG, bd=0, highlightthickness=0)
        lower.pack(fill=tk.BOTH, expand=True)
        self._chat_text = tk.Text(lower, bg=_BG, fg=_FG, insertbackground=_FG,
                                  font=("Consolas", 11), wrap=tk.WORD,
                                  state=tk.DISABLED, height=8, padx=12, pady=10,
                                  highlightthickness=0, bd=0,
                                  selectbackground=_ACCENT)
        scroll = tk.Scrollbar(lower, command=self._chat_text.yview)
        self._chat_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._chat_text.pack(fill=tk.BOTH, expand=True)
        self._chat_text.tag_configure("user", foreground=_CYAN, font=("Consolas", 11, "bold"))
        self._chat_text.tag_configure("system", foreground=_FG2)
        self._chat_text.tag_configure("phase", foreground=_YELLOW)
        self._chat_text.tag_configure("ok", foreground=_GREEN)
        self._chat_text.tag_configure("error", foreground=_RED)

        inp = tk.Frame(f, bg=_BG, bd=0, highlightthickness=0)
        inp.pack(fill=tk.X, padx=10, pady=(4, 10))
        self._input = tk.Text(inp, bg=_INPUT_BG, fg=_FG, insertbackground=_FG,
                              font=("Segoe UI", 12), height=3, wrap=tk.WORD,
                              highlightthickness=1, highlightbackground=_BG3,
                              highlightcolor=_ACCENT, bd=0, padx=10, pady=8)
        self._input.bind("<Return>", self._on_enter)
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self._send_btn = tk.Button(inp, text="EXECUTAR", font=("Segoe UI", 11, "bold"),
                                   fg=_FG, bg=_ACCENT, activeforeground="#fff",
                                   activebackground="#4a64d9", bd=0, padx=20, pady=10,
                                   command=self._send_task)
        self._send_btn.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_enter(self, event):
        if event.state & 0x0001:
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
        if not obj:
            return
        self._input.delete("1.0", tk.END)
        self._input.configure(state=tk.DISABLED)
        self._send_btn.configure(state=tk.DISABLED, text="Executando...")
        self._append_chat(f"> {obj}", "user")
        self._running = True
        self._worker = threading.Thread(target=_worker_execute, args=(obj, self._phase_q, self._result_q), daemon=True)
        self._worker.start()

    def _build_memory_view(self):
        f = tk.Frame(self._content, bg=_BG)
        self._views["memory"] = f
        tk.Label(f, text="MEMORIA DO PROJETO", font=("Segoe UI", 14, "bold"), fg=_FG, bg=_BG).pack(anchor="w", padx=16, pady=10)
        self._mem_text = tk.Text(f, bg=_BG, fg=_FG, font=("Consolas", 10), wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0, bd=0)
        self._mem_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        tk.Button(f, text="Atualizar", command=self._refresh_memory, bg=_BG3, fg=_FG, bd=0).pack(anchor="w", padx=16, pady=6)

    def _refresh_memory(self):
        threading.Thread(target=self._load_memory, daemon=True).start()

    def _load_memory(self):
        try:
            from engine.executor.memory import ProjectMemory
            mem = ProjectMemory(str(_ROOT))
            self.root.after(0, self._render_memory, mem.summary_markdown())
        except Exception as exc:
            self.root.after(0, self._render_memory, f"Erro: {exc}")

    def _render_memory(self, text):
        self._mem_text.configure(state=tk.NORMAL)
        self._mem_text.delete("1.0", tk.END)
        self._mem_text.insert(tk.END, text)
        self._mem_text.configure(state=tk.DISABLED)

    def _build_context_view(self):
        f = tk.Frame(self._content, bg=_BG)
        self._views["context"] = f
        tk.Label(f, text="CONTEXTO", font=("Segoe UI", 14, "bold"), fg=_FG, bg=_BG).pack(anchor="w", padx=16, pady=10)
        self._ctx_text = tk.Text(f, bg=_BG, fg=_FG, font=("Consolas", 10), state=tk.DISABLED, highlightthickness=0, bd=0)
        self._ctx_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        tk.Button(f, text="Atualizar", command=self._refresh_context, bg=_BG3, fg=_FG, bd=0).pack(anchor="w", padx=16, pady=6)

    def _refresh_context(self):
        threading.Thread(target=_worker_context, args=(self._result_q,), daemon=True).start()

    def _render_context(self, ctx):
        self._ctx = ctx
        self._ctx_text.configure(state=tk.NORMAL)
        self._ctx_text.delete("1.0", tk.END)
        self._ctx_text.insert(tk.END, json.dumps(ctx, ensure_ascii=False, indent=2, default=str))
        self._ctx_text.configure(state=tk.DISABLED)

    def _build_status_view(self):
        f = tk.Frame(self._content, bg=_BG)
        self._views["status"] = f
        tk.Label(f, text="STATUS DO RUNTIME", font=("Segoe UI", 14, "bold"), fg=_FG, bg=_BG).pack(anchor="w", padx=16, pady=10)
        self._status_text = tk.Text(f, bg=_BG, fg=_FG, font=("Consolas", 10), state=tk.DISABLED, highlightthickness=0, bd=0)
        self._status_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        tk.Button(f, text="Atualizar", command=self._refresh_status, bg=_BG3, fg=_FG, bd=0).pack(anchor="w", padx=16, pady=6)

    def _refresh_status(self):
        threading.Thread(target=_worker_context, args=(self._result_q,), daemon=True).start()

    def _render_status(self, ctx):
        gemini = ctx.get("llm_gemini", False)
        groq = ctx.get("llm_groq", False)
        text = (
            f"Python: {ctx.get('python', '-')}\n"
            f"Workspace: {ctx.get('root', '-')}\n"
            f"Gemini: {'Online' if gemini else 'Offline'}\n"
            f"Groq: {'Online' if groq else 'Offline'}\n"
            f"Memoria: {ctx.get('store_dir', '-')}\n"
        )
        self._status_text.configure(state=tk.NORMAL)
        self._status_text.delete("1.0", tk.END)
        self._status_text.insert(tk.END, text)
        self._status_text.configure(state=tk.DISABLED)
        self._update_header(ctx)

    def _update_header(self, ctx):
        gemini = ctx.get("llm_gemini", False)
        groq = ctx.get("llm_groq", False)
        self._status_labels["gemini"].configure(text=f"Gemini: {'Online' if gemini else 'Offline'}", fg=_GREEN if gemini else _RED)
        self._status_labels["groq"].configure(text=f"Groq: {'Online' if groq else 'Offline'}", fg=_GREEN if groq else _RED)
        self._status_labels["memory"].configure(text="Memoria: Ativa", fg=_GREEN)

    def _build_settings_view(self):
        f = tk.Frame(self._content, bg=_BG)
        self._views["settings"] = f
        tk.Label(f, text="CONFIGURACOES", font=("Segoe UI", 14, "bold"), fg=_FG, bg=_BG).pack(anchor="w", padx=16, pady=10)

        anim_s = _load_anim_settings()
        anim_frame = tk.Frame(f, bg=_BG3, padx=12, pady=10)
        anim_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        self._anim_var = tk.BooleanVar(value=anim_s["enabled"])
        self._anim_intensity = tk.StringVar(value=anim_s["intensity"])
        self._anim_reduce = tk.BooleanVar(value=anim_s["reduce"])
        tk.Checkbutton(anim_frame, text="Animacao de fundo", variable=self._anim_var, command=self._on_anim_changed, fg=_FG, bg=_BG3, selectcolor=_BG2).pack(anchor="w")
        row = tk.Frame(anim_frame, bg=_BG3); row.pack(anchor="w")
        for val, label in [("low", "Baixa"), ("medium", "Media"), ("high", "Alta")]:
            tk.Radiobutton(row, text=label, variable=self._anim_intensity, value=val, command=self._on_anim_changed, fg=_FG, bg=_BG3, selectcolor=_BG2).pack(side=tk.LEFT)
        tk.Checkbutton(anim_frame, text="Reduzir animacoes", variable=self._anim_reduce, command=self._on_anim_changed, fg=_FG, bg=_BG3, selectcolor=_BG2).pack(anchor="w")

        for label, env_var in [("GEMINI_API_KEY", "GEMINI_API_KEY"), ("GROQ_API_KEY", "GROQ_API_KEY")]:
            tk.Label(f, text=label + ":", font=("Segoe UI", 11, "bold"), fg=_FG, bg=_BG).pack(anchor="w", padx=16, pady=(8, 0))
            entry = tk.Entry(f, font=("Consolas", 11), bg=_INPUT_BG, fg=_FG, insertbackground=_FG, bd=0, show="*", width=52)
            entry.pack(anchor="w", padx=16, pady=2)
            entry.insert(0, _read_env_value(env_var))
            setattr(self, f"_entry_{env_var.lower()}", entry)
        tk.Button(f, text="Salvar chaves", command=self._save_settings, bg=_GREEN, fg="#fff", bd=0).pack(anchor="w", padx=16, pady=12)
        self._settings_status = tk.Label(f, text="", fg=_FG2, bg=_BG)
        self._settings_status.pack(anchor="w", padx=16)

    def _on_anim_changed(self):
        s = {"enabled": self._anim_var.get(), "intensity": self._anim_intensity.get(), "reduce": self._anim_reduce.get()}
        _save_anim_settings(s)
        if self._brain:
            self._brain.update_settings(s)

    def _save_settings(self):
        gemini = self._entry_gemini_api_key.get().strip()
        groq = self._entry_groq_api_key.get().strip()
        threading.Thread(target=_worker_save_keys, args=(gemini, groq, self._result_q), daemon=True).start()

    def _switch_view(self, key: str):
        for child in self._content.winfo_children():
            child.pack_forget()
        self._views[key].pack(fill=tk.BOTH, expand=True)
        self._current_view.set(key)
        if self._brain:
            if key == "chat": self._brain.resume()
            else: self._brain.pause()
        if key == "memory": self._refresh_memory()
        elif key == "context": self._refresh_context()
        elif key == "status": self._refresh_status()

    def _poll_queues(self):
        try:
            while True:
                name, payload = self._phase_q.get_nowait()
                if name == "__permission__" and payload:
                    self._show_permission_dialog(payload)
                elif name in PHASE_LABELS:
                    self._append_chat(f"  {PHASE_LABELS[name]}", "phase")
                    if self._brain:
                        self._brain.set_state({
                            "thinking": _BrainAnimation.THINKING,
                            "planning": _BrainAnimation.PLANNING,
                            "executing": _BrainAnimation.EXECUTING,
                            "validating": _BrainAnimation.THINKING,
                        }.get(name, _BrainAnimation.IDLE))
        except queue.Empty:
            pass

        try:
            while True:
                kind, data = self._result_q.get_nowait()
                if kind == "execute": self._on_execute_done(data)
                elif kind == "context":
                    self._render_context(data); self._render_status(data)
                elif kind == "save_keys":
                    self._settings_status.configure(text="Salvo com sucesso." if data.get("ok") else f"Erro: {data.get('error')}", fg=_GREEN if data.get("ok") else _RED)
                elif kind == "test_provider":
                    pass
        except queue.Empty:
            pass
        self.root.after(60, self._poll_queues)

    def _on_execute_done(self, data: dict):
        self._running = False
        self._input.configure(state=tk.NORMAL)
        self._send_btn.configure(state=tk.NORMAL, text="EXECUTAR")
        success = data.get("success", False)
        if self._brain:
            self._brain.set_state(_BrainAnimation.COMPLETED if success else _BrainAnimation.ERROR)
        self._append_chat("Concluido." if success else "Erro.", "ok" if success else "error")
        for e in (data.get("errors") or [])[:5]:
            self._append_chat(f"  - {e}", "error")
        if data.get("report_markdown"):
            self._append_chat(data["report_markdown"], "system")

    def _show_permission_dialog(self, payload: dict):
        reason = payload.get("reason", "Acao perigosa detectada")
        ev = payload.get("event"); holder = payload.get("holder")
        if ev is None or holder is None:
            return
        dlg = tk.Toplevel(self.root); dlg.title("Acao requer autorizacao"); dlg.configure(bg=_BG2); dlg.geometry("480x220"); dlg.transient(self.root); dlg.grab_set()
        tk.Label(dlg, text="Acao requer autorizacao", font=("Segoe UI", 14, "bold"), fg=_YELLOW, bg=_BG2, pady=12).pack()
        tk.Label(dlg, text=reason[:200], font=("Segoe UI", 10), fg=_FG, bg=_BG2, wraplength=440, padx=16, pady=8).pack()
        row = tk.Frame(dlg, bg=_BG2); row.pack(pady=12)
        def answer(v):
            holder[0] = v; ev.set(); dlg.destroy()
        tk.Button(row, text="CANCELAR", command=lambda: answer(False), bg=_BG3, fg=_FG, bd=0, padx=20, pady=6).pack(side=tk.LEFT, padx=8)
        tk.Button(row, text="AUTORIZAR", command=lambda: answer(True), bg=_GREEN, fg="#fff", bd=0, padx=20, pady=6).pack(side=tk.LEFT, padx=8)

    def _on_unmap(self, event):
        if event.widget == self.root and self._brain and self.root.state() == "iconic": self._brain.pause()

    def _on_map(self, event):
        if event.widget == self.root and self._brain and self._current_view.get() == "chat": self._brain.resume()

    def _on_focus_in(self, event):
        if event.widget == self.root and self._brain: self._brain.focus_in()

    def _on_focus_out(self, event):
        if event.widget == self.root and self._brain: self._brain.focus_out()

    def _load_initial_status(self):
        threading.Thread(target=_worker_context, args=(self._result_q,), daemon=True).start()

    def _on_close(self):
        if self._brain: self._brain.stop()
        if self._running and not messagebox.askokcancel("Sair", "Uma tarefa esta em execucao. Deseja sair mesmo?"):
            return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        MegaBrainApp().run()
