from __future__ import annotations

import os
import secrets
import threading
import uuid
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException
from fastapi import Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel

from .latex_service import LatexCompileError, compile_resume
from .llm_client import LLMClient
from .orchestrator import ResumeOrchestrator
from .prompt_splitter import build_prompt_bundle, extract_workflow_steps_from_text
from .storage import SessionKeyStore, StateStore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
STATE_DB = DATA_DIR / "state.db"
OUTPUT_PDF = DATA_DIR / "resume-latest.pdf"
PDF_FILENAME = os.getenv("RESUME_PDF_FILENAME", "FirstLastResume.pdf")
CUSTOM_INSTRUCTIONS_PATH = DATA_DIR / "instructions.custom.md"
BUNDLED_INSTRUCTIONS_PATH = BASE_DIR / "data" / "instructions.default.md"

DEFAULT_RESUME_PATH = Path(os.getenv("DEFAULT_RESUME_PATH", r"C:\Users\Steven\Downloads\resume.tex"))
DEFAULT_INSTRUCTIONS_PATH = Path(os.getenv("DEFAULT_INSTRUCTIONS_PATH", r"C:\Users\Steven\Downloads\instructions.md"))
SESSION_COOKIE_NAME = "rts_session"
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production")

store = StateStore(STATE_DB)
session_keys = SessionKeyStore(STATE_DB, SESSION_SECRET)
llm = LLMClient()

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
app = FastAPI(title="Resume Tailor Studio")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


@app.middleware("http")
async def add_no_store_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


class ResumeUpdate(BaseModel):
    resume_latex: str


class TailorRequest(BaseModel):
    job_description: str
    llm_provider: str | None = None
    llm_model: str | None = None


class SessionKeyRequest(BaseModel):
    api_key: str
    llm_provider: str = "openai"


class CompileRequest(BaseModel):
    latex: str


class InstructionsUpdate(BaseModel):
    content: str


class TailorJobStatus(BaseModel):
    id: str
    status: str
    stage: str
    progress: int
    error: str | None = None
    latex: str | None = None
    jd_analysis: str | None = None


JOBS: dict[str, TailorJobStatus] = {}
JOBS_LOCK = threading.Lock()


def _set_job(job: TailorJobStatus) -> None:
    with JOBS_LOCK:
        JOBS[job.id] = job


def _get_job(job_id: str) -> TailorJobStatus | None:
    with JOBS_LOCK:
        return JOBS.get(job_id)


def _load_initial_resume() -> str:
    cached = store.get("current_resume")
    if cached:
        return cached
    if DEFAULT_RESUME_PATH.exists():
        text = DEFAULT_RESUME_PATH.read_text(encoding="utf-8", errors="ignore")
        store.set("current_resume", text)
        return text
    return ""


def _resolve_instructions_path() -> tuple[Path, str]:
    mode = store.get("instructions_mode") or "default"

    if mode == "custom" and CUSTOM_INSTRUCTIONS_PATH.exists():
        return CUSTOM_INSTRUCTIONS_PATH, "custom"

    if DEFAULT_INSTRUCTIONS_PATH.exists():
        return DEFAULT_INSTRUCTIONS_PATH, "default"

    if BUNDLED_INSTRUCTIONS_PATH.exists():
        return BUNDLED_INSTRUCTIONS_PATH, "bundled"

    raise RuntimeError("No instructions file found. Set DEFAULT_INSTRUCTIONS_PATH.")


def _load_instructions_path() -> Path:
    path, _ = _resolve_instructions_path()
    return path


def _get_or_create_session_id(request: Request) -> str:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid:
        return sid
    return secrets.token_urlsafe(32)


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _resolve_request_key_and_provider(request: Request, payload: TailorRequest) -> tuple[str | None, str | None]:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    provider = (payload.llm_provider or "").strip().lower() or None
    if not sid:
        return None, provider
    record = session_keys.get(sid)
    if not record:
        return None, provider
    record_provider = str(record["provider"]).strip().lower()
    if not provider:
        provider = record_provider
    elif provider != record_provider:
        # Do not use a session key saved for a different provider.
        # This prevents sending Gemini keys to OpenAI (or vice versa).
        return None, provider
    return str(record["api_key"]), provider


