# Isolated command runner for a host API deployment with Docker available.
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/runner && /opt/runner/bin/pip install --no-cache-dir pytest
ENV PATH=/opt/runner/bin:$PATH HOME=/tmp
WORKDIR /work
USER 10001
