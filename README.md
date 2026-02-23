# Resume Tailor Studio

Resume Tailor Studio is a web app that tailors a LaTeX resume to a pasted job description using dynamic multi-agent orchestration.

## What It Does

- Caches your resume LaTeX between sessions (SQLite state)
- Lets you paste a JD and run dynamic agent workflow steps
- Lets you edit global rules and workflow steps in-app
- Supports request-time OpenAI API key input (not persisted)
- Compiles LaTeX to PDF and shows in-app preview
- Supports PDF download

## Tech Stack

- FastAPI (`app/main.py`)
- OpenAI Responses API (`app/llm_client.py`)
- Dynamic prompt/workflow parsing (`app/prompt_splitter.py`)
- Agent orchestration (`app/orchestrator.py`)
- SQLite state store (`app/storage.py`)
- Vanilla HTML/CSS/JS frontend (`app/templates`, `app/static`)

## Project Structure

```text
resume-tailor-studio/
  app/
    main.py
    llm_client.py
    orchestrator.py
    prompt_splitter.py
    latex_service.py
    storage.py
    templates/index.html
    static/app.js
    static/styles.css
  data/
    instructions.default.md
  Dockerfile
  render.yaml
  requirements.txt
```

## Local Development

### 1. Create venv and install

```powershell
cd C:\Users\Steven\Downloads\Projects\resume-tailor-studio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Set environment variables

```powershell
$env:OPENAI_API_KEY="your_key_here"
$env:OPENAI_MODEL="gpt-5"                # optional
$env:DATA_DIR="C:\Users\Steven\Downloads\Projects\resume-tailor-studio\data"  # optional
```

Optional local defaults:

```powershell
$env:DEFAULT_RESUME_PATH="C:\Users\Steven\Downloads\resume.tex"
$env:DEFAULT_INSTRUCTIONS_PATH="C:\Users\Steven\Downloads\instructions.md"
```

### 3. Run app

```powershell
uvicorn app.main:app --reload --port 8080
```

Open: `http://127.0.0.1:8080`

## Deployment

### Render (Free tier)

1. Push this repo to GitHub.
2. In Render: `New` -> `Web Service` -> `Public Git Repository`.
3. Use repo URL (example): `https://github.com/STEVVVU/resume-tailor-studio`.
4. Select Docker runtime.
5. Add env vars:
   - `OPENAI_API_KEY` (required)
   - `OPENAI_MODEL=gpt-5` (optional)
   - `DATA_DIR=/var/data`
6. Deploy.

Notes:
- Free Render sleeps on idle and is not always-on.
- Free tier does not provide durable persistent disk behavior for production use.

## Environment Variables

- `OPENAI_API_KEY` (required for tailoring)
- `OPENAI_MODEL` (default: `gpt-5`)
- `DATA_DIR` (default: `./data`)
- `DEFAULT_RESUME_PATH` (optional)
- `DEFAULT_INSTRUCTIONS_PATH` (optional)

## API Endpoints

- `GET /` UI
- `GET /healthz` health check
- `GET /api/state` app state
- `GET /api/instructions` load active instructions
- `PUT /api/instructions` save custom instructions
- `POST /api/instructions/reset` reset to default instructions
- `PUT /api/resume` save cached resume
- `POST /api/tailor/start` start async tailor job
- `GET /api/tailor/status/{job_id}` poll job status
- `POST /api/compile` compile current LaTeX to PDF
- `GET /api/pdf/latest` inline preview PDF
- `GET /api/pdf/download` download PDF

## Troubleshooting

- `400 Unsupported parameter: temperature`
  - Fixed in current build by using compatible Responses API payload.

- `POST /api/compile` returns `400`
  - Local machine missing/blocked LaTeX compiler setup.
  - Hosted Docker build includes `tectonic`.

- Browser logs `304 Not Modified`
  - Normal cache behavior.

- Browser logs `GET /favicon.ico 404`
  - Harmless unless you add a favicon file.

## Security

- Do not commit API keys.
- If a key is exposed, revoke and rotate immediately.

## License

Use for personal/portfolio/demo purposes unless you add your own project license.
