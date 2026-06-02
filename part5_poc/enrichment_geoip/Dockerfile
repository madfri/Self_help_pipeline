# Dockerfile for enrichment.geoip business logic container
FROM python:3.11-slim-bookworm

RUN groupadd -r enrichment && useradd -r -g enrichment enrichment

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.109.0 uvicorn==0.27.0

COPY main.py ./

USER enrichment

EXPOSE 8080

ENTRYPOINT ["python", "-u", "main.py"]
