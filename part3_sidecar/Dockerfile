# Part 3: Dockerfile for the Platform AMQP Sidecar
# =================================================
# This Dockerfile builds the sidecar image that runs sidecar.py.
# It is managed by the platform and injected into every Decoder Pod.

FROM python:3.11-slim-bookworm

# Security: create non-root user
RUN groupadd -r sidecar && useradd -r -g sidecar sidecar

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy sidecar source
COPY sidecar.py ./

# Switch to non-root user
USER sidecar

# Default to running the sidecar
ENTRYPOINT ["python", "-u", "sidecar.py"]
