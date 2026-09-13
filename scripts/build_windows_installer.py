"""Build the offline, single-click repair ZIP from reviewed repository sources."""
import base64
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'INICIAR_MEGA_CEREBRO.cmd', 'TESTAR_MEGA_CEREBRO.cmd',
    'scripts/start_mega_brain.py', 'scripts/start_mega_brain_v2.py',
    'scripts/mega_brain_rate_limit.py', 'windows/LEIA_ME_FINAL.md',
    '.claude/hooks/run-hook.cjs',
    'mega-brain-core/package.json',
    'mega-brain-core/core/synapse/runtime/hook-runtime.js',
    'mega-brain-core/hooks/unified/runners/precompact-runner.js',
    'engine/jarvis/voice/vapi_update_assistant.py',
    'engine/jarvis/voice/vapi_update_full_ptbr.py',
    'system/REGISTRY/INSIGHTS-STATE.json',
    'system/REGISTRY/BATCH-HISTORY.json',
]
INSTALL = r'''
import base64, hashlib, json, os, pathlib, secrets, subprocess, sys, tempfile
from datetime import datetime, timezone

def install():
    here = pathlib.Path(os.environ['MEGA_INSTALLER']).resolve().parent
    home = pathlib.Path.home()
    candidates = [here, home/'Desktop/mega-brain-main/mega-brain-main', home/'Desktop/mega-brain-main']
    if os.environ.get('OneDrive'):
        desktop = pathlib.Path(os.environ['OneDrive'])/'Desktop'
        candidates += [desktop/'mega-brain-main/mega-brain-main', desktop/'mega-brain-main']
    target = next((p for p in candidates if (p/'.claude/settings.json').is_file()), None)
    if target is None:
        import tkinter as tk
        from tkinter import filedialog
        ui = tk.Tk(); ui.withdraw()
        directory = filedialog.askdirectory(title='Selecione a pasta do Mega Cerebro que contem .claude')
        ui.destroy()
        if not directory: print('Instalacao cancelada.'); return 1
        target = pathlib.Path(directory)
    if not (target/'.claude/settings.json').is_file(): print('Pasta incorreta: .claude/settings.json ausente.'); return 1
    payload = json.loads(base64.b64decode(PAYLOAD)); decoded = {}
    for relative, item in payload.items():
        data = base64.b64decode(item['data'])
        if hashlib.sha256(data).hexdigest() != item['sha256']: print('Pacote corrompido. Nenhum arquivo alterado.'); return 1
        # Registry baselines are create-only: existing knowledge is never replaced.
        if relative.startswith('system/REGISTRY/') and (target/relative).exists():
            continue
        decoded[relative] = data
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(4)
    backup = target/'.data/mega-brain/installer-backups'/stamp; backup.mkdir(parents=True)
    previous = {}
    for relative in decoded:
        dest = target/relative; previous[relative] = dest.read_bytes() if dest.exists() else None
        if previous[relative] is not None:
            saved = backup/relative; saved.parent.mkdir(parents=True, exist_ok=True); saved.write_bytes(previous[relative])
    (backup/'manifest.json').write_text(json.dumps({'replaced':[p for p,v in previous.items() if v is not None], 'created':[p for p,v in previous.items() if v is None]}, indent=2))
    for relative, data in decoded.items():
        dest = target/relative; current = dest.read_bytes() if dest.exists() else None
        if current != previous[relative]: print('Arquivo alterado por outro processo. Instalacao interrompida; backup disponivel.'); return 1
        dest.parent.mkdir(parents=True, exist_ok=True); fd, temporary = tempfile.mkstemp(dir=dest.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream: stream.write(data)
            os.replace(temporary, dest)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    print('Correcao instalada com backup. Abrindo Mega Cerebro...')
    return subprocess.call([sys.executable, str(target/'scripts/start_mega_brain_v2.py')], cwd=target)
try: sys.exit(install())
except Exception:
    print('Instalacao interrompida. Nenhuma chave foi exibida. Consulte o backup antes de repetir.'); sys.exit(1)
'''

def build():
    payload = {}
    for relative in FILES:
        data = (ROOT / relative).read_bytes()
        if relative.endswith('.cmd'): data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        payload[relative] = {'data': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode(); source = 'PAYLOAD = ' + repr(encoded) + '\n' + INSTALL
    body = base64.b64encode(source.encode()).decode()
    bootstrap = "import base64,os; p=open(os.environ['MEGA_INSTALLER'],'rb').read().replace(b'\\r\\n',b'\\n'); exec(compile(base64.b64decode(p.rsplit(b'\\nREM MEGA_PAYLOAD\\n',1)[1]),'<mega-installer>','exec'))"
    cmd = '@echo off\nsetlocal\nset "MEGA_INSTALLER=%~f0"\nwhere py >nul 2>nul\nif not errorlevel 1 (\n  py -3 -c "' + bootstrap + '"\n) else (\n  python -c "' + bootstrap + '"\n)\nset "MEGA_RESULT=%ERRORLEVEL%"\nif not "%MEGA_RESULT%"=="0" pause\nexit /b %MEGA_RESULT%\nREM MEGA_PAYLOAD\n' + body + '\n'
    out = ROOT / 'windows/INSTALAR_MEGA_CEREBRO_FINAL.zip'; out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w') as archive:
        info = zipfile.ZipInfo('INSTALAR_MEGA_CEREBRO.cmd', (2026, 9, 12, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
        archive.writestr(info, cmd.replace('\n', '\r\n').encode('ascii'))
    return out
if __name__ == '__main__': print(build().relative_to(ROOT))
