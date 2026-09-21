import asyncio
import json
import os
import signal
import sys

from sqlalchemy import select

from .config import ROOT
from .database import Event, Job, Message

TERMINAL = {"done", "error", "cancelled", "partial"}


class JobManager:
    """One worker at a time: memory and index updates stay serialized in this MVP."""

    def __init__(self, settings, sessions):
        self.settings = settings
        self.sessions = sessions
        self.tasks = {}
        self.processes = {}
        self.lock = asyncio.Lock()

    def recover(self):
        with self.sessions() as db:
            for job in db.scalars(select(Job).where(Job.state.not_in(TERMINAL))):
                job.state = "error"
                job.result = {"error": "Execução interrompida por reinício. Inicie novamente."}
                db.add(Event(job_id=job.id, payload={"type": "terminal", "state": "error"}))
                if job.message_id:
                    db.get(Message, job.message_id).state = "error"
            db.commit()

    def submit(self, job_id, request):
        if len(self.tasks) >= 8:
            raise ValueError("Fila cheia")
        self.tasks[job_id] = asyncio.create_task(self.run(job_id, request))
        self.tasks[job_id].add_done_callback(lambda _: self.tasks.pop(job_id, None))

    def record(self, job_id, payload):
        with self.sessions() as db:
            job = db.get(Job, job_id)
            if job.state in TERMINAL:
                return
            if payload["type"] == "phase":
                job.state = payload["state"]
                job.progress = payload.get("progress", job.progress)
            if payload["type"] == "result":
                job.result = payload["result"]
            if payload["type"] == "error":
                job.result = {"error": payload["message"]}
            if job.message_id:
                message = db.get(Message, job.message_id)
                if payload["type"] == "delta":
                    message.content += payload["text"]
                elif payload["type"] in ("provider", "context"):
                    message.details = {**message.details, payload["type"]: payload}
            db.add(Event(job_id=job_id, payload=payload))
            db.commit()

    def finish(self, job_id, state):
        with self.sessions() as db:
            job = db.get(Job, job_id)
            if job.state in TERMINAL:
                return
            job.state = state
            if state == "done":
                job.progress = 100
            if job.message_id:
                db.get(Message, job.message_id).state = state
            db.add(Event(job_id=job_id, payload={"type": "terminal", "state": state}))
            db.commit()

    async def run(self, job_id, request):
        proc = None
        try:
            async with self.lock:
                with self.sessions() as db:
                    if db.get(Job, job_id).state in TERMINAL:
                        return
                env = {
                    **os.environ,
                    "APP_DATA_DIR": str(self.settings.data),
                    "APP_JOB_ID": job_id,
                    "APP_WORKSPACE": str(self.settings.workspace),
                    "PYTHONPATH": str(ROOT) + os.pathsep + str(ROOT / "apps/api"),
                }
                # Engine workers do not need the app token or database credentials.
                for key in ("APP_ACCESS_TOKEN", "DATABASE_URL"):
                    env.pop(key, None)
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "megabrain_api.worker",
                    cwd=ROOT,
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                    limit=4_000_000,
                )
                self.processes[job_id] = proc
                proc.stdin.write((json.dumps(request) + "\n").encode())
                await proc.stdin.drain()
                proc.stdin.close()
                succeeded = False
                partial = False
                async with asyncio.timeout(self.settings.job_timeout):
                    while line := await proc.stdout.readline():
                        event = json.loads(line)
                        self.record(job_id, event)
                        if event["type"] == "result":
                            succeeded = True
                            result = event["result"]
                            partial = result.get("success") is False or result.get("limited", False)
                    await proc.wait()
                self.finish(
                    job_id,
                    ("partial" if partial else "done")
                    if succeeded and proc.returncode == 0
                    else "error",
                )
        except asyncio.CancelledError:
            self.finish(job_id, "cancelled")
        except Exception:
            self.record(
                job_id,
                {"type": "error", "message": "Execução interrompida ou limite de tempo excedido."},
            )
            self.finish(job_id, "error")
        finally:
            if proc and proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
            # Killing the Docker client alone leaves a running container behind.
            # The name is derived only from our UUID, never from a browser argument.
            import shutil

            if (
                request["kind"] == "execution"
                and os.getenv("APP_SANDBOX_IMAGE")
                and shutil.which("docker")
            ):
                cleanup = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    "megabrain-" + job_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(cleanup.wait(), 10)
                except TimeoutError:
                    cleanup.kill()
                    await cleanup.wait()
            self.processes.pop(job_id, None)

    async def cancel(self, job_id):
        task = self.tasks.get(job_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.finish(job_id, "cancelled")

    async def close(self):
        for job_id in list(self.tasks):
            await self.cancel(job_id)
