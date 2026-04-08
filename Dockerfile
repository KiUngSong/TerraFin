FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TERRAFIN_DISABLE_DOTENV=1 \
    TERRAFIN_HOST=0.0.0.0 \
    TERRAFIN_PORT=7860 \
    TERRAFIN_CACHE_TIMEZONE=America/New_York

WORKDIR /app

COPY pyproject.toml README.md MANIFEST.in ./
COPY src ./src
COPY docs ./docs
COPY skills ./skills

RUN pip install --upgrade pip \
    && pip install .

EXPOSE 7860

CMD ["python", "src/TerraFin/interface/server.py", "run"]
