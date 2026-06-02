# Self-Help ELT Pipeline Platform

A production-grade, multi-tenant ELT (Extract, Load, Transform) pipeline platform for network PCAP processing, built around the **Claim Check Pattern**, **Dynamic Choreography (Itinerary Envelope)**, and **Platform Sidecar Pattern**.

## Architecture Overview

For comprehensive, interactive architecture diagrams (Mermaid) covering the full system, sidecar pattern internals, message choreography sequences, claim check pattern, error handling flows, and network topology, see:

📐 **`ARCHITECTURE.md`** — Detailed visual architecture with 8 diagram types

### Simplified Conceptual Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WINDMILL SELF-HELP PORTAL                           │
│  External developers submit custom decoder registrations via a low-code UI. │
│  Windmill triggers deploy_decoder.py to create K8s Deployments dynamically. │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KUBERNETES CLUSTER                                  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Pod: decoder-example                                                 │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐   │  │
│  │  │ Business Logic       │  │ Platform Sidecar                     │   │  │
│  │  │ C++ Decoder Server   │◄─┤ AMQP Consumer, HTTP Client, Router   │   │  │
│  │  │ 127.0.0.1:8080       │  │ MY_QUEUE=decoder.cplusplus           │   │  │
│  │  └──────────────────────┘  └──────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼ RabbitMQ                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Pod: enrichment-geoip                                                │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐   │  │
│  │  │ Business Logic       │  │ Platform Sidecar                     │   │  │
│  │  │ Python GeoIP Worker  │◄─┤ Pops itinerary, routes forward       │   │  │
│  │  │ 127.0.0.1:8080       │  │ MY_QUEUE=enrichment.geoip            │   │  │
│  │  └──────────────────────┘  └──────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼ RabbitMQ                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Pod: enrichment-threat-intel                                         │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐   │  │
│  │  │ Business Logic       │  │ Platform Sidecar                     │   │  │
│  │  │ Python Threat Worker │◄─┤ Pops itinerary, routes forward       │   │  │
│  │  │ 127.0.0.1:8080       │  │ MY_QUEUE=enrichment.threat_intel     │   │  │
│  │  └──────────────────────┘  └──────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼ RabbitMQ                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Pod: formatter-json                                                  │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐   │  │
│  │  │ Business Logic       │  │ Platform Sidecar                     │   │  │
│  │  │ Python JSON Worker   │◄─┤ Pops itinerary, routes to completed  │   │  │
│  │  │ 127.0.0.1:8080       │  │ MY_QUEUE=formatter.json              │   │  │
│  │  └──────────────────────┘  └──────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼ RabbitMQ                             │
│                           ┌──────────────────────┐                          │
│                           │  pipeline.completed  │                          │
│                           │  pipeline.dlq        │                          │
│                           └──────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Core Patterns

1. **Claim Check Pattern**: Raw binary PCAP files remain in S3/MinIO. Only lightweight JSON metadata envelopes flow through RabbitMQ.
2. **Dynamic Choreography**: The `itinerary` array inside each envelope determines routing. External developers can dynamically rewrite this array in their decoder code.
3. **Platform Sidecar Pattern**: Each Pod contains the developer's business logic container and a platform-managed sidecar that handles all AMQP plumbing, ACKs, NACKs, DLQ routing, and HTTP forwarding.

## Repository Structure

```
self_help/
├── part1_windmill/
│   ├── SETUP_GUIDE.md              # Conceptual Windmill UI configuration
│   ├── WINDMILL_SETUP.md           # Complete click-by-click setup & deployment guide
│   ├── deploy_decoder.py           # Windmill backend script (K8s Deployment generator)
│   └── windmill_deployment/
│       └── docker-compose.yml      # Self-hosted Windmill stack (CE)
├── part2_decoder/
│   ├── src/
│   │   └── main.cpp            # C++ Business Logic Decoder Server
│   └── Dockerfile              # Multi-stage build for minimal static binary
├── part3_sidecar/
│   ├── sidecar.py              # High-reliability AMQP sidecar (pika)
│   ├── requirements.txt        # Python dependencies
│   └── Dockerfile              # Sidecar container image
├── part4_infrastructure/
│   └── infrastructure.yaml     # Unified K8s manifests (decoder + downstream workers)
└── part5_poc/
    ├── docker-compose.yml      # Local testing laboratory
    ├── setup_and_test.sh       # Automated end-to-end orchestration
    ├── test_pipeline.py        # Inject & verify messages
    ├── enrichment_geoip/
    │   ├── main.py             # GeoIP enrichment worker (FastAPI)
    │   └── Dockerfile
    ├── enrichment_threat_intel/
    │   ├── main.py             # Threat intel enrichment worker (FastAPI)
    │   └── Dockerfile
    └── formatter_json/
        ├── main.py             # JSON formatter worker (FastAPI)
        └── Dockerfile
```

## Quick Start: Windmill Portal Setup

To run the Windmill Self-Help UI locally and start onboarding developers:

```bash
cd part1_windmill/windmill_deployment
docker compose up -d
# Open http://localhost:8000 and follow the UI setup guide
```

See `part1_windmill/WINDMILL_SETUP.md` for the complete click-by-click guide to create the Developer Onboarding Portal app, bind the form to the deployment script, and verify end-to-end K8s deployment.

---

## Quick Start: Local Pipeline POC

The fastest way to validate the entire pipeline architecture is to run the automated POC script.

### Prerequisites

- Docker Engine >= 24.0
- Docker Compose >= 2.20
- Bash

### Run the POC

