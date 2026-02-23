from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class LatexCompileError(RuntimeError):
    pass


def _find_engine() -> str | None:
    for engine in ("tectonic", "pdflatex", "xelatex"):
        if shutil.which(engine):
            return engine
    return None


def compile_resume(latex_source: str, output_pdf: Path) -> None:
    engine = _find_engine()
    if not engine:
        raise LatexCompileError("No LaTeX compiler found (tectonic/pdflatex/xelatex).")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        tex_path = temp_dir / "resume.tex"
        tex_path.write_text(latex_source, encoding="utf-8")

        if engine == "tectonic":
            cmd = [engine, "--keep-logs", "--outdir", str(temp_dir), str(tex_path)]
        else:
            cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", str(tex_path)]

        proc = subprocess.run(
            cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            check=False,
        )

        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-30:])
            raise LatexCompileError(f"LaTeX compile failed with {engine}.\n{tail}")

        pdf_path = temp_dir / "resume.pdf"
        if not pdf_path.exists():
            raise LatexCompileError("Compiler finished but resume.pdf was not generated.")

        output_pdf.write_bytes(pdf_path.read_bytes())
