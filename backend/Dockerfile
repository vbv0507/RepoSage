FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser
ENV HOME=/home/appuser \
    PYTHONUNBUFFERED=1 \
    CHROMA_PATH=/tmp/chroma \
    SEMANTIC_CACHE=off \
    AUTO_INDEX_SAMPLE_REPO=false

EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860} --timeout-keep-alive 300"]
