import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[2] / 'windows/ui/neural_brain.py'
spec = importlib.util.spec_from_file_location('neural_brain', path)
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)


class Canvas:
    def __init__(self):
        self.items = {}; self.delay = None; self.mode = 'normal'
    def create_line(self, *args, **kwargs):
        n = len(self.items) + 1; self.items[n] = args; return n
    create_oval = create_line
    def coords(self, item, *args): self.items[item] = args
    def itemconfigure(self, *args, **kwargs): pass
    def winfo_toplevel(self): return self
    def state(self): return self.mode
    def winfo_width(self): return 700
    def winfo_height(self): return 240
    def after(self, delay, callback): self.delay = delay; return 1
    def after_cancel(self, job): self.delay = None


def test_animation_states_and_bounded_items(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(brain.time, 'monotonic', lambda: clock[0])
    canvas = Canvas()
    animation = brain.NeuralBrain(canvas, dict(brain.DEFAULTS))
    count = len(canvas.items)
    initial = dict(canvas.items)
    for state in ('THINKING', 'PLANNING', 'EXECUTING', 'COMPLETED', 'ERROR'):
        animation.set_state(state)
        clock[0] += .2
        animation.tick()
        assert animation.state == state
        assert len(canvas.items) == count
    assert initial != canvas.items
    clock[0] += 1.1
    animation.tick()
    assert animation.state == 'IDLE'
    assert canvas.delay == 40
    canvas.mode = 'iconic'
    initial = dict(canvas.items)
    animation.tick()
    assert canvas.items == initial and canvas.delay == 250
    animation.stop()
    assert canvas.delay is None


def test_animation_settings_roundtrip(tmp_path):
    path = tmp_path / 'ui-animation.json'
    settings = {'enabled': False, 'intensity': 'Low', 'reduce': True}
    brain.save_settings(path, settings)
    assert brain.load_settings(path) == settings
    path.write_text('invalid json')
    assert brain.load_settings(path) == brain.DEFAULTS
