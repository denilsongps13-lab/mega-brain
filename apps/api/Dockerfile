FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/apps/api
WORKDIR /app
COPY requirements.txt requirements.txt
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r apps/api/requirements.txt && useradd --create-home --uid 10001 app
COPY engine engine
COPY agents agents
COPY squads squads
COPY workspace workspace
COPY knowledge knowledge
COPY apps/api apps/api
RUN mkdir -p /app/.data/app/workspace && chown -R app:app /app/.data
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn megabrain_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --ws-max-size 65536 --limit-concurrency 64 --no-access-log"]
