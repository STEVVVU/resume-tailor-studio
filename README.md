# Resume Tailor Studio

Local/hosted web app for resume tailoring with cached LaTeX resume state, JD input, dynamic multi-agent orchestration, and PDF preview/download.

## Features

- Persistent cached resume (SQLite-backed)
- JD paste + dynamic workflow-agent orchestration from instructions
- Rules + workflow editor in UI
- Compile to PDF (`tectonic`, `pdflatex`, or `xelatex`)
- In-app PDF preview + direct download

## Local Setup

```powershell
cd C:\Users\Steven\Downloads\Projects\resume-tailor-studio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Local Run

```powershell
$env:OPENAI_API_KEY="your_key"
$env:OPENAI_MODEL="gpt-5"  # optional
uvicorn app.main:app --reload --port 8080
```

Open `http://127.0.0.1:8080`.

## Production Deploy (Always-On)

This repo includes:
- `Dockerfile`
- `.dockerignore`
- `render.yaml`
- health endpoint: `GET /healthz`

### Option A: Railway (recommended fastest)

1. Push this folder to GitHub.
2. Create Railway project from repo.
3. Railway detects Dockerfile and deploys.
4. Set env vars:
   - `OPENAI_API_KEY` (required)
   - `OPENAI_MODEL=gpt-5` (optional)
   - `DATA_DIR=/var/data`
5. Add a Volume mounted to `/var/data`.
6. Open generated public URL.

Notes:
- Railway free is not permanent; use Hobby/paid for durable hosting.
- Keep app and volume in same region.

### Option B: Render (always-on with paid instance)

1. Push repo to GitHub.
2. In Render, create a new Web Service from repo.
3. Render will read `render.yaml` and configure service + disk.
4. Set `OPENAI_API_KEY` in Render dashboard.
5. Deploy.

Notes:
- Render Free spins down after idle and is not production-grade.
- Use paid instance type for always-on behavior.

## Data + Persistence

- App data (state DB, custom instructions, compiled PDF) lives under `DATA_DIR`.
- For hosted deployments, use persistent disk/volume and set `DATA_DIR=/var/data`.

## Security

- Never commit API keys.
- Rotate keys if exposed.

## Project URLs for resume

After deploy, add:
- Live URL (app)
- GitHub repo URL
- Optional short Loom demo showing JD -> tailored LaTeX -> compile -> PDF preview
