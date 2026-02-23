from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class LatexCompileError(RuntimeError):
    pass


def _sanitize_latex_source(latex_source: str) -> str:
    src = latex_source.replace("\ufeff", "").strip()

    # Remove common Markdown code-fence wrappers:
    # ```latex ... ``` or ``` ... ```
    fence_match = re.match(r"^\s*```(?:latex|tex)?\s*\n([\s\S]*?)\n```\s*$", src, flags=re.IGNORECASE)
    if fence_match:
        src = fence_match.group(1).strip()

    # Remove odd single-line fence headers some models produce (e.g. "` ``latex").
    src = re.sub(r"^\s*`+\s*latex\s*$\n?", "", src, flags=re.IGNORECASE)
    src = re.sub(r"^\s*`+\s*tex\s*$\n?", "", src, flags=re.IGNORECASE)

    return src


def _find_engine() -> str | None:
    for engine in ("tectonic", "pdflatex", "xelatex"):
        if shutil.which(engine):
            return engine
    return None


def compile_resume(latex_source: str, output_pdf: Path) -> None:
    latex_source = _sanitize_latex_source(latex_source)
    engine = _find_engine()
    if not engine:
        raise LatexCompileError("No LaTeX compiler found (tectonic/pdflatex/xelatex).")

    if r"\begin{document}" not in latex_source:
        raise LatexCompileError("LaTeX source is invalid (missing \\begin{document}). Remove markdown wrappers and retry.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    timeout_seconds = int(os.getenv("LATEX_COMPILE_TIMEOUT_SECONDS", "90"))

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        tex_path = temp_dir / "resume.tex"
        tex_path.write_text(latex_source, encoding="utf-8")

        if engine == "tectonic":
            cmd = [engine, "--keep-logs", "--outdir", str(temp_dir), str(tex_path)]
        else:
            cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", str(tex_path)]

        try:
            proc = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            tail = ""
            if exc.stdout or exc.stderr:
                tail = "\n".join(((exc.stdout or "") + "\n" + (exc.stderr or "")).splitlines()[-30:])
            message = f"LaTeX compile timed out after {timeout_seconds}s with {engine}."
            if tail:
                message = f"{message}\n{tail}"
            raise LatexCompileError(message) from exc

        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-30:])
            raise LatexCompileError(f"LaTeX compile failed with {engine}.\n{tail}")

        pdf_path = temp_dir / "resume.pdf"
        if not pdf_path.exists():
            raise LatexCompileError("Compiler finished but resume.pdf was not generated.")

        output_pdf.write_bytes(pdf_path.read_bytes())
