import asyncio
import hmac
import json
import re
import secrets
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from . import adapters
from .config import Settings
from .database import (
    Conversation,
    Document,
    Event,
    Job,
    Message,
    connect,
    serialize,
    uid,
)
from .jobs import TERMINAL, JobManager


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatInput(Input):
    content: str = Field(min_length=1, max_length=16000)
    conversation_id: UUID | None = None


class Goal(Input):
    objective: str = Field(min_length=1, max_length=16000)


class TicketInput(Input):
    job_id: UUID


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


def create_app(settings=None):
    settings = settings or Settings()
    tickets = {}
    login_sessions: dict[str, float] = {}

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        engine, sessions = connect(settings.database_url)
        app.state.sessions = sessions
        app.state.jobs = JobManager(settings, sessions)
        app.state.jobs.recover()
        yield
        await app.state.jobs.close()
        engine.dispose()

    app = FastAPI(
        title="Mega Cérebro",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in settings.origins:
            from starlette.responses import JSONResponse

            return JSONResponse({"detail": "Origem não permitida"}, status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > settings.max_upload + 65536):
            from starlette.responses import JSONResponse

            return JSONResponse({"detail": "Requisição muito grande"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def auth(authorization: str = Header(default="")):
        expected = f"Bearer {settings.token}"
        if hmac.compare_digest(authorization, expected):
            return
        if authorization.startswith("Bearer "):
            session_token = authorization[7:]
            expires_at = login_sessions.get(session_token, 0)
            if expires_at > time.monotonic():
                return
            if session_token:
                login_sessions.pop(session_token, None)
        raise HTTPException(401, "Acesso privado. Informe suas credenciais.")

    def sessions():
        with app.state.sessions() as db:
            yield db

    def get_job(db, job_id):
        job = db.get(Job, str(job_id))
        if not job:
            raise HTTPException(404, "Execução não encontrada")
        return job

    def capacity():
        if len(app.state.jobs.tasks) >= 8:
            raise HTTPException(429, "Fila cheia. Aguarde uma execução terminar.")

    @app.post("/api/login", tags=["auth"])
    def login(body: LoginInput):
        if not settings.test_login_enabled:
            raise HTTPException(404, "Login de teste desativado")
        username_ok = hmac.compare_digest(body.username, settings.test_username)
        password_ok = hmac.compare_digest(body.password, settings.test_password)
        if not (username_ok and password_ok):
            raise HTTPException(401, "Usuário ou senha inválidos")
        for key, expires_at in list(login_sessions.items()):
            if expires_at <= time.monotonic():
                login_sessions.pop(key, None)
        if len(login_sessions) >= 32:
            raise HTTPException(429, "Muitas sessões de teste ativas")
        session_token = secrets.token_urlsafe(32)
        login_sessions[session_token] = time.monotonic() + 12 * 60 * 60
        return {"access_token": session_token, "token_type": "bearer", "expires_in": 43200}

    api = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    @api.get("/chat/conversations", tags=["chat"])
    def conversations(db=Depends(sessions)):
        return [
            serialize(c)
            for c in db.scalars(
                select(Conversation).order_by(Conversation.created_at.desc()).limit(200)
            )
        ]

    @api.get("/chat/conversations/{conversation_id}", tags=["chat"])
    def conversation(conversation_id: UUID, db=Depends(sessions)):
        if not db.get(Conversation, str(conversation_id)):
            raise HTTPException(404, "Conversa não encontrada")
        return [
            serialize(m)
            for m in db.scalars(
                select(Message)
                .where(Message.conversation_id == str(conversation_id))
                .order_by(Message.created_at, Message.id)
            )
        ]

    @api.post("/chat", status_code=202, tags=["chat"])
    async def chat(body: ChatInput, db=Depends(sessions)):
        capacity()
        cid = str(body.conversation_id) if body.conversation_id else uid()
        if body.conversation_id:
            if not db.get(Conversation, cid):
                raise HTTPException(404, "Conversa não encontrada")
            busy = db.scalar(
                select(Job).where(Job.conversation_id == cid, Job.state.not_in(TERMINAL))
            )
            if busy:
                raise HTTPException(409, "A conversa já tem uma resposta em processamento")
        else:
            db.add(Conversation(id=cid, title=body.content[:100]))
            db.flush()
        previous = [
            dict(role=m.role, content=m.content)
            for m in db.scalars(
                select(Message)
                .where(Message.conversation_id == cid, Message.state == "done")
                .order_by(Message.created_at.desc())
                .limit(30)
            )
        ][::-1]
        mid, jid = uid(), uid()
        db.add(Message(conversation_id=cid, role="user", content=body.content))
        db.add(Message(id=mid, conversation_id=cid, role="assistant", state="processing"))
        db.flush()
        db.add(
            Job(id=jid, kind="chat", objective=body.content, conversation_id=cid, message_id=mid)
        )
        db.commit()
        app.state.jobs.submit(
            jid, {"kind": "chat", "messages": previous, "objective": body.content}
        )
        return {"id": jid, "conversation_id": cid, "message_id": mid}

    @api.get("/executions", tags=["executions"])
    def executions(db=Depends(sessions)):
        return [
            serialize(j) for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(200))
        ]

    @api.post("/executions", status_code=202, tags=["executions"])
    async def execute(body: Goal, db=Depends(sessions)):
        capacity()
        job = Job(id=uid(), kind="execution", objective=body.objective)
        db.add(job)
        db.commit()
        app.state.jobs.submit(job.id, {"kind": "execution", "objective": body.objective})
        return serialize(job)

    @api.get("/executions/{job_id}", tags=["executions"])
    def execution(job_id: UUID, db=Depends(sessions)):
        return serialize(get_job(db, job_id))

    @api.post("/executions/{job_id}/cancel", tags=["executions"])
    async def cancel(job_id: UUID, db=Depends(sessions)):
        get_job(db, job_id)
        await app.state.jobs.cancel(str(job_id))
        return {"status": "cancelled"}

    @api.get("/memory", tags=["memory"])
    async def memory(q: str = "", db=Depends(sessions)):
        if len(q) > 1000:
            raise HTTPException(422, "Consulta muito longa")
        state = await asyncio.to_thread(lambda: adapters.memory(settings).load())
        matches = {
            k: v
            for k, v in state.items()
            if not q or q.lower() in json.dumps(v, ensure_ascii=False).lower()
        }
        return {
            "memory": matches,
            "sources": await asyncio.to_thread(adapters.query, settings, q) if q else [],
        }

    @api.get("/rag", tags=["rag"])
    async def rag(q: str = ""):
        if not q.strip() or len(q) > 1000:
            raise HTTPException(422, "Informe uma consulta de até 1000 caracteres")
        return {"sources": await asyncio.to_thread(adapters.query, settings, q)}

    @api.get("/documents", tags=["documents"])
    def documents(db=Depends(sessions)):
        return [
            {**serialize(d), "job": serialize(db.get(Job, d.job_id))}
            for d in db.scalars(select(Document).order_by(Document.created_at.desc()).limit(200))
        ]

    @api.post("/documents", status_code=202, tags=["documents"])
    async def upload(file: UploadFile = File(), db=Depends(sessions)):
        capacity()
        filename = file.filename or ""
        if not re.fullmatch(r"[^/\\\x00-\x1f]{1,200}", filename) or filename in (".", ".."):
            raise HTTPException(400, "Nome de arquivo inválido")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".txt", ".md", ".markdown", ".docx"}:
            raise HTTPException(415, "Formato não suportado")
        did, jid = uid(), uid()
        target = settings.data / "uploads" / did
        size = 0
        try:
            with target.open("xb") as out:
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > settings.max_upload:
                        raise HTTPException(413, "Limite de 20 MB por arquivo")
                    out.write(chunk)
            if not size:
                raise HTTPException(400, "Arquivo vazio")
            with target.open("rb") as data:
                head = data.read(1024)
            if suffix == ".pdf" and not head.startswith(b"%PDF-"):
                raise HTTPException(400, "PDF inválido")
            if suffix == ".docx":
                try:
                    with zipfile.ZipFile(target) as archive:
                        entries = archive.infolist()
                        if (
                            "word/document.xml" not in archive.namelist()
                            or sum(i.file_size for i in entries) > settings.max_upload * 4
                            or len(entries) > 2000
                        ):
                            raise ValueError()
                except (zipfile.BadZipFile, ValueError):
                    raise HTTPException(400, "DOCX inválido ou descompactação excessiva") from None
            elif suffix != ".pdf":
                try:
                    content = target.read_text(encoding="utf-8")
                    if "\x00" in content or len(content) > settings.max_text:
                        raise ValueError()
                except (UnicodeError, ValueError):
                    raise HTTPException(
                        400, "Use texto UTF-8 de até 2 milhões de caracteres"
                    ) from None
            db.add(Job(id=jid, kind="document", objective=filename))
            db.flush()
            db.add(Document(id=did, name=filename, size=size, job_id=jid))
            db.commit()
            app.state.jobs.submit(
                jid, {"kind": "document", "document_id": did, "filename": filename}
            )
            return {"id": did, "job_id": jid, "name": filename}
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @api.get("/agents", tags=["agents"])
    def agents():
        return adapters.agents()

    @api.get("/providers", tags=["providers"])
    async def providers():
        return await asyncio.to_thread(adapters.providers)

    @api.get("/status", tags=["status"])
    async def status(db=Depends(sessions)):
        import os
        import shutil

        try:
            db.execute(text("SELECT 1"))
            database = "online"
        except Exception:
            database = "error"
        provider_rows = await asyncio.to_thread(adapters.providers)
        return {
            "backend": "online",
            "engine": "online",
            "database": database,
            "memory": "online" if (settings.data / "memory").exists() else "not_configured",
            "rag": "online"
            if (adapters.app_index_dir(settings) / "chunks.json").exists()
            else "not_configured",
            "executor": "online",
            "websocket": "available",
            "command_sandbox": "configured"
            if shutil.which("docker") and os.getenv("APP_SANDBOX_IMAGE")
            else "not_configured",
            "providers": provider_rows,
            "provider": adapters.llm_router.resolve_provider(),
            "scope": "single_operator",
            "queue": len(app.state.jobs.tasks),
        }

    @api.post("/ws-ticket", tags=["realtime"])
    def ticket(body: TicketInput, db=Depends(sessions)):
        job = get_job(db, body.job_id)
        for key, value in list(tickets.items()):
            if value[1] < time.monotonic():
                tickets.pop(key, None)
        if len(tickets) > 100:
            raise HTTPException(429, "Muitas conexões solicitadas")
        value = secrets.token_urlsafe(32)
        tickets[value] = (job.id, time.monotonic() + 30)
        return {"ticket": value}

    app.include_router(api)

    async def stream(ws: WebSocket, channel):
        # Ticket travels in the first message, never in a URL/access log.
        if ws.headers.get("origin") not in settings.origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            hello = json.loads(await asyncio.wait_for(ws.receive_text(), 5))
            value = tickets.pop(hello.get("ticket", ""), None)
            if not value or value[1] < time.monotonic():
                await ws.close(code=1008)
                return
            jid = value[0]
            after = max(0, int(hello.get("after", 0)))
            with app.state.sessions() as db:
                job = db.get(Job, jid)
                if (channel == "chat") != (job.kind == "chat"):
                    await ws.close(code=1008)
                    return
            while True:
                with app.state.sessions() as db:
                    events = list(
                        db.scalars(
                            select(Event)
                            .where(Event.job_id == jid, Event.id > after)
                            .order_by(Event.id)
                            .limit(100)
                        )
                    )
                    done = db.get(Job, jid).state in TERMINAL
                    for event in events:
                        await ws.send_json({"id": event.id, **event.payload})
                        after = event.id
                if done and len(events) < 100:
                    await ws.close(code=1000)
                    return
                if not events:
                    await ws.send_json({"type": "heartbeat"})
                await asyncio.sleep(0.2)
        except Exception:
            try:
                await ws.close(code=1008)
            except RuntimeError:
                pass

    @app.websocket("/ws/chat")
    async def ws_chat(ws: WebSocket):
        await stream(ws, "chat")

    @app.websocket("/ws/executions")
    async def ws_executions(ws: WebSocket):
        await stream(ws, "executions")

    return app


app = create_app()
