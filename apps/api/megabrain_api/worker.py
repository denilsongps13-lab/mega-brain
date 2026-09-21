"""Cancelable process boundary. Only JSON events go to the API; raw errors stay hidden."""

import contextlib
import json
import logging
import sys

from . import adapters
from .config import Settings
from .execution import execute


def main():
    output = sys.stdout
    logging.disable(logging.CRITICAL)

    def emit(event):
        output.write(json.dumps(event, ensure_ascii=False) + "\n")
        output.flush()

    try:
        request = json.loads(sys.stdin.readline())
        settings = Settings()
        # Engine libraries occasionally print diagnostics; keep them out of event protocol.
        with contextlib.redirect_stdout(sys.stderr):
            if request["kind"] == "chat":
                result = adapters.chat(settings, request["messages"], request["objective"], emit)
            elif request["kind"] == "document":
                result = adapters.ingest(
                    settings, request["document_id"], request["filename"], emit
                )
            elif request["kind"] == "execution":
                result = execute(settings, request["objective"], emit)
            else:
                raise ValueError("Unknown job kind")
        emit({"type": "result", "result": result})
    except Exception:
        emit(
            {
                "type": "error",
                "message": "Falha no engine. Verifique configuração dos provedores, formato do documento e sandbox.",
            }
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
