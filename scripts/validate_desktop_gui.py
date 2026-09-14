"""Exercise real Tk widgets, lifecycle states and settings without credentials."""
import importlib.machinery
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'windows/ui'))
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader('desktop_ui', str(ROOT / 'windows/ui/megabrain-ui.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
ui = importlib.util.module_from_spec(spec)
loader.exec_module(ui)

# Do not probe or load real credentials or project memory during GUI smoke.
ui._read_env_value = lambda _: ''
ui.MegaBrainApp._load_initial_status = lambda _: None
ui.MegaBrainApp._refresh_memory = lambda _: None
ui.MegaBrainApp._refresh_context = lambda _: None
ui.MegaBrainApp._refresh_status = lambda _: None
from engine import paths
from neural_brain import save_settings, load_settings

with tempfile.TemporaryDirectory() as tmp:
    paths.DATA = Path(tmp)
    app = ui.MegaBrainApp()
    try:
        app.root.update()
        assert app._brain_canvas.winfo_ismapped()
        assert len(app._brain_canvas.find_all()) > 100
        for state in ('IDLE', 'THINKING', 'PLANNING', 'EXECUTING', 'COMPLETED', 'ERROR'):
            app._brain.set_state(state)
            app._brain.tick()
            assert app._brain.state == state
            app.root.update()
        for view in ('memory', 'context', 'status', 'settings', 'chat'):
            app._switch_view(view)
            app.root.update()
            assert app._views[view].winfo_ismapped()
        app._append_chat('Readable chat preserved', 'user')
        assert 'Readable chat preserved' in app._chat_text.get('1.0', 'end')
        assert app._send_btn['text'] == 'EXECUTAR'
        save_settings(app._animation_path, {'enabled': False, 'intensity': 'Low', 'reduce': True})
        assert load_settings(app._animation_path)['reduce'] is True
        print('GUI visual selftest: PASS (Tk widgets, six states, views, chat, settings)')
    finally:
        app._brain.stop()
        app.root.destroy()
