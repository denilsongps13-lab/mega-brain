"""Lightweight retained Canvas animation; all Tk calls run on the event loop."""
import json
import math
import random
import time
from pathlib import Path

DEFAULTS = {'enabled': True, 'intensity': 'Medium', 'reduce': False}


def load_settings(path):
    try:
        saved = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        saved = {}
    return {'enabled': saved.get('enabled', True) is not False,
            'intensity': saved.get('intensity') if saved.get('intensity') in ('Low', 'Medium', 'High') else 'Medium',
            'reduce': saved.get('reduce', False) is True}


def save_settings(path, settings):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    temp.replace(path)


class NeuralBrain:
    def __init__(self, canvas, settings):
        self.canvas, self.settings = canvas, settings
        self.state = 'IDLE'
        self.changed = time.monotonic()
        self.visible = True
        self.closed = False
        self.after_id = None
        rng = random.Random(23)
        # Two lobes with a narrow fissure, denser along the folded outline.
        self.points = []
        for side in (-1, 1):
            for ring, count in ((1, 24), (.68, 17), (.34, 9)):
                for i in range(count):
                    a = math.tau * i / count
                    x = side * (.27 + .25 * ring * math.cos(a))
                    y = .80 * ring * math.sin(a)
                    self.points.append((x, y))
        self.edges = []
        for i, p in enumerate(self.points):
            near = sorted(range(len(self.points)), key=lambda j: math.dist(p, self.points[j]))[1:4]
            for j in near:
                if j > i:
                    self.edges.append((i, j))
        self.lines = [canvas.create_line(0, 0, 0, 0, fill='#163a60') for _ in self.edges]
        self.nodes = [canvas.create_oval(0, 0, 0, 0, outline='', fill='#276ea5') for _ in self.points]
        self.pulses = [(canvas.create_oval(0, 0, 0, 0, outline='', fill='#56bcdd'), i)
                       for i in range(0, len(self.edges), 9)]
        self.particles = [(canvas.create_oval(0, 0, 0, 0, outline='', fill='#234766'), rng.random(), rng.random())
                          for _ in range(14)]
        self.tick()

    def set_state(self, state):
        self.state = {'DONE': 'COMPLETED', 'VALIDATING': 'EXECUTING'}.get(state.upper(), state.upper())
        if self.state not in ('IDLE', 'THINKING', 'PLANNING', 'EXECUTING', 'COMPLETED', 'ERROR'):
            self.state = 'IDLE'
        self.changed = time.monotonic()

    def stop(self):
        self.closed = True
        if self.after_id is not None:
            self.canvas.after_cancel(self.after_id)
            self.after_id = None

    def tick(self):
        if self.closed:
            return
        now = time.monotonic()
        if self.state in ('COMPLETED', 'ERROR') and now - self.changed >= 1:
            self.set_state('IDLE')
        active = self.visible and self.canvas.winfo_toplevel().state() not in ('iconic', 'withdrawn')
        enabled = self.settings.get('enabled', True)
        self.canvas.itemconfigure('all', state='normal' if enabled else 'hidden')
        if active and enabled:
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            reduced = self.settings.get('reduce', False)
            intensity = {'Low': .55, 'Medium': .8, 'High': 1.0}[self.settings['intensity']]
            speed = {'IDLE': .8, 'THINKING': 1.1, 'PLANNING': 1.6, 'EXECUTING': 2.0}.get(self.state, 1)
            pulse = 0 if reduced else math.sin(now * speed)
            scale = min(w * .85, h * .56) * (1 + .015 * pulse)
            coords = [(w/2 + x*min(w*.9, h*2.1)*(1+.015*pulse), h/2 + y*scale) for x, y in self.points]
            brightness = intensity * (.76 + .10*pulse + (.12 if self.state != 'IDLE' else 0))
            rgb = (130, 66, 86) if self.state == 'ERROR' else (38, 150, 141) if self.state == 'COMPLETED' else (40, 113, 170)
            color = '#' + ''.join(f'{int(c*brightness):02x}' for c in rgb)
            for line, (a, b) in zip(self.lines, self.edges):
                self.canvas.coords(line, *coords[a], *coords[b])
                self.canvas.itemconfigure(line, fill=color)
            for node, (x, y) in zip(self.nodes, coords):
                self.canvas.coords(node, x-1.5, y-1.5, x+1.5, y+1.5)
                self.canvas.itemconfigure(node, fill=color)
            for item, edge in self.pulses:
                a, b = self.edges[edge]
                t = (now * speed * .22 + edge * .13) % 1
                x, y = (coords[a][k]*(1-t)+coords[b][k]*t for k in (0, 1))
                self.canvas.coords(item, x-2, y-2, x+2, y+2)
                self.canvas.itemconfigure(item, state='hidden' if reduced else 'normal')
            for item, x, y in self.particles:
                px, py = x*w, ((y + (0 if reduced else now*.008)) % 1)*h
                self.canvas.coords(item, px-1, py-1, px+1, py+1)
        delay = 40 if active and enabled and not self.settings.get('reduce') else 250
        self.after_id = self.canvas.after(delay, self.tick)