def _safe_pdf_filename(name: str | None = None) -> str:
    if not name:
        base = PDF_FILENAME
    else:
        base = re.sub(r"[^A-Za-z0-9_ -]+", "", name).strip().replace(" ", "_")
        if not base:
            base = PDF_FILENAME
        if not base.lower().endswith("_resume"):
            base = f"{base}_Resume"
    return base if base.lower().endswith(".pdf") else f"{base}.pdf"


def _extract_filename_metadata(latex: str) -> str | None:
    # Optional explicit metadata comment for deterministic output:
    # %RESUME_FILENAME=First_Last_Resume.pdf
    match = re.search(r"^\s*%\s*RESUME_FILENAME\s*=\s*([^\r\n]+)\s*$", latex, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    candidate = match.group(1).strip()
    return candidate or None


def _extract_resume_name(latex: str) -> str | None:
    # 1) Template-aware macro parsing.
    first = re.search(r"\\firstname\{([^{}]+)\}", latex)
    last = re.search(r"\\familyname\{([^{}]+)\}", latex)
    if first and last:
        return f"{first.group(1).strip()} {last.group(1).strip()}".strip()

    macro_patterns = [
        # \name{First}{Last}
        r"\\name\{([^{}]+)\}\{([^{}]+)\}",
        # \name{Full Name}
        r"\\name\{([^{}]+)\}",
        # \cvname{Full Name}
        r"\\cvname\{([^{}]+)\}",
        # \author{Full Name}
        r"\\author\{([^{}]+)\}",
    ]
    for pattern in macro_patterns:
        m = re.search(pattern, latex)
        if not m:
            continue
        if len(m.groups()) == 2:
            return f"{m.group(1).strip()} {m.group(2).strip()}".strip()
        return m.group(1).strip()

    # 2) Header fallback for custom templates:
    # \textbf{\Huge \scshape Steven Vu}
    header_patterns = [
        r"\\textbf\{\\Huge\s+\\scshape\s+([^}]+)\}",
        r"\\textbf\{\\Huge\s+([^}]+)\}",
    ]
    for pattern in header_patterns:
        match = re.search(pattern, latex)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate

    # 3) Last fallback (broad; may be noisy in some templates).
    broad = re.search(r"\\textbf\{([^}]+)\}", latex)
    if broad:
        candidate = broad.group(1).strip()
        if candidate:
            return candidate
    return None


def _derive_pdf_filename(latex: str) -> str:
    explicit = _extract_filename_metadata(latex)
    if explicit:
        return _safe_pdf_filename(explicit)
    parsed_name = _extract_resume_name(latex)
    return _safe_pdf_filename(parsed_name)


def _get_latest_pdf_filename() -> str:
    stored = store.get("latest_pdf_filename")
    return _safe_pdf_filename(stored if stored else None)


def _discover_openai_models(api_key: str) -> list[str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    resp = client.models.list()
    names: list[str] = []
    for item in getattr(resp, "data", []):
        model_id = getattr(item, "id", None)
        if isinstance(model_id, str) and model_id.startswith("gpt-"):
            names.append(model_id)
    # Keep stable ordering for UI.
    return sorted(set(names))


def _discover_gemini_models(api_key: str) -> list[str]:
    url = "https://generativelanguage.googleapis.com/v1beta/models?" + urlencode({"key": api_key})
    req = UrlRequest(url, method="GET")
    with urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raw_models = payload.get("models", [])
    names: list[str] = []
    for model in raw_models:
        name = model.get("name")
        if not isinstance(name, str):
            continue
        short = name.split("/", 1)[-1]
        if short.startswith("gemini-"):
            names.append(short)
    return sorted(set(names))


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/state")
def get_state() -> dict:
    instructions_path, source = _resolve_instructions_path()
    return {
        "resume_latex": _load_initial_resume(),
        "instructions_path": str(instructions_path),
        "instructions_source": source,
        "llm_enabled": llm.enabled,
        "llm_provider": llm.default_provider,
        "llm_model": llm.default_model,
        "llm_gemini_model": llm.default_gemini_model,
        "pdf_available": OUTPUT_PDF.exists(),
    }


@app.get("/api/session/status")
def session_status(request: Request) -> dict:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return {"has_key": False}
    record = session_keys.get(sid)
    if not record:
        return {"has_key": False}
    return {"has_key": True, "provider": record["provider"]}


@app.get("/api/models")
def get_models(request: Request, provider: str) -> dict:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        raise HTTPException(status_code=400, detail="No session key set.")

    record = session_keys.get(sid)
    if not record:
        raise HTTPException(status_code=400, detail="No session key set.")

    provider_norm = (provider or "").strip().lower()
    key_provider = str(record["provider"]).strip().lower()
    if provider_norm not in {"openai", "gemini"}:
        raise HTTPException(status_code=400, detail="Unsupported provider.")
    if provider_norm != key_provider:
        raise HTTPException(status_code=400, detail="Session key provider mismatch. Save a key for this provider first.")

    api_key = str(record["api_key"])
    try:
        if provider_norm == "openai":
            models = _discover_openai_models(api_key)
        else:
            models = _discover_gemini_models(api_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load models for {provider_norm}: {exc}") from exc

    if not models:
        raise HTTPException(status_code=400, detail=f"No models returned for {provider_norm}.")
    return {"provider": provider_norm, "models": models}


@app.post("/api/session/key")
def set_session_key(payload: SessionKeyRequest, request: Request, response: Response) -> dict:
    sid = _get_or_create_session_id(request)
    session_keys.set(
        session_id=sid,
        provider=(payload.llm_provider or "openai").lower(),
        api_key=payload.api_key.strip(),
        ttl_seconds=SESSION_TTL_HOURS * 3600,
    )
    _set_session_cookie(response, sid)
    return {"ok": True}


@app.post("/api/session/key/clear")
def clear_session_key(request: Request, response: Response) -> dict:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid:
        session_keys.clear(sid)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/instructions")
def get_instructions() -> dict:
    instructions_path, source = _resolve_instructions_path()
    content = instructions_path.read_text(encoding="utf-8", errors="ignore")
    return {
        "source": source,
        "path": str(instructions_path),
        "content": content,
        "workflow_steps": extract_workflow_steps_from_text(content),
    }


@app.put("/api/instructions")
def update_instructions(payload: InstructionsUpdate) -> dict:
    CUSTOM_INSTRUCTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_INSTRUCTIONS_PATH.write_text(payload.content, encoding="utf-8")
    store.set("instructions_mode", "custom")

    return {
        "ok": True,
        "source": "custom",
        "path": str(CUSTOM_INSTRUCTIONS_PATH),
        "workflow_steps": extract_workflow_steps_from_text(payload.content),
    }


@app.post("/api/instructions/reset")
def reset_instructions() -> dict:
    store.set("instructions_mode", "default")
    if not DEFAULT_INSTRUCTIONS_PATH.exists():
        raise HTTPException(status_code=400, detail="Default instructions path does not exist.")
    content = DEFAULT_INSTRUCTIONS_PATH.read_text(encoding="utf-8", errors="ignore")
    return {
        "ok": True,
        "source": "default",
        "path": str(DEFAULT_INSTRUCTIONS_PATH),
        "workflow_steps": extract_workflow_steps_from_text(content),
        "content": content,
    }


@app.put("/api/resume")
def update_resume(payload: ResumeUpdate) -> dict:
    store.set("current_resume", payload.resume_latex)
    return {"ok": True}


@app.post("/api/tailor")
def tailor_resume(payload: TailorRequest, request: Request) -> dict:
    # Kept for compatibility with existing clients.
    return _run_tailor_sync(payload, request)


def _run_tailor_sync(payload: TailorRequest, request: Request) -> dict:
    resume = _load_initial_resume()
    if not resume.strip():
        raise HTTPException(status_code=400, detail="No resume in cache.")

    instructions_path = _load_instructions_path()
    prompts = build_prompt_bundle(instructions_path)
    orchestrator = ResumeOrchestrator(llm=llm, prompts=prompts)
    api_key, provider = _resolve_request_key_and_provider(request, payload)

    try:
        result = orchestrator.tailor(
            current_resume=resume,
            job_description=payload.job_description,
            api_key=api_key,
            llm_provider=provider,
            llm_model=payload.llm_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tailor request failed: {exc}") from exc
    store.set("current_resume", result.latex)

    return {
        "latex": result.latex,
        "jd_analysis": result.jd_analysis,
        "llm_enabled": llm.enabled,
    }


@app.post("/api/tailor/start")
def start_tailor_job(payload: TailorRequest, request: Request) -> dict:
    resume = _load_initial_resume()
    if not resume.strip():
        raise HTTPException(status_code=400, detail="No resume in cache.")

    job_id = str(uuid.uuid4())
    _set_job(
        TailorJobStatus(
            id=job_id,
            status="running",
            stage="Queued",
            progress=0,
        )
    )

    instructions_path = _load_instructions_path()
    prompts = build_prompt_bundle(instructions_path)
    orchestrator = ResumeOrchestrator(llm=llm, prompts=prompts)
    api_key, provider = _resolve_request_key_and_provider(request, payload)

    def worker() -> None:
        try:

            def on_progress(stage: str, progress: int, jd_analysis: str | None = None) -> None:
                existing = _get_job(job_id)
                if not existing:
                    return
                existing.stage = stage
                existing.progress = progress
                if jd_analysis is not None:
                    existing.jd_analysis = jd_analysis
                _set_job(existing)

            result = orchestrator.tailor(
                current_resume=resume,
                job_description=payload.job_description,
                api_key=api_key,
                llm_provider=provider,
                llm_model=payload.llm_model,
                progress_cb=on_progress,
            )
            store.set("current_resume", result.latex)

            existing = _get_job(job_id)
            if existing:
                existing.status = "completed"
                existing.stage = "Completed"
                existing.progress = 100
                existing.latex = result.latex
                existing.jd_analysis = result.jd_analysis
                _set_job(existing)
        except Exception as exc:
            existing = _get_job(job_id)
            if existing:
                existing.status = "failed"
                existing.stage = "Failed"
                existing.error = str(exc)
                _set_job(existing)

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/tailor/status/{job_id}")
def get_tailor_job_status(job_id: str) -> dict:
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.model_dump()


@app.post("/api/compile")
def compile_latex(payload: CompileRequest) -> dict:
    try:
        compile_resume(payload.latex, OUTPUT_PDF)
    except LatexCompileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.set("latest_pdf_filename", _derive_pdf_filename(payload.latex))

    return {"ok": True, "pdf_url": "/api/pdf/latest"}


@app.get("/api/pdf/latest")
def latest_pdf() -> FileResponse:
    if not OUTPUT_PDF.exists():
        raise HTTPException(status_code=404, detail="No compiled PDF available yet.")
    safe_name = _get_latest_pdf_filename()
    return FileResponse(
        str(OUTPUT_PDF),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@app.get("/api/pdf/download")
def download_pdf() -> FileResponse:
    if not OUTPUT_PDF.exists():
        raise HTTPException(status_code=404, detail="No compiled PDF available yet.")
    safe_name = _get_latest_pdf_filename()
    return FileResponse(str(OUTPUT_PDF), media_type="application/pdf", filename=safe_name)
