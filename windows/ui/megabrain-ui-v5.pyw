#!/usr/bin/env python3
from __future__ import annotations

"""Mega Brain desktop UI v5.

Advanced home dashboard requested for the desktop app: richer navigation,
login/local profile, attachment/audio controls, quick tools, recent tasks and
BINEXORA branding while preserving the V4 executor diagnostics and neural
animation.
"""

import hashlib
import importlib.util
import json
import secrets
import sys
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V4_PATH = Path(__file__).with_name("megabrain-ui-v4.pyw")
spec = importlib.util.spec_from_file_location("megabrain_ui_v4", V4_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Não foi possível carregar a interface V4: {V4_PATH}")
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)

tk = v4.v3.tk
BG = v4.v3.BG
SIDEBAR = v4.v3.SIDEBAR
PANEL = v4.v3.PANEL
PANEL2 = v4.v3.PANEL2
BLUE = v4.v3.BLUE
CYAN = v4.v3.CYAN
FG = v4.v3.FG
MUTED = v4.v3.MUTED
GREEN = v4.v3.GREEN
RED = v4.v3.RED

PROFILE_FILE = ROOT / ".data" / "megabrain" / "ui-profile.json"


def _load_profile() -> dict:
    try:
        if PROFILE_FILE.exists():
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_profile(data: dict) -> None:
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _password_hash(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000).hex()


