#!/usr/bin/env bash
# Part 5: setup_and_test.sh
# ==========================
# Automated End-to-End POC Orchestration Script
#
# This script:
#   1. Validates prerequisites (Docker, Docker Compose).
#   2. Spins up RabbitMQ, MinIO, the Decoder Pod, and downstream workers.
#   3. Seeds MinIO with a sample PCAP object.
#   4. Waits for all health checks to pass.
#   5. Injects an Initial Envelope into decoder.cplusplus.
#   6. Consumes from pipeline.completed to verify end-to-end delivery.
#   7. Streams live logs from the sidecars and workers.
#
# Usage:
#   chmod +x part5_poc/setup_and_test.sh
#   ./part5_poc/setup_and_test.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
RABBITMQ_MGMT_URL="http://localhost:15672"
MINIO_CONSOLE_URL="http://localhost:9001"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# Step 0: Prerequisites
# ---------------------------------------------------------------------------
log_info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    log_error "Docker is not installed or not in PATH."
    exit 1
fi

if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null; then
    log_error "Docker Compose is not installed or not in PATH."
    exit 1
fi

# Determine whether to use 'docker-compose' or 'docker compose'
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

log_ok "Docker and Docker Compose are available."

# ---------------------------------------------------------------------------
# Step 1: Tear down any existing POC environment
# ---------------------------------------------------------------------------
log_info "Tearing down any existing POC containers..."
${COMPOSE_CMD} -f "${COMPOSE_FILE}" down --volumes --remove-orphans 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 2: Build images
# ---------------------------------------------------------------------------
log_info "Building container images (this may take several minutes)..."
${COMPOSE_CMD} -f "${COMPOSE_FILE}" build --parallel
log_ok "All images built successfully."

