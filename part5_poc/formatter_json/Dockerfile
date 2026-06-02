# Dockerfile for formatter.json business logic container
FROM python:3.11-slim-bookworm

RUN groupadd -r formatter && useradd -r -g formatter formatter

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.109.0 uvicorn==0.27.0

COPY main.py ./

USER formatter

EXPOSE 8080

ENTRYPOINT ["python", "-u", "main.py"]
