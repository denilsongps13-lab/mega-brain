#!/usr/bin/env python3
from __future__ import annotations

import json, math, os, queue, random, sys, threading, time, tkinter as tk
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

BG="#020814"; SIDEBAR="#03101d"; PANEL="#061426"; PANEL2="#07192d"; BORDER="#0a5fb8"
BLUE="#0b8cff"; CYAN="#22dfff"; FG="#eef7ff"; MUTED="#8ea9c3"; GREEN="#18f58d"; RED="#ff4f6d"
SETTINGS=ROOT/".data"/"megabrain"/"ui-premium.json"
DEFAULTS={"animation":True,"intensity":"high","reduce":False}

def load_settings():
    try:
        if SETTINGS.exists():
            d=DEFAULTS.copy(); d.update(json.loads(SETTINGS.read_text(encoding="utf-8"))); return d
    except Exception: pass
    return DEFAULTS.copy()

def save_settings(d):
    try:
        SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        SETTINGS.write_text(json.dumps(d,indent=2),encoding="utf-8")
    except Exception: pass

class NeuralHero:
    IDLE="idle"; THINKING="thinking"; PLANNING="planning"; EXECUTING="executing"; DONE="done"; ERROR="error"
    def __init__(self,canvas,settings):
        self.c=canvas; self.settings=settings; self.state=self.IDLE; self.state_t=time.time()
        self.nodes=[]; self.edges=[]; self.pulses=[]; self.stars=[]; self.rng=random.Random(5588)
        self.after=None; self.running=False; self.last_size=(0,0)

    def set_state(self,state): self.state=state; self.state_t=time.time()
    def apply(self,s): self.settings=s; self.last_size=(0,0)
    def start(self): self.running=True; self.tick()
    def stop(self):
        self.running=False
        if self.after:
            try:self.c.after_cancel(self.after)
            except Exception:pass

    def _inside(self,x,y,cx,cy,bw,bh):
        lobes=[
            (cx-bw*.24,cy-bh*.08,bw*.31,bh*.40),
            (cx+bw*.08,cy-bh*.10,bw*.34,bh*.42),
            (cx+bw*.25,cy+bh*.06,bw*.24,bh*.31),
            (cx-bw*.08,cy+bh*.11,bw*.35,bh*.30),
        ]
        inside=any(((x-lx)/rx)**2+((y-ly)/ry)**2<=1 for lx,ly,rx,ry in lobes)
        cere=((x-(cx+bw*.28))/(bw*.19))**2+((y-(cy+bh*.30))/(bh*.18))**2<=1
        notch=(abs(x-cx)<bw*.025 and y<cy-bh*.04)
        return (inside or cere) and not notch

    def build(self,w,h):
        self.nodes=[]; self.edges=[]; self.pulses=[]; self.stars=[]
        cx,cy=w*.52,h*.43; bw=min(w*.58,h*.86); bh=bw*.65
        n={"low":120,"medium":170,"high":230}.get(self.settings.get("intensity"),200)
        tries=0
        while len(self.nodes)<n and tries<n*40:
            tries+=1
            x=self.rng.uniform(cx-bw*.55,cx+bw*.55); y=self.rng.uniform(cy-bh*.52,cy+bh*.50)
            if self._inside(x,y,cx,cy,bw,bh):
                self.nodes.append([x,y,self.rng.random()*6.28,self.rng.uniform(1.0,2.4)])
        maxd=bw*.105
        for i,a in enumerate(self.nodes):
            near=[]
            for j,b in enumerate(self.nodes):
                if i==j:continue
                d=math.hypot(a[0]-b[0],a[1]-b[1])
                if d<maxd: near.append((d,j))
            for _,j in sorted(near)[:5]:
                if i<j:self.edges.append((i,j))
        for _ in range(max(38,n//4)):
            if self.edges:self.pulses.append([self.rng.randrange(len(self.edges)),self.rng.random(),self.rng.uniform(.0035,.012)])
        for _ in range(130):
            self.stars.append((self.rng.randrange(max(1,w)),self.rng.randrange(max(1,h)),self.rng.uniform(.4,1.7),self.rng.random()*6.28))
        self.last_size=(w,h)

    @staticmethod
    def hx(rgb):
        return "#%02x%02x%02x"%tuple(max(0,min(255,int(v))) for v in rgb)
    @staticmethod
    def mix(a,b,t): return tuple(a[i]+(b[i]-a[i])*t for i in range(3))

    def tick(self):
        if not self.running:return
        self.draw()
        fps=12 if self.settings.get("reduce") else 25
        self.after=self.c.after(int(1000/fps),self.tick)

    def draw(self):
        self.c.delete("neural")
        w=max(2,self.c.winfo_width()); h=max(2,self.c.winfo_height())
        if not self.settings.get("animation",True):
            return
        if not self.nodes or abs(w-self.last_size[0])>24 or abs(h-self.last_size[1])>24:
            self.build(w,h)

        t=time.time()
        base=(0,170,255); pulse=.78+.22*(.5+.5*math.sin(t*1.35))
        if self.state==self.THINKING: pulse=.88+.12*(.5+.5*math.sin(t*2.0))
        elif self.state==self.PLANNING: pulse=.86+.14*(.5+.5*math.sin(t*2.5)); base=(55,180,255)
        elif self.state==self.EXECUTING: pulse=.90+.10*(.5+.5*math.sin(t*3.2)); base=(20,220,255)
        elif self.state==self.DONE and t-self.state_t<1.2: base=self.mix(base,(24,245,141),.70)
        elif self.state==self.ERROR and t-self.state_t<1.2: base=self.mix(base,(255,79,109),.78)
        elif self.state in (self.DONE,self.ERROR): self.state=self.IDLE

        for x,y,r,ph in self.stars:
            a=.18+.82*(.5+.5*math.sin(t*.75+ph))
            col=self.hx(tuple(v*a*.60 for v in base))
            self.c.create_oval(x-r,y-r,x+r,y+r,fill=col,outline="",tags="neural")

        for k in range(5):
            pts=[]
            yy=h*(.28+.08*k); amp=h*(.04+.01*k)
            for q in range(22):
                x=w*q/21
                y=yy+math.sin(q*.6+t*.35+k)*amp + math.sin(q*.21+k)*12
                pts.extend((x,y))
            self.c.create_line(*pts,smooth=True,fill=self.hx(tuple(v*.16 for v in base)),width=2,tags="neural")

        for i,j in self.edges:
            a=self.nodes[i]; b=self.nodes[j]
            self.c.create_line(a[0],a[1],b[0],b[1],fill=self.hx(tuple(v*pulse*.10 for v in base)),width=5,tags="neural")
            self.c.create_line(a[0],a[1],b[0],b[1],fill=self.hx(tuple(v*pulse*.42 for v in base)),width=1,tags="neural")

        for x,y,ph,r in self.nodes:
            tw=.45+.55*(.5+.5*math.sin(t*2.1+ph))
            halo=self.hx(tuple(v*pulse*tw*.22 for v in base))
            core=self.hx(tuple(v*pulse*tw for v in base))
            rr=r*4.8
            self.c.create_oval(x-rr,y-rr,x+rr,y+rr,fill=halo,outline="",tags="neural")
            rr=r
            self.c.create_oval(x-rr,y-rr,x+rr,y+rr,fill=core,outline="",tags="neural")

        speed=1.9 if self.state==self.EXECUTING else 1.0
        for p in self.pulses:
            p[1]=(p[1]+p[2]*speed)%1.0
            i,j=self.edges[p[0]]; a=self.nodes[i]; b=self.nodes[j]
            x=a[0]+(b[0]-a[0])*p[1]; y=a[1]+(b[1]-a[1])*p[1]
            self.c.create_oval(x-7,y-7,x+7,y+7,fill="#073968",outline="",tags="neural")
            self.c.create_oval(x-2.4,y-2.4,x+2.4,y+2.4,fill="#e6fdff",outline="",tags="neural")

        self.c.create_text(w*.52,h*.80,text="MEGA BRAIN",fill="#f4fbff",font=("Segoe UI",30,"bold"),tags="neural")
        self.c.create_text(w*.52,h*.87,text="M A I S   Q U E   I A ,   É   O   S E U   A L I A D O",fill=BLUE,font=("Segoe UI",11),tags="neural")
        self.c.create_line(w*.47,h*.92,w*.57,h*.92,fill=CYAN,width=3,tags="neural")
        self.c.create_text(26,h*.56,text="INTELIGÊNCIA\nQUE TRANSFORMA\nIDEIAS EM\nRESULTADOS",anchor="w",justify="left",fill=BLUE,font=("Segoe UI",11,"bold"),tags="neural")
        self.c.create_line(28,h*.72,78,h*.72,fill=CYAN,width=3,tags="neural")
        self.c.create_text(w-26,h*.66,text="AUTOMAÇÃO\nESTRATÉGIA\nPRODUTIVIDADE\nSEM LIMITES",anchor="e",justify="right",fill=BLUE,font=("Segoe UI",10,"bold"),tags="neural")
        self.c.create_line(w-82,h*.82,w-30,h*.82,fill=CYAN,width=3,tags="neural")
        self.c.create_text(w-30,24,text="PENSAR\nPLANEJAR\nEXECUTAR\nEVOLUIR",anchor="ne",justify="center",fill="#d7e7f7",font=("Segoe UI",10,"italic"),tags="neural")

class App:
    def __init__(self):
        self.root=tk.Tk(); self.root.title("Mega Brain"); self.root.configure(bg=BG)
        self.root.geometry("1240x900"); self.root.minsize(1050,760)
        self.phase_q=queue.Queue(); self.result_q=queue.Queue(); self.worker=None
        self.running=False; self.settings=load_settings(); self.views={}; self.brain=None
        self.build(); self.root.after(100,self.poll); self.root.after(400,self.refresh_status)
        self.root.protocol("WM_DELETE_WINDOW",self.close)

    def card(self,parent,title,sub):
        f=tk.Frame(parent,bg=PANEL2,highlightthickness=1,highlightbackground="#0b4b86",padx=12,pady=8)
        f.pack(side=tk.LEFT,fill=tk.X,expand=True,padx=6)
        tk.Label(f,text="●",fg=GREEN,bg=PANEL2,font=("Segoe UI",20,"bold")).pack(side=tk.LEFT,padx=(0,8))
        t=tk.Frame(f,bg=PANEL2); t.pack(side=tk.LEFT)
        tk.Label(t,text=title,fg=FG,bg=PANEL2,font=("Segoe UI",10,"bold")).pack(anchor="w")
        lab=tk.Label(t,text=sub,fg=MUTED,bg=PANEL2,font=("Segoe UI",9)); lab.pack(anchor="w"); return lab

    def build(self):
        title=tk.Frame(self.root,bg="#04101d",height=34); title.pack(fill=tk.X); title.pack_propagate(False)
        tk.Label(title,text="🧠  Mega Brain",fg=FG,bg="#04101d",font=("Segoe UI",10,"bold"),padx=10).pack(side=tk.LEFT,pady=7)

        body=tk.Frame(self.root,bg=BG); body.pack(fill=tk.BOTH,expand=True)
        side=tk.Frame(body,bg=SIDEBAR,width=228,highlightthickness=1,highlightbackground="#06365f")
        side.pack(side=tk.LEFT,fill=tk.Y); side.pack_propagate(False)
        tk.Label(side,text="🧠",fg=CYAN,bg=SIDEBAR,font=("Segoe UI Emoji",36)).pack(pady=(20,0))
        tk.Label(side,text="MEGA BRAIN",fg=FG,bg=SIDEBAR,font=("Segoe UI",19,"bold")).pack()
        tk.Label(side,text="Sua inteligência em ação",fg=MUTED,bg=SIDEBAR,font=("Segoe UI",9)).pack(pady=(2,26))

        for icon,label,key in [("💬","Nova tarefa","chat"),("▣","Memória","memory"),("▤","Contexto","context"),("▥","Status","status"),("⚙","Configurações","settings")]:
            bg="#0a2850" if key=="chat" else SIDEBAR
            b=tk.Button(side,text=f"{icon}   {label}",anchor="w",fg=FG,bg=bg,activebackground="#0d3470",activeforeground=FG,
                        font=("Segoe UI",11),bd=0,padx=18,pady=13,command=lambda k=key:self.switch(k))
            b.pack(fill=tk.X,padx=10,pady=3)
        tk.Label(side,text="Ideias\nAutomação\nResultados",justify="left",fg="#c9e9ff",bg=SIDEBAR,font=("Segoe Script",16,"italic")).pack(side=tk.BOTTOM,anchor="w",padx=28,pady=30)

        self.content=tk.Frame(body,bg=BG); self.content.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        self.build_chat(); self.build_simple("memory","MEMÓRIA","Histórico e memória persistente do Mega Brain.")
        self.build_simple("context","CONTEXTO","Contexto atual do projeto e ambiente de execução.")
        self.build_simple("status","STATUS","Estado dos provedores, executor e memória.")
        self.build_settings(); self.switch("chat")

    def build_chat(self):
        f=tk.Frame(self.content,bg=BG); self.views["chat"]=f
        cards=tk.Frame(f,bg=BG); cards.pack(fill=tk.X,padx=8,pady=(10,5))
        self.s_mb=self.card(cards,"Mega Brain Online","Pronto para executar")
        self.s_gem=self.card(cards,"Gemini Online","IA principal")
        self.s_groq=self.card(cards,"Groq Online","Fallback ativo")
        self.s_mem=self.card(cards,"Memória Ativa","Histórico preservado")

        hero=tk.Frame(f,bg=BG,highlightthickness=1,highlightbackground="#06365f")
        hero.pack(fill=tk.BOTH,expand=True,padx=8,pady=4)
        self.canvas=tk.Canvas(hero,bg="#020a17",highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH,expand=True)
        self.brain=NeuralHero(self.canvas,self.settings); self.brain.start()

        cmd=tk.Frame(f,bg=PANEL,highlightthickness=1,highlightbackground="#0b4b86")
        cmd.pack(fill=tk.X,padx=8,pady=(6,4))
        left=tk.Frame(cmd,bg=PANEL); left.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        self.input=tk.Text(left,height=3,bg=PANEL,fg=FG,insertbackground=FG,font=("Segoe UI",11),bd=0,padx=14,pady=11,wrap=tk.WORD)
        self.input.pack(fill=tk.BOTH,expand=True); self.input.bind("<Return>",self.enter)
        tools=tk.Frame(left,bg=PANEL); tools.pack(fill=tk.X,padx=12,pady=(0,8))
        tk.Label(tools,text="📎    ◉    ⚙",fg="#c9d8e7",bg=PANEL,font=("Segoe UI",12)).pack(side=tk.LEFT)
        tk.Label(tools,text="Enter: executar  |  Shift + Enter: nova linha",fg=MUTED,bg=PANEL,font=("Segoe UI",8)).pack(side=tk.RIGHT)
        self.runbtn=tk.Button(cmd,text="▶  EXECUTAR",fg="white",bg="#078cf0",activebackground="#0aa7ff",font=("Segoe UI",11,"bold"),
                              bd=0,padx=26,pady=16,command=self.execute)
        self.runbtn.pack(side=tk.RIGHT,fill=tk.Y,padx=10,pady=10)

        recent=tk.Frame(f,bg=PANEL,highlightthickness=1,highlightbackground="#06365f")
        recent.pack(fill=tk.X,padx=8,pady=(4,8))
        hdr=tk.Frame(recent,bg=PANEL); hdr.pack(fill=tk.X,padx=14,pady=(8,3))
        tk.Label(hdr,text="Tarefas recentes",fg=FG,bg=PANEL,font=("Segoe UI",10,"bold")).pack(side=tk.LEFT)
        tk.Label(hdr,text="Ver todas  →",fg=BLUE,bg=PANEL,font=("Segoe UI",9)).pack(side=tk.RIGHT)
        self.recent_box=tk.Frame(recent,bg=PANEL); self.recent_box.pack(fill=tk.X,padx=12,pady=(0,8))
        self.render_recent([])

    def build_simple(self,key,title,text):
        f=tk.Frame(self.content,bg=BG); self.views[key]=f
        tk.Label(f,text=title,fg=FG,bg=BG,font=("Segoe UI",22,"bold")).pack(anchor="w",padx=28,pady=(28,8))
        box=tk.Text(f,bg=PANEL,fg=FG,font=("Consolas",11),bd=0,padx=16,pady=16)
        box.pack(fill=tk.BOTH,expand=True,padx=28,pady=(0,28)); box.insert("1.0",text)

    def build_settings(self):
        f=tk.Frame(self.content,bg=BG); self.views["settings"]=f
        tk.Label(f,text="CONFIGURAÇÕES",fg=FG,bg=BG,font=("Segoe UI",22,"bold")).pack(anchor="w",padx=28,pady=(28,18))
        self.v_anim=tk.BooleanVar(value=self.settings.get("animation",True))
        self.v_reduce=tk.BooleanVar(value=self.settings.get("reduce",False))
        self.v_int=tk.StringVar(value=self.settings.get("intensity","high"))
        tk.Checkbutton(f,text="Animação neural ativada",variable=self.v_anim,fg=FG,bg=BG,selectcolor=PANEL,activebackground=BG,command=self.save_ui).pack(anchor="w",padx=32,pady=8)
        tk.Checkbutton(f,text="Reduzir animações",variable=self.v_reduce,fg=FG,bg=BG,selectcolor=PANEL,activebackground=BG,command=self.save_ui).pack(anchor="w",padx=32,pady=8)
        row=tk.Frame(f,bg=BG); row.pack(anchor="w",padx=32,pady=8)
        tk.Label(row,text="Intensidade:",fg=FG,bg=BG).pack(side=tk.LEFT)
        tk.OptionMenu(row,self.v_int,"low","medium","high",command=lambda _=None:self.save_ui()).pack(side=tk.LEFT,padx=10)

    def save_ui(self):
        self.settings={"animation":self.v_anim.get(),"reduce":self.v_reduce.get(),"intensity":self.v_int.get()}
        save_settings(self.settings); self.brain.apply(self.settings)

    def render_recent(self,items):
        for w in self.recent_box.winfo_children():w.destroy()
        if not items:
            items=[("Criar arquivo ola.txt com 'BOM DIA'","Concluído",GREEN),
                   ("Verificar status do sistema","Concluído",GREEN),
                   ("Analisar pasta do projeto","Processando...",BLUE),
                   ("Instalar dependências","Pendente",MUTED)]
        for task,status,color in items[-4:]:
            r=tk.Frame(self.recent_box,bg=PANEL); r.pack(fill=tk.X,pady=2)
            tk.Label(r,text="●",fg=color,bg=PANEL,font=("Segoe UI",12,"bold")).pack(side=tk.LEFT)
            tk.Label(r,text=task[:84],fg=FG,bg=PANEL,font=("Segoe UI",9)).pack(side=tk.LEFT,padx=8)
            tk.Label(r,text=status,fg=color,bg=PANEL,font=("Segoe UI",9,"bold")).pack(side=tk.RIGHT,padx=8)

    def switch(self,key):
        for v in self.views.values(): v.pack_forget()
        self.views[key].pack(fill=tk.BOTH,expand=True)

    def enter(self,e):
        if e.state & 1:return
        self.execute(); return "break"

    def execute(self):
        if self.running:return
        objective=self.input.get("1.0","end").strip()
        if not objective:return
        self.running=True; self.runbtn.config(state=tk.DISABLED,text="EXECUTANDO...")
        self.brain.set_state(NeuralHero.THINKING)
        def work():
            try:
                from engine.executor.executor import execute_objective
                def obs(name,payload): self.phase_q.put((name,payload))
                def confirm(reason):
                    ev=threading.Event(); holder=[False]
                    self.phase_q.put(("permission",reason,ev,holder)); ev.wait(300); return holder[0]
                res=execute_objective(objective,permission_mode="ask",phase_observer=obs,confirmer=confirm)
            except Exception as ex:
                res={"success":False,"error":str(ex)}
            self.result_q.put((objective,res))
        self.worker=threading.Thread(target=work,daemon=True); self.worker.start()

    def poll(self):
        try:
            while True:
                x=self.phase_q.get_nowait(); name=x[0]
                if name=="permission":
                    _,reason,ev,holder=x
                    holder[0]=messagebox.askyesno("Mega Brain — Permissão",reason,parent=self.root); ev.set(); continue
                mapping={"thinking":NeuralHero.THINKING,"planning":NeuralHero.PLANNING,"executing":NeuralHero.EXECUTING,
                         "validating":NeuralHero.EXECUTING,"done":NeuralHero.DONE,"error":NeuralHero.ERROR}
                self.brain.set_state(mapping.get(name,NeuralHero.IDLE))
        except queue.Empty: pass
        try:
            while True:
                objective,res=self.result_q.get_nowait(); ok=bool(res.get("success")); self.running=False
                self.runbtn.config(state=tk.NORMAL,text="▶  EXECUTAR")
                self.brain.set_state(NeuralHero.DONE if ok else NeuralHero.ERROR)
                self.input.delete("1.0","end")
                self.render_recent([(objective,"Concluído" if ok else "Erro",GREEN if ok else RED)])
                if not ok: messagebox.showerror("Mega Brain",res.get("error") or "Execução falhou",parent=self.root)
        except queue.Empty: pass
        self.root.after(100,self.poll)

    def refresh_status(self):
        try:
            from engine.intelligence.pipeline.mce.llm_router import is_provider_available
            g=is_provider_available("gemini"); q=is_provider_available("groq")
            self.s_gem.config(text="IA principal" if g else "Não configurado",fg=GREEN if g else MUTED)
            self.s_groq.config(text="Fallback ativo" if q else "Não configurado",fg=GREEN if q else MUTED)
        except Exception: pass
        self.root.after(10000,self.refresh_status)

    def close(self):
        if self.brain:self.brain.stop()
        self.root.destroy()
    def run(self): self.root.mainloop()

def selftest():
    import tempfile, shutil
    from engine.executor.executor import execute_objective
    td=Path(tempfile.mkdtemp(prefix="mb_ui_v3_"))
    try:
        class Stub:
            kind="stub"
            def plan(self,o,c):
                return {"goal":o,"steps":[{"id":"1","action":"write","params":{"path":"ok.txt","content":"ok"}}],"validation":"manual","planner":"stub"}
        r=execute_objective("ui v3 selftest",workspace=str(td),planner=Stub(),confirmer=lambda _:True)
        assert r.get("success") and (td/"ok.txt").exists()
        print("MEGA BRAIN UI V3 SELFTEST: PASS")
    finally:
        shutil.rmtree(td,ignore_errors=True)

if __name__=="__main__":
    if "--selftest" in sys.argv:selftest()
    else:App().run()
