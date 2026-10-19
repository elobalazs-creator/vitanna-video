FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core fontconfig ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker.py renderer.py captions.py /app/
RUN useradd --create-home --uid 10001 vitanna && mkdir /work && chown vitanna:vitanna /work
USER vitanna
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 RUN_MODE=disabled
CMD ["python", "/app/worker.py"]
