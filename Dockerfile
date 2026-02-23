FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system deps and LaTeX compiler for PDF generation.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        lmodern \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY data ./data
COPY README.md ./README.md

ENV DATA_DIR=/var/data \
    PORT=10000

EXPOSE 10000

CMD ["sh", "-c", "mkdir -p ${DATA_DIR} && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