```bash
chmod +x part5_poc/setup_and_test.sh
./part5_poc/setup_and_test.sh
```

This script will:
1. Build all container images (C++ decoder, Python sidecar, enrichment worker, formatter worker).
2. Start RabbitMQ (with Management UI on [http://localhost:15672](http://localhost:15672)) and MinIO (Console on [http://localhost:9001](http://localhost:9001)).
3. Seed MinIO with a sample PCAP object.
4. Start the Decoder Pod and downstream workers, each using `network_mode: service:<worker>` to simulate Kubernetes Pod localhost networking.
5. Declare all RabbitMQ queues.
6. Inject an **Initial Envelope** into `decoder.cplusplus`.
7. Stream live logs for 15 seconds.
8. Verify the message successfully arrives at `pipeline.completed`.

### Expected Output

You will see:
- The C++ decoder receiving the envelope, detecting fingerprint `0x8100`, and injecting `enrichment.threat_intel` into the itinerary.
- The sidecar popping `decoder.cplusplus` from the itinerary and routing to `enrichment.geoip`.
- The GeoIP enrichment worker adding geographic metadata.
- The formatter normalizing the output.
- The final envelope arriving at `pipeline.completed`.

### Teardown

```bash
docker compose -f part5_poc/docker-compose.yml down --volumes
```

## Component Details

### Part 1: Windmill Self-Help Portal

See `part1_windmill/SETUP_GUIDE.md` for detailed instructions on configuring the low-code UI. The `deploy_decoder.py` script:
- Sanitizes developer inputs.
- Generates a deterministic, collision-resistant Deployment name.
- Builds a complete K8s manifest with:
  - Two containers per Pod (business logic + sidecar).
  - Resource limits and requests.
  - Security contexts (non-root, read-only root filesystem, dropped capabilities).
  - Liveness and readiness probes.
  - Topology spread constraints for resilience.
- Injects `MY_QUEUE` into the sidecar to bind it to the correct RabbitMQ queue.

### Part 2: C++ Business Logic Decoder

A production-ready C++ HTTP server using `cpp-httplib` (header-only). Key behaviors:
- `POST /process`: Receives the JSON envelope, inspects `fingerprint`, dynamically rewrites `itinerary`, mocks an S3 write, updates `decoded_data_uri`, and returns the modified envelope.
- Dynamic routing rule: If fingerprint matches known threat indicators (`0x8100`, `0x0806`, `0x88E1`), injects `enrichment.threat_intel` before `formatter.json`.
- Built as a statically-linked binary in a multi-stage Dockerfile for a minimal `scratch`-based runtime image.

### Part 3: Python AMQP Sidecar

A robust, long-running Python script using `pika`:
- Reads `MY_QUEUE` from environment variables.
- Establishes a durable channel with manual acknowledgments (`auto_ack=False`).
- Forwards envelopes to the business logic container via HTTP POST.
- On HTTP 200: parses the response, pops the current queue from `itinerary`, publishes to the next queue, and ACKs.
- On failure (timeout, connection error, HTTP 500): logs the failure and NACKs with `requeue=False` to route to the DLQ.
- Includes connection recovery, graceful shutdown on SIGTERM/SIGINT, and structured logging.

### Part 4: Kubernetes Manifests

`infrastructure.yaml` provides:
- ConfigMap for non-sensitive platform configuration.
- Secret template for RabbitMQ credentials.
- **decoder-example** Deployment: demonstrates the two-container Pod pattern.
- **enrichment-geoip** Deployment: downstream worker proving continuous event flow.
- **formatter-json** Deployment: final stage routing to `pipeline.completed`.
- ServiceAccounts for each workload.
- Security hardening (security contexts, non-root, read-only root FS).
- Topology spread constraints for high availability.

### Part 5: Local Testing Laboratory

The `docker-compose.yml` simulates the full Kubernetes architecture locally:
- RabbitMQ with Management UI.
- MinIO object store.
- Decoder Pod (C++ decoder + sidecar sharing network namespace).
- Enrichment Pod (Python worker + sidecar sharing network namespace).
- Formatter Pod (Python worker + sidecar sharing network namespace).

`test_pipeline.py` provides:
- `--inject-only`: Publishes the Initial Envelope to `decoder.cplusplus`.
- `--verify`: Consumes from `pipeline.completed` and prints a detailed journey report.
- `--timeout`: Configurable wait time for verification.

## Security Considerations

- All containers run as non-root users.
- Business logic containers use `readOnlyRootFilesystem: true`.
- All capabilities are dropped.
- RabbitMQ credentials are injected via Kubernetes Secrets, not environment variables in plain text.
- The sidecar image is platform-managed and immutable to external developers.
- Resource quotas prevent noisy-neighbor issues in multi-tenant environments.

## Production Deployment Checklist

1. Replace `registry.example.com/...` image URIs with your actual registry.
2. Populate the `rabbitmq-credentials` Secret with production credentials (or integrate with Vault/External Secrets Operator).
3. Configure NetworkPolicies to restrict inter-pod traffic to necessary ports.
4. Enable Prometheus scraping annotations (already present in the manifests) and deploy ServiceMonitors.
5. Configure PodDisruptionBudgets for each Deployment.
6. Set up alerts for DLQ depth, consumer lag, and HTTP error rates.
7. Use HorizontalPodAutoscalers based on CPU/RabbitMQ queue depth metrics.
8. Enable MinIO/S3 bucket versioning and lifecycle policies for raw PCAP retention.

## License

This reference architecture is provided as-is for educational and production adaptation purposes.
# Self_help_pipeline
