# Resume Tailor Studio

Resume Tailor Studio is a web app that tailors a LaTeX resume to a job description using multi-step agent orchestration.

Live Site: https://resume-tailor-studio.onrender.com

## What It Does

- Stores your current resume text in app cache
- Lets you paste a job description and run multi-agent tailoring
- Applies your rules/workflow from the Rules & Agents tab
- Supports OpenAI and Gemini model providers
- Stores API keys in secure server-side session (HttpOnly cookie)
- Compiles LaTeX to PDF, shows in-app preview, and allows download

## How To Use The Website

1. Open the site.
2. In `Resume`, paste your current LaTeX resume and click `Save Resume Cache`.
3. In `Rules & Agents`, review/edit global rules and workflow steps if needed.
4. In `Tailor`:
   - Choose `Provider`
   - Save your API key with `Save Key`
   - Pick a model from the dropdown
   - Paste the job description
5. Click `Run Multi-Agent Tailor`.
6. Review `JD Analysis` and `Tailored LaTeX`.
7. Click `Compile to PDF`, then use `Preview` or `Download PDF`.

## How It Works

1. Rules text is parsed into workflow steps (agents).
2. Agents run in sequence.
3. Each step receives:
   - global rules
   - current resume
   - job description
   - prior step outputs
4. Final LaTeX is returned and cached.
5. PDF compilation runs server-side and the latest file is served to preview/download endpoints.

## Security Notes

- API keys are not stored in browser local storage.
- Session keys are stored server-side and tied to a secure session cookie.
- If a key is exposed, revoke and rotate it immediately.

## Common Issues

- `401 invalid_api_key`: wrong key for selected provider.
- `429 quota exceeded`: provider/model quota exhausted; switch model or wait/reset quota window.
- PDF compile error: malformed LaTeX (often markdown code fences); clean LaTeX and retry.

## Tech

- FastAPI backend
- Vanilla HTML/CSS/JS frontend
- SQLite state/session store
- OpenAI-compatible client for OpenAI and Gemini
- Server-side LaTeX compilation
