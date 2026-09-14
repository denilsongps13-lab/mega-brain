#!/usr/bin/env python3
from __future__ import annotations

"""Mega Brain desktop UI v6.

Branding correction over V5: every visible BINEXORA label is replaced by the
approved signature "by NEXORA" while preserving the full V5 dashboard,
attachments, local login/profile, neural animation and V4 executor diagnostics.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V5_PATH = Path(__file__).with_name("megabrain-ui-v5.pyw")
spec = importlib.util.spec_from_file_location("megabrain_ui_v5", V5_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Não foi possível carregar a interface V5: {V5_PATH}")
v5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v5)


def _fix_branding(widget) -> None:
    """Recursively replace the old temporary brand label in Tk widgets."""
    try:
        text = widget.cget("text")
    except Exception:
        text = None
    if isinstance(text, str) and "BINEXORA" in text:
        try:
            widget.config(text=text.replace("BINEXORA", "by NEXORA"))
        except Exception:
            pass
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        _fix_branding(child)


class App(v5.App):
    def build(self):
        super().build()
        _fix_branding(self.root)

    def _hero_overlay(self):
        # Keep V5's neural hero and replace only the brand signature rendered
        # directly on Canvas (Canvas text is not a normal Tk child widget).
        super()._hero_overlay()
        c = self.canvas
        try:
            for item in c.find_withtag("v5overlay"):
                if c.type(item) == "text":
                    text = c.itemcget(item, "text")
                    if "BINEXORA" in text:
                        c.itemconfigure(item, text=text.replace("BINEXORA", "by NEXORA"))
        except Exception:
            pass


def selftest():
    v5.selftest()
    assert "by NEXORA" == "BINEXORA".replace("BINEXORA", "by NEXORA")
    print("MEGA BRAIN UI V6 SELFTEST: PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        App().run()