class App(v4.App):
    def build(self):
        self.attachments: list[str] = []
        self.profile = _load_profile()
        self.logged_user = None

        top = tk.Frame(self.root, bg="#030b16", height=36)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="◉  Mega Brain", fg=FG, bg="#030b16", font=("Segoe UI", 10, "bold"), padx=10).pack(side=tk.LEFT, pady=8)
        tk.Label(top, text="⚙     —     □     ✕", fg="#d7e8f7", bg="#030b16", font=("Segoe UI", 10), padx=14).pack(side=tk.RIGHT, pady=7)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        side = tk.Frame(body, bg=SIDEBAR, width=220, highlightthickness=1, highlightbackground="#06365f")
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)
        tk.Label(side, text="🧠", fg=CYAN, bg=SIDEBAR, font=("Segoe UI Emoji", 36)).pack(pady=(14, 0))
        tk.Label(side, text="MEGA BRAIN", fg=FG, bg=SIDEBAR, font=("Segoe UI", 18, "bold")).pack()
        tk.Label(side, text="Sua inteligência em ação", fg=MUTED, bg=SIDEBAR, font=("Segoe UI", 9)).pack(pady=(2, 20))

        nav = [
            ("⌂", "Página Inicial", "chat"),
            ("⊕", "Nova Tarefa", "chat"),
            ("🤖", "Assistentes IA", "assistants"),
            ("⚙", "Automação", "automation"),
            ("▣", "Memória", "memory"),
            ("▤", "Contexto", "context"),
            ("▰", "Projetos", "projects"),
            ("🔧", "Ferramentas", "tools"),
            ("◷", "Histórico", "history"),
            ("⚙", "Configurações", "settings"),
        ]
        for icon, label, key in nav:
            bg = "#0a56dd" if label == "Página Inicial" else SIDEBAR
            tk.Button(
                side, text=f"{icon}   {label}", anchor="w", fg=FG, bg=bg,
                activebackground="#0d3470", activeforeground=FG, font=("Segoe UI", 10),
                bd=0, padx=16, pady=10, command=lambda k=key: self.switch(k),
            ).pack(fill=tk.X, padx=8, pady=2)

        brand = tk.Frame(side, bg=SIDEBAR)
        brand.pack(side=tk.BOTTOM, fill=tk.X, pady=18)
        tk.Label(brand, text="⬡", fg=CYAN, bg=SIDEBAR, font=("Segoe UI", 32, "bold")).pack()
        tk.Label(brand, text="BINEXORA", fg=BLUE, bg=SIDEBAR, font=("Segoe UI", 16, "bold")).pack()
        tk.Label(brand, text="AUTOMAÇÃO • ESTRATÉGIA\nPRODUTIVIDADE SEM LIMITES", fg=CYAN, bg=SIDEBAR, font=("Segoe UI", 7, "bold")).pack()

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.views = {}
        self.build_chat()
        for key, title, text in [
            ("assistants", "ASSISTENTES IA", "Agentes e assistentes especializados do Mega Brain."),
            ("automation", "AUTOMAÇÃO", "Fluxos, tarefas automáticas e rotinas."),
            ("memory", "MEMÓRIA", "Histórico e memória persistente do Mega Brain."),
            ("context", "CONTEXTO", "Contexto atual do projeto e ambiente de execução."),
            ("projects", "PROJETOS", "Projetos locais e áreas de trabalho."),
            ("tools", "FERRAMENTAS", "Ferramentas rápidas e recursos do sistema."),
            ("history", "HISTÓRICO", "Execuções e resultados recentes."),
        ]:
            self.build_simple(key, title, text)
        self.build_settings()
        self.switch("chat")

    def _status_card(self, parent, title, sub):
        f = tk.Frame(parent, bg=PANEL2, highlightthickness=1, highlightbackground="#0a5fa8", padx=10, pady=7)
        f.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        tk.Label(f, text="●", fg=GREEN, bg=PANEL2, font=("Segoe UI", 17, "bold")).pack(side=tk.LEFT, padx=(0, 7))
        t = tk.Frame(f, bg=PANEL2); t.pack(side=tk.LEFT)
        tk.Label(t, text=title, fg=FG, bg=PANEL2, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        lab = tk.Label(t, text=sub, fg=MUTED, bg=PANEL2, font=("Segoe UI", 8)); lab.pack(anchor="w")
        return lab

    def build_chat(self):
        f = tk.Frame(self.content, bg=BG)
        self.views["chat"] = f

        cards = tk.Frame(f, bg=BG)
        cards.pack(fill=tk.X, padx=8, pady=(9, 5))
        self.s_mb = self._status_card(cards, "Mega Brain Online", "Pronto para executar")
        self.s_gem = self._status_card(cards, "Gemini Online", "IA principal")
        self.s_groq = self._status_card(cards, "Groq Online", "Fallback ativo")
        self.s_mem = self._status_card(cards, "Memória Ativa", "Histórico preservado")
        login_card = tk.Frame(cards, bg=PANEL2, highlightthickness=1, highlightbackground="#0a5fa8", padx=10, pady=7)
        login_card.pack(side=tk.LEFT, fill=tk.X, padx=4)
        self.login_top = tk.Button(login_card, text="◯  Login\nCadastre-se", fg=FG, bg=PANEL2, bd=0, font=("Segoe UI", 9, "bold"), command=self.login_dialog)
        self.login_top.pack()

        mainrow = tk.Frame(f, bg=BG)
        mainrow.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        center = tk.Frame(mainrow, bg=BG)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        hero = tk.Frame(center, bg=BG, highlightthickness=1, highlightbackground="#06365f")
        hero.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(hero, bg="#020a17", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.brain = v4.v3.NeuralHero(self.canvas, self.settings)
        self.brain.start()
        self.canvas.bind("<Configure>", lambda e: self._hero_overlay())

        quick = tk.Frame(center, bg=PANEL, highlightthickness=1, highlightbackground="#0a4d83")
        quick.pack(fill=tk.X, pady=(5, 5))
        for icon, label, sub in [
            ("▣", "Analisar", "Documentos e dados"), ("💡", "Criar", "Conteúdos e ideias"),
            ("⚙", "Automatizar", "Processos e tarefas"), ("⌕", "Pesquisar", "Informações"),
            ("◎", "Resolver", "Problemas complexos"),
        ]:
            q = tk.Frame(quick, bg=PANEL2, padx=9, pady=7, highlightthickness=1, highlightbackground="#0b4b86")
            q.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3, pady=4)
            tk.Label(q, text=icon, fg=CYAN, bg=PANEL2, font=("Segoe UI", 14)).pack(side=tk.LEFT, padx=(0, 6))
            tt = tk.Frame(q, bg=PANEL2); tt.pack(side=tk.LEFT)
            tk.Label(tt, text=label, fg=FG, bg=PANEL2, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            tk.Label(tt, text=sub, fg=MUTED, bg=PANEL2, font=("Segoe UI", 7)).pack(anchor="w")

        cmd = tk.Frame(center, bg=PANEL, highlightthickness=1, highlightbackground="#0b4b86")
        cmd.pack(fill=tk.X)
        tabs = tk.Frame(cmd, bg=PANEL); tabs.pack(fill=tk.X, padx=8, pady=(5, 0))
        for label, fn in [("Texto", lambda: None), ("Áudio", self.pick_audio), ("Imagem", self.pick_image), ("Arquivo", self.pick_file)]:
            tk.Button(tabs, text=label, fg=FG, bg="#0b2b5e" if label == "Texto" else PANEL, bd=0, padx=16, pady=6, command=fn).pack(side=tk.LEFT, padx=2)
        tk.Label(tabs, text="Modo Avançado  ◯", fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=8)

        self.input = tk.Text(cmd, height=4, bg=PANEL, fg=FG, insertbackground=FG, font=("Segoe UI", 10), bd=0, padx=12, pady=9, wrap=tk.WORD)
        self.input.pack(fill=tk.X, padx=6)
        self.input.insert("1.0", "")
        self.input.bind("<Return>", self.enter)

        actions = tk.Frame(cmd, bg=PANEL); actions.pack(fill=tk.X, padx=10, pady=(2, 7))
        tk.Button(actions, text="📎", fg=FG, bg=PANEL, bd=0, command=self.pick_file).pack(side=tk.LEFT)
        tk.Button(actions, text="🖼", fg=FG, bg=PANEL, bd=0, command=self.pick_image).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="🎙", fg=FG, bg=PANEL, bd=0, command=self.pick_audio).pack(side=tk.LEFT, padx=4)
        self.attach_label = tk.Label(actions, text="Nenhum anexo", fg=MUTED, bg=PANEL, font=("Segoe UI", 8))
        self.attach_label.pack(side=tk.LEFT, padx=8)
        tk.Label(actions, text="Shift + Enter para nova linha", fg=MUTED, bg=PANEL, font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=8)
        self.runbtn = tk.Button(actions, text="▶  EXECUTAR", fg="white", bg="#078bff", activebackground="#0aa8ff", font=("Segoe UI", 10, "bold"), bd=0, padx=24, pady=9, command=self.execute)
        self.runbtn.pack(side=tk.RIGHT)

        rec = tk.Frame(center, bg=PANEL, highlightthickness=1, highlightbackground="#0a4d83")
        rec.pack(fill=tk.X, pady=(5, 0))
        head = tk.Frame(rec, bg=PANEL); head.pack(fill=tk.X, padx=10, pady=(7, 2))
        tk.Label(head, text="♙  Tarefas Recentes", fg=FG, bg=PANEL, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(head, text="Ver todas  →", fg=CYAN, bg=PANEL, bd=0, command=lambda: self.switch("history")).pack(side=tk.RIGHT)
        self.recent_box = tk.Frame(rec, bg=PANEL); self.recent_box.pack(fill=tk.X, padx=10, pady=(0, 7))
        self.render_recent([])

        right = tk.Frame(mainrow, bg=BG, width=260)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0))
        right.pack_propagate(False)
        self._right_login(right)
        self._right_tools(right)
        self._right_stats(right)

    def _hero_overlay(self):
        c = self.canvas; w = max(2, c.winfo_width()); h = max(2, c.winfo_height())
        c.delete("v5overlay")
        c.create_text(w-28, h*.63, text="AUTOMAÇÃO\nESTRATÉGIA\nPRODUTIVIDADE\nSEM LIMITES", anchor="e", justify="right", fill=BLUE, font=("Segoe UI", 9, "bold"), tags="v5overlay")
        c.create_text(w-28, h*.78, text="BINEXORA", anchor="e", fill=FG, font=("Segoe UI", 10, "bold"), tags="v5overlay")

    def _right_login(self, parent):
        box = tk.Frame(parent, bg=PANEL2, highlightthickness=1, highlightbackground="#0a5fa8", padx=10, pady=10)
        box.pack(fill=tk.X, pady=(0, 8))
        self.user_title = tk.Label(box, text="Olá, usuário!", fg=FG, bg=PANEL2, font=("Segoe UI", 10, "bold")); self.user_title.pack(anchor="w")
        tk.Label(box, text="Faça login para usar seu perfil local e acessar seus recursos.", wraplength=220, justify="left", fg=MUTED, bg=PANEL2, font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 8))
        tk.Button(box, text="Entrar", fg="white", bg="#078bff", bd=0, pady=7, command=self.login_dialog).pack(fill=tk.X, pady=3)
        tk.Button(box, text="Criar conta", fg=FG, bg=PANEL2, highlightthickness=1, highlightbackground=CYAN, bd=0, pady=7, command=self.register_dialog).pack(fill=tk.X, pady=3)

    def _right_tools(self, parent):
        box = tk.Frame(parent, bg=PANEL2, highlightthickness=1, highlightbackground="#0a5fa8", padx=10, pady=10)
        box.pack(fill=tk.X, pady=8)
        tk.Label(box, text="Ferramentas Rápidas", fg=FG, bg=PANEL2, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        for text, fn in [("▣  Resumo de PDF", self.pick_file), ("▧  Análise de Imagem", self.pick_image), ("🎙  Transcrever Áudio", self.pick_audio), ("✦  Criar Imagens (IA)", lambda: self._prefill("Crie uma imagem com a seguinte descrição: ")), ("⌕  Pesquisa na Web", lambda: self._prefill("Pesquise na web: ")), ("⌘  Gerar Código", lambda: self._prefill("Gere código para: "))]:
            tk.Button(box, text=text, anchor="w", fg="#d9eaff", bg=PANEL2, activebackground="#0d3470", bd=0, pady=5, command=fn).pack(fill=tk.X)

    def _right_stats(self, parent):
        box = tk.Frame(parent, bg=PANEL2, highlightthickness=1, highlightbackground="#0a5fa8", padx=10, pady=10)
        box.pack(fill=tk.X, pady=8)
        tk.Label(box, text="Estatísticas", fg=FG, bg=PANEL2, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        for name, val in [("Tarefas executadas", "—"), ("Arquivos analisados", "—"), ("Ideias geradas", "—"), ("Taxa de sucesso", "—")]:
            r = tk.Frame(box, bg=PANEL2); r.pack(fill=tk.X, pady=3)
            tk.Label(r, text=name, fg=MUTED, bg=PANEL2, font=("Segoe UI", 8)).pack(side=tk.LEFT)
            tk.Label(r, text=val, fg=FG, bg=PANEL2, font=("Segoe UI", 8, "bold")).pack(side=tk.RIGHT)

    def _prefill(self, text):
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self.input.focus_set()

    def _attach(self, path: str):
        if path and path not in self.attachments:
            self.attachments.append(path)
        names = [Path(x).name for x in self.attachments[-3:]]
        self.attach_label.config(text=" • ".join(names) if names else "Nenhum anexo")

    def pick_file(self):
        p = filedialog.askopenfilename(title="Anexar arquivo")
        if p: self._attach(p)

    def pick_image(self):
        p = filedialog.askopenfilename(title="Anexar imagem", filetypes=[("Imagens", "*.png *.jpg *.jpeg *.webp *.gif"), ("Todos", "*.*")])
        if p: self._attach(p)

    def pick_audio(self):
        p = filedialog.askopenfilename(title="Anexar áudio", filetypes=[("Áudio", "*.mp3 *.wav *.m4a *.ogg *.flac"), ("Todos", "*.*")])
        if p: self._attach(p)

    def execute(self):
        if self.running:
            return
        objective = self.input.get("1.0", "end").strip()
        if not objective:
            return
        if self.attachments:
            objective += "\n\nArquivos anexados pelo usuário:\n" + "\n".join(f"- {p}" for p in self.attachments)
        self.input.delete("1.0", "end")
        self.input.insert("1.0", objective)
        super().execute()
        self.attachments = []
        self.attach_label.config(text="Nenhum anexo")

    def register_dialog(self):
        username = simpledialog.askstring("Mega Brain — Cadastro", "Escolha seu nome de usuário:", parent=self.root)
        if not username: return
        password = simpledialog.askstring("Mega Brain — Cadastro", "Crie uma senha:", parent=self.root, show="*")
        if not password or len(password) < 4:
            messagebox.showwarning("Mega Brain", "Use uma senha com pelo menos 4 caracteres.", parent=self.root); return
        salt = secrets.token_hex(16)
        data = {"username": username.strip(), "salt": salt, "password_hash": _password_hash(password, salt)}
        _save_profile(data); self.profile = data; self.logged_user = data["username"]; self._apply_login_state()
        messagebox.showinfo("Mega Brain", "Perfil local criado com sucesso.", parent=self.root)

    def login_dialog(self):
        if not self.profile:
            if messagebox.askyesno("Mega Brain", "Nenhum perfil local encontrado. Criar agora?", parent=self.root): self.register_dialog()
            return
        password = simpledialog.askstring("Mega Brain — Login", f"Senha de {self.profile.get('username','usuário')}:", parent=self.root, show="*")
        if password is None: return
        expected = self.profile.get("password_hash", ""); salt = self.profile.get("salt", "")
        if salt and secrets.compare_digest(_password_hash(password, salt), expected):
            self.logged_user = self.profile.get("username", "usuário"); self._apply_login_state()
        else:
            messagebox.showerror("Mega Brain", "Senha incorreta.", parent=self.root)

    def _apply_login_state(self):
        name = self.logged_user or "usuário"
        self.user_title.config(text=f"Olá, {name}!")
        self.login_top.config(text=f"◉  {name}\nPerfil local")


def selftest():
    v4.selftest()
    assert _password_hash("teste", "00" * 16) == _password_hash("teste", "00" * 16)
    print("MEGA BRAIN UI V5 SELFTEST: PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        App().run()
