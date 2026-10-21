FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core fontconfig ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
# Text measurement only; no remote image or AI service is used for the title card.
RUN python -m pip install --no-cache-dir Pillow==12.3.0
WORKDIR /app
COPY worker.py renderer.py captions.py /app/
COPY vitanna-logo.png /app/vitanna-logo.png
RUN useradd --create-home --uid 10001 vitanna && mkdir /work && chown vitanna:vitanna /work
USER vitanna
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 RUN_MODE=disabled
CMD ["python", "/app/worker.py"]
