"""HTTP API. POST /api/tailor streams the agent's steps as server-sent events,
ending with the full result; the tailored résumé is then downloadable as DOCX or PDF."""
from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import TailorAgent
from .export import to_docx, to_pdf
from .jobpost import fetch_job_text
from .demo import DemoLLM
from .llm import LLM, GeminiLLM
from .resume import Resume

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
MAX_RUNS = 50


class TailorRequest(BaseModel):
    job_text: str | None = None
    job_url: str | None = None


def create_app(llm_factory=None, resume: Resume | None = None) -> FastAPI:
    app = FastAPI(title="Job Copilot")
    resume = resume or Resume.load(os.getenv("RESUME_PATH") or Path(__file__).parent / "resume_ramya.json")
    runs: OrderedDict[str, dict] = OrderedDict()
    if llm_factory:
        make_llm = llm_factory
    elif os.getenv("GEMINI_API_KEY"):
        make_llm = lambda: GeminiLLM()
    else:  # no key: run the offline demo model so the app still works end to end
        make_llm = lambda: DemoLLM(resume)

    @app.get("/api/health")
    def health():
        return {"ok": True, "model": getattr(make_llm(), "name", "custom")}

    @app.get("/api/resume")
    def get_resume():
        return resume.raw

    @app.post("/api/tailor")
    def tailor(req: TailorRequest):
        if not (req.job_text and req.job_text.strip()) and not req.job_url:
            raise HTTPException(400, "Paste a job description or a link to one")
        try:
            llm: LLM = make_llm()
        except RuntimeError as e:
            raise HTTPException(503, str(e))

        events: queue.Queue = queue.Queue()

        def work():
            try:
                text = req.job_text
                if not (text and text.strip()):
                    events.put({"step": "fetch", "status": "running", "message": "Fetching the job posting"})
                    text = fetch_job_text(req.job_url)
                    events.put({"step": "fetch", "status": "done", "message": f"Read {len(text):,} characters from the posting"})
                result = TailorAgent(llm, resume, emit=events.put).run(text)
                run_id = uuid.uuid4().hex[:12]
                runs[run_id] = result.to_dict()
                while len(runs) > MAX_RUNS:
                    runs.popitem(last=False)
                events.put({"step": "result", "status": "done", "run_id": run_id, "result": runs[run_id]})
            except Exception as e:  # surfaced to the UI as a failed step
                events.put({"step": "error", "status": "failed", "message": str(e) or e.__class__.__name__})
            finally:
                events.put(None)

        threading.Thread(target=work, daemon=True).start()

        def stream():
            while (event := events.get()) is not None:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/runs/{run_id}/resume.{fmt}")
    def download(run_id: str, fmt: str):
        run = runs.get(run_id)
        if not run:
            raise HTTPException(404, "That result has expired. Run it again.")
        slug = "".join(c if c.isalnum() else "-" for c in (run.get("company") or run["title"]).lower()).strip("-")[:40]
        name = f"{resume.name.replace(' ', '_')}_{slug}.{fmt}"
        if fmt == "docx":
            body, mime = to_docx(run["draft"], resume), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "pdf":
            body, mime = to_pdf(run["draft"], resume), "application/pdf"
        else:
            raise HTTPException(404, "Use .docx or .pdf")
        return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    if FRONTEND.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()