# ---------------------------------------------------------------------------
# Step 3: Start infrastructure and workers
# ---------------------------------------------------------------------------
log_info "Starting RabbitMQ, MinIO, and all pipeline workers..."
${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d --wait

# Give sidecars a moment to establish connections and declare queues
sleep 8

# ---------------------------------------------------------------------------
# Step 4: Verify RabbitMQ Management UI
# ---------------------------------------------------------------------------
log_info "Waiting for RabbitMQ Management UI at ${RABBITMQ_MGMT_URL} ..."
for i in {1..30}; do
    if curl -s -o /dev/null -w "%{http_code}" -u platform:platform-secret "${RABBITMQ_MGMT_URL}/api/overview" | grep -q "200"; then
        log_ok "RabbitMQ Management UI is reachable."
        break
    fi
    if [ "$i" -eq 30 ]; then
        log_error "RabbitMQ did not become ready in time."
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# Step 5: Verify MinIO
# ---------------------------------------------------------------------------
log_info "Waiting for MinIO to be ready..."
for i in {1..30}; do
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:9000/minio/health/live" | grep -q "200"; then
        log_ok "MinIO is reachable."
        break
    fi
    if [ "$i" -eq 30 ]; then
        log_error "MinIO did not become ready in time."
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# Step 6: Seed MinIO with sample data
# ---------------------------------------------------------------------------
log_info "Seeding MinIO with sample PCAP object..."
docker run --rm --network pelt-poc_pelt-network \
    --entrypoint /bin/sh \
    minio/mc:RELEASE.2024-01-16T16-06-34Z \
    -c "
        mc alias set local http://minio:9000 minioadmin minioadmin123
        mc mb local/packet-storage 2>/dev/null || true
        echo 'mock-pcap-binary-data-placeholder' | mc pipe local/packet-storage/raw/2026/06/file_123.pcap
        echo 'MinIO seeding complete.'
    " || true
log_ok "MinIO seeded."

# ---------------------------------------------------------------------------
# Step 7: Declare queues explicitly (idempotent)
# ---------------------------------------------------------------------------
log_info "Declaring RabbitMQ queues..."

# Helper to declare a queue via the RabbitMQ Management HTTP API
declare_queue() {
    local queue_name="$1"
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" -u platform:platform-secret \
        -X PUT "${RABBITMQ_MGMT_URL}/api/queues/%2f/${queue_name}" \
        -H "Content-Type: application/json" \
        -d '{"auto_delete":false,"durable":true,"arguments":{}}')
    if echo "$status" | grep -q "20"; then
        return 0
    else
        return 1
    fi
}

QUEUES=("decoder.cplusplus" "enrichment.geoip" "enrichment.threat_intel" "formatter.json" "pipeline.completed" "pipeline.dlq")
for q in "${QUEUES[@]}"; do
    if declare_queue "$q"; then
        log_ok "Queue declared: $q"
    else
        log_warn "Queue may already exist or failed to declare: $q"
    fi
done

# ---------------------------------------------------------------------------
# Step 8: Inject the Initial Envelope
# ---------------------------------------------------------------------------
log_info "Injecting Initial Envelope into 'decoder.cplusplus'..."

# Run the test script inside a container to avoid host Python dependencies
docker run --rm \
    --network pelt-poc_pelt-network \
    -e RABBITMQ_HOST=rabbitmq \
    -e RABBITMQ_PORT=5672 \
    -e RABBITMQ_USER=platform \
    -e RABBITMQ_PASS=platform-secret \
    -e RABBITMQ_VHOST=/ \
    -v "${SCRIPT_DIR}/test_pipeline.py:/app/test_pipeline.py:ro" \
    python:3.11-slim-bookworm \
    bash -c "pip install --quiet pika==1.3.2 && python /app/test_pipeline.py --inject-only"

log_ok "Initial envelope injected."

# ---------------------------------------------------------------------------
# Step 9: Stream live logs for 15 seconds
# ---------------------------------------------------------------------------
log_info "Streaming live sidecar and worker logs for 15 seconds..."
echo -e "${YELLOW}----------------------------------------------------------------${NC}"
${COMPOSE_CMD} -f "${COMPOSE_FILE}" logs -f --tail=10 &
LOGS_PID=$!
sleep 15
kill $LOGS_PID 2>/dev/null || true
wait $LOGS_PID 2>/dev/null || true
echo -e "${YELLOW}----------------------------------------------------------------${NC}"

# ---------------------------------------------------------------------------
# Step 10: Verify end-to-end completion
# ---------------------------------------------------------------------------
log_info "Verifying end-to-end pipeline completion..."

docker run --rm \
    --network pelt-poc_pelt-network \
    -e RABBITMQ_HOST=rabbitmq \
    -e RABBITMQ_PORT=5672 \
    -e RABBITMQ_USER=platform \
    -e RABBITMQ_PASS=platform-secret \
    -e RABBITMQ_VHOST=/ \
    -v "${SCRIPT_DIR}/test_pipeline.py:/app/test_pipeline.py:ro" \
    python:3.11-slim-bookworm \
    bash -c "pip install --quiet pika==1.3.2 && python /app/test_pipeline.py --verify --timeout 30"

log_ok "POC verification complete."

# ---------------------------------------------------------------------------
# Step 11: Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  POC SETUP AND TEST COMPLETED SUCCESSFULLY                ${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
log_info "RabbitMQ Management UI: ${RABBITMQ_MGMT_URL}"
log_info "  Username: platform"
log_info "  Password: platform-secret"
echo ""
log_info "MinIO Console:          ${MINIO_CONSOLE_URL}"
log_info "  Username: minioadmin"
log_info "  Password: minioadmin123"
echo ""
log_info "To inspect live logs at any time:"
echo "  ${COMPOSE_CMD} -f ${COMPOSE_FILE} logs -f"
echo ""
log_info "To tear down the POC:"
echo "  ${COMPOSE_CMD} -f ${COMPOSE_FILE} down --volumes"
echo ""
