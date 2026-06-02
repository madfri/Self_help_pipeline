# Self-Help ELT Platform: Detailed Architecture

This document provides comprehensive architecture diagrams illustrating how all five components of the multi-tenant PCAP processing platform interconnect.

---

## 1. High-Level System Architecture

This diagram shows the complete platform from the external developer's perspective through to the final pipeline completion.

```mermaid
graph TB
    subgraph "External Developer"
        DEV[Browser]
    end

    subgraph "Part 1: Windmill Self-Help Portal"
        WM[Windmill Server<br/>localhost:8000]
        APP[Developer Onboarding Portal<br/>Low-Code App]
        SCRIPT[deploy_decoder_k8s.py<br/>Python Script]
    end

    subgraph "Kubernetes Cluster"
        K8S_API[K8s API Server]

        subgraph "Decoder Pod"
            C_DECODER[C++ Decoder Server<br/>127.0.0.1:8080]
            C_SIDEAR[Platform Sidecar<br/>Python + Pika]
        end

        subgraph "GeoIP Pod"
            PY_GEOIP[GeoIP Enrichment<br/>FastAPI 127.0.0.1:8080]
            GEO_SIDEAR[Platform Sidecar]
        end

        subgraph "Threat Intel Pod"
            PY_THREAT[Threat Intel Enrichment<br/>FastAPI 127.0.0.1:8080]
            THR_SIDEAR[Platform Sidecar]
        end

        subgraph "Formatter Pod"
            PY_FMT[JSON Formatter<br/>FastAPI 127.0.0.1:8080]
            FMT_SIDEAR[Platform Sidecar]
        end
    end

    subgraph "Infrastructure Layer"
        RMQ[RabbitMQ Broker<br/>localhost:5672]
        MINIO[MinIO S3-Compatible Store<br/>localhost:9000]
    end

    subgraph "Completed Pipeline"
        DLQ[(Dead Letter Queue<br/>pipeline.dlq)]
        COMP[(Completed Queue<br/>pipeline.completed)]
    end

    DEV -->|HTTPS| WM
    WM --> APP
    APP -->|Form Submit| SCRIPT
    SCRIPT -->|Apply Deployment| K8S_API
    K8S_API -->|Creates| C_DECODER
    K8S_API -->|Creates| C_SIDEAR

    MINIO -->|Claim Check<br/>Raw PCAP Binary| C_DECODER
    C_SIDEAR <-->|AMQP Consume| RMQ
    C_SIDEAR -->|HTTP POST<br/>JSON Envelope| C_DECODER
    C_DECODER -->|HTTP 200<br/>Modified Envelope| C_SIDEAR
    C_SIDEAR -->|Publish| RMQ

    RMQ -->|Route to<br/>enrichment.geoip| GEO_SIDEAR
    GEO_SIDEAR -->|HTTP POST| PY_GEOIP
    PY_GEOIP -->|HTTP 200| GEO_SIDEAR
    GEO_SIDEAR -->|Publish| RMQ

    RMQ -->|Route to<br/>enrichment.threat_intel| THR_SIDEAR
    THR_SIDEAR -->|HTTP POST| PY_THREAT
    PY_THREAT -->|HTTP 200| THR_SIDEAR
    THR_SIDEAR -->|Publish| RMQ

    RMQ -->|Route to<br/>formatter.json| FMT_SIDEAR
    FMT_SIDEAR -->|HTTP POST| PY_FMT
    PY_FMT -->|HTTP 200| FMT_SIDEAR
    FMT_SIDEAR -->|Publish| RMQ

    RMQ -->|DLQ| DLQ
    RMQ -->|Final| COMP

    style DEV fill:#e1f5fe
    style WM fill:#fff3e0
    style APP fill:#fff3e0
    style SCRIPT fill:#fff3e0
    style C_DECODER fill:#e8f5e9
    style C_SIDEAR fill:#ffebee
    style PY_GEOIP fill:#e8f5e9
    style GEO_SIDEAR fill:#ffebee
    style PY_THREAT fill:#e8f5e9
    style THR_SIDEAR fill:#ffebee
    style PY_FMT fill:#e8f5e9
    style FMT_SIDEAR fill:#ffebee
    style RMQ fill:#f3e5f5
    style MINIO fill:#f3e5f5
    style COMP fill:#c8e6c9
    style DLQ fill:#ffcdd2
```

---

## 2. The Platform Sidecar Pattern (Pod-Level Detail)

This diagram zooms into a single Pod to show exactly how the business logic container and the platform sidecar share the localhost network namespace.

```mermaid
graph LR
    subgraph "Kubernetes Pod: decoder-example"
        subgraph "Shared Network Namespace"
            direction TB
            LOOPBACK[127.0.0.1 Loopback]
        end

        subgraph "Container: business-logic"
            C_HEALTH["/health<br/>200 OK"]
            C_READY["/ready<br/>200 OK"]
            C_PROCESS["/process<br/>POST JSON Envelope"]
            C_CODE[C++ Decoder Code]
        end

        subgraph "Container: sidecar"
            S_AMQP[AMQP Consumer<br/>pika BlockingConnection]
            S_HTTP[HTTP Client<br/>requests Session]
            S_ROUTER[Itinerary Router<br/>Pop Current Queue]
            S_ACK[Manual ACK/NACK]
            S_DLQ[DLQ Handler]
        end
    end

    RMQ_IN["RabbitMQ<br/>decoder.cplusplus"]
    RMQ_OUT["RabbitMQ<br/>enrichment.geoip"]

    RMQ_IN -->|1. Consume Message| S_AMQP
    S_AMQP -->|2. Forward JSON| S_HTTP
    S_HTTP -->|3. POST 127.0.0.1:8080/process| LOOPBACK
    LOOPBACK -->|4. Receive| C_PROCESS
    C_PROCESS -->|5. Parse Fingerprint| C_CODE
    C_CODE -->|6. Rewrite Itinerary| C_PROCESS
    C_PROCESS -->|7. Return 200 + JSON| LOOPBACK
    LOOPBACK -->|8. Response| S_HTTP
    S_HTTP -->|9. Parse Response| S_ROUTER
    S_ROUTER -->|10. Pop 'decoder.cplusplus'| S_ROUTER
    S_ROUTER -->|11. Determine Next Queue| S_AMQP
    S_AMQP -->|12. Publish| RMQ_OUT
    S_AMQP -->|13. ch.basic_ack| RMQ_IN

    C_PROCESS -.->|Liveness Probe| C_HEALTH
    C_PROCESS -.->|Readiness Probe| C_READY

    S_HTTP -.->|Timeout / 500| S_DLQ
    S_DLQ -->|ch.basic_nack<br/>requeue=False| RMQ_IN

    style C_CODE fill:#e8f5e9
    style S_AMQP fill:#ffebee
    style S_ROUTER fill:#ffebee
    style LOOPBACK fill:#fff9c4
```

---

## 3. Message Flow & Dynamic Choreography

This sequence diagram shows the exact lifecycle of an Initial Envelope as it progresses through the pipeline, including the dynamic itinerary rewrite.

```mermaid
sequenceDiagram
    autonumber
    participant IN as Test Injector
    participant RMQ as RabbitMQ
    participant D_S as Decoder Sidecar
    participant D_C as C++ Decoder
    participant G_S as GeoIP Sidecar
    participant G_C as GeoIP Worker
    participant T_S as ThreatIntel Sidecar
    participant T_C as ThreatIntel Worker
    participant F_S as Formatter Sidecar
    participant F_C as Formatter Worker
    participant OUT as pipeline.completed

    Note over IN,D_C: Initial Envelope<br/>itinerary: [decoder.cplusplus, enrichment.geoip, formatter.json]<br/>fingerprint: 0x8100

    IN->>RMQ: Publish to decoder.cplusplus
    RMQ->>D_S: Deliver message (delivery_tag=1)
    D_S->>D_C: POST 127.0.0.1:8080/process
    D_C->>D_C: Inspect fingerprint 0x8100
    Note right of D_C: Threat indicator detected!<br/>Insert 'enrichment.threat_intel' before 'formatter.json'
    D_C->>D_S: HTTP 200 + Modified Envelope<br/>itinerary: [decoder.cplusplus, enrichment.geoip, enrichment.threat_intel, formatter.json]
    D_S->>D_S: Pop 'decoder.cplusplus'<br/>Next queue: enrichment.geoip
    D_S->>RMQ: Publish to enrichment.geoip
    D_S->>RMQ: ch.basic_ack(delivery_tag=1)

    RMQ->>G_S: Deliver message
    G_S->>G_C: POST 127.0.0.1:8080/process
    G_C->>G_C: Add geoip metadata
    G_C->>G_S: HTTP 200 + Enriched Envelope
    G_S->>G_S: Pop 'enrichment.geoip'<br/>Next queue: enrichment.threat_intel
    G_S->>RMQ: Publish to enrichment.threat_intel
    G_S->>RMQ: ch.basic_ack()

    RMQ->>T_S: Deliver message
    T_S->>T_C: POST 127.0.0.1:8080/process
    T_C->>T_C: Add IoC / reputation data
    T_C->>T_S: HTTP 200 + Enriched Envelope
    T_S->>T_S: Pop 'enrichment.threat_intel'<br/>Next queue: formatter.json
    T_S->>RMQ: Publish to formatter.json
    T_S->>RMQ: ch.basic_ack()

    RMQ->>F_S: Deliver message
    F_S->>F_C: POST 127.0.0.1:8080/process
    F_C->>F_C: Normalize schema, set status
    F_C->>F_S: HTTP 200 + Formatted Envelope
    F_S->>F_S: Pop 'formatter.json'<br/>Next queue: pipeline.completed
    F_S->>RMQ: Publish to pipeline.completed
    F_S->>RMQ: ch.basic_ack()

    RMQ->>OUT: Message arrives
    Note over OUT: Final Envelope<br/>itinerary: []<br/>pipeline_status: formatted
```

---

## 4. Claim Check Pattern Detail

This diagram illustrates how raw binary data never flows through the message broker — only lightweight metadata envelopes do.

```mermaid
graph LR
    subgraph "Object Storage"
        RAW[(Raw PCAP Bucket<br/>s3://packet-storage/raw/)]
        DEC[(Decoded Output Bucket<br/>s3://packet-storage/decoded/)]
    end

    subgraph "Message Broker"
        Q1[decoder.cplusplus]
        Q2[enrichment.geoip]
        Q3[enrichment.threat_intel]
        Q4[formatter.json]
        Q5[pipeline.completed]
    end

    subgraph "JSON Envelope Contents"
        ENV1["{<br/>pcap_uri: s3://.../raw/file_123.pcap,<br/>decoded_data_uri: '',<br/>fingerprint: 0x8100,<br/>itinerary: [decoder.cplusplus, ...]<br/>}"]
        ENV2["{<br/>pcap_uri: s3://.../raw/file_123.pcap,<br/>decoded_data_uri: s3://.../decoded/file.json,<br/>fingerprint: 0x8100,<br/>itinerary: [enrichment.geoip, ...]<br/>}"]
    end

    RAW -.->|1. Reference only| ENV1
    ENV1 -->|2. Flows through| Q1
    ENV1 --> Q2
    ENV1 --> Q3
    ENV1 --> Q4
    ENV1 --> Q5
    ENV2 -.->|3. Reference to decoded output| DEC

    style RAW fill:#c8e6c9
    style DEC fill:#c8e6c9
    style ENV1 fill:#fff9c4
    style ENV2 fill:#fff9c4
    style Q1 fill:#f3e5f5
    style Q2 fill:#f3e5f5
    style Q3 fill:#f3e5f5
    style Q4 fill:#f3e5f5
    style Q5 fill:#f3e5f5
```

---

## 5. Windmill-to-Kubernetes Deployment Flow

This diagram shows exactly what happens when an external developer clicks **Deploy Decoder** in the Windmill Self-Help Portal.

```mermaid
graph TB
    subgraph "External Developer"
        FORM_FILL[Fill Form:<br/>- Name<br/>- Fingerprint<br/>- Runtime<br/>- Docker Image<br/>- Target Queue]
    end

    subgraph "Windmill Control Plane"
        UI[Windmill App UI<br/>Developer Onboarding Portal]
        SCRIPT[Windmill Script Executor<br/>deploy_decoder_k8s.py]
    end

    subgraph "Kubernetes Control Plane"
        API[K8s API Server]
        ETCD[etcd]
        SCHED[Scheduler]
    end

    subgraph "Worker Node"
        KUBELET[Kubelet]

        subgraph "Created Pod: decoder-alice-dev"
            CONT1[Container: business-logic<br/>External Dev's C++ Image]
            CONT2[Container: sidecar<br/>Platform Sidecar Image]
        end
    end

    subgraph "Secret Store"
        SECRET[Secret: rabbitmq-credentials<br/>host, port, user, pass]
    end

    FORM_FILL -->|Submit| UI
    UI -->|Trigger Script<br/>Pass form values| SCRIPT
    SCRIPT -->|1. Generate Deployment Manifest<br/>2. Set MY_QUEUE env var| API
    API -->|Store desired state| ETCD
    ETCD -->|Notify| SCHED
    SCHED -->|Assign to Node| KUBELET
    KUBELET -->|Pull Images| CONT1
    KUBELET -->|Pull Images| CONT2
    KUBELET -->|Inject Secrets| CONT2
    SECRET -->|Mount as envFrom| CONT2

    style UI fill:#fff3e0
    style SCRIPT fill:#fff3e0
    style API fill:#e3f2fd
    style CONT1 fill:#e8f5e9
    style CONT2 fill:#ffebee
    style SECRET fill:#fce4ec
```

---

## 6. Error Handling & Dead Letter Queue Flow

This diagram shows what happens when the business logic container fails or returns an HTTP 500.

```mermaid
graph TB
    subgraph "Normal Flow"
        RMQ[RabbitMQ Queue]
        SIDEAR[Platform Sidecar]
        BIZ[Business Logic<br/>127.0.0.1:8080]
        NEXT[Next Queue]
    end

    subgraph "Failure Scenarios"
        TIMEOUT[HTTP Timeout]
        CONN_ERR[Connection Refused]
        HTTP_500[HTTP 500 Error]
        BAD_JSON[Invalid JSON Response]
    end

    subgraph "Dead Letter Queue"
        DLQ[(pipeline.dlq)]
        DLQ_CONSUMER[DLQ Consumer / Alert Manager]
        ALERT[PagerDuty / Slack Alert]
    end

    RMQ -->|Message| SIDEAR
    SIDEAR -->|POST /process| BIZ

    BIZ -.->|Crash / Unreachable| CONN_ERR
    BIZ -.->|Slow / Hanging| TIMEOUT
    BIZ -.->|Runtime Exception| HTTP_500
    BIZ -.->|Malformed JSON| BAD_JSON

    CONN_ERR -->|ch.basic_nack<br/>requeue=False| DLQ
    TIMEOUT -->|ch.basic_nack<br/>requeue=False| DLQ
    HTTP_500 -->|ch.basic_nack<br/>requeue=False| DLQ
    BAD_JSON -->|ch.basic_nack<br/>requeue=False| DLQ

    BIZ -->|HTTP 200| SIDEAR
    SIDEAR -->|ch.basic_ack| RMQ
    SIDEAR -->|Publish| NEXT

    DLQ -->|Monitor Depth| DLQ_CONSUMER
    DLQ_CONSUMER -->|Alert on Threshold| ALERT

    style RMQ fill:#f3e5f5
    style SIDEAR fill:#ffebee
    style BIZ fill:#e8f5e9
    style DLQ fill:#ffcdd2
    style CONN_ERR fill:#ffebee
    style TIMEOUT fill:#ffebee
    style HTTP_500 fill:#ffebee
    style BAD_JSON fill:#ffebee
    style ALERT fill:#fff3e0
```

---

## 7. Component Relationship Matrix

| Component | Part | Technology | Interfaces With | Responsibility |
|-----------|------|------------|-----------------|----------------|
| **Windmill Server** | 1 | Docker (ghcr.io) | Browser, Worker, Postgres | Serves UI & API |
| **Windmill Worker** | 1 | Docker (ghcr.io) | Server, K8s API | Executes Python deployment script |
| **Developer Portal App** | 1 | Windmill Low-Code | Windmill Script | Form UI for developer onboarding |
| **deploy_decoder_k8s.py** | 1 | Python + kubernetes | K8s API Server | Generates & applies K8s Deployment manifests |
| **C++ Decoder Server** | 2 | C++17 + cpp-httplib | Sidecar (localhost) | Inspects fingerprint, rewrites itinerary, mocks S3 write |
| **Platform Sidecar** | 3 | Python + pika + requests | RabbitMQ, Business Logic | AMQP consumer, HTTP forwarding, ACK/NACK, DLQ routing |
| **RabbitMQ Broker** | 3/5 | RabbitMQ 3.12 | All Sidecars | Durable queues, message routing, DLQ |
| **MinIO Object Store** | 5 | MinIO | Test Seeder, C++ Decoder | S3-compatible raw PCAP & decoded output storage |
| **GeoIP Worker** | 4/5 | Python + FastAPI | GeoIP Sidecar | Adds geographic metadata to envelope |
| **Threat Intel Worker** | 4/5 | Python + FastAPI | Threat Sidecar | Adds IoC / reputation metadata to envelope |
| **Formatter Worker** | 4/5 | Python + FastAPI | Formatter Sidecar | Normalizes output schema, sets pipeline_status |
| **K8s Deployment Manifest** | 4 | YAML | Kubectl / API Server | Declares Pods, containers, security contexts, ServiceAccounts |

---

## 8. Network Topology (Docker Compose POC)

This diagram shows how the local POC simulates the Kubernetes Pod networking model using Docker Compose.

```mermaid
graph TB
    subgraph "Docker Network: pelt-poc_pelt-network"
        RMQ[RabbitMQ<br/>rabbitmq:5672]
        MINIO[MinIO<br/>minio:9000]

        subgraph "Simulated Pod: Decoder"
            D_NET[Network Namespace<br/>Shared]
            D_CPP[C++ Decoder<br/>127.0.0.1:8080]
            D_SIDE[Sidecar<br/>network_mode: service:decoder]
        end

        subgraph "Simulated Pod: GeoIP"
            G_NET[Network Namespace<br/>Shared]
            G_PY[GeoIP Worker<br/>127.0.0.1:8080]
            G_SIDE[Sidecar<br/>network_mode: service:enrichment]
        end

        subgraph "Simulated Pod: ThreatIntel"
            T_NET[Network Namespace<br/>Shared]
            T_PY[ThreatIntel Worker<br/>127.0.0.1:8080]
            T_SIDE[Sidecar<br/>network_mode: service:threat-intel]
        end

        subgraph "Simulated Pod: Formatter"
            F_NET[Network Namespace<br/>Shared]
            F_PY[Formatter Worker<br/>127.0.0.1:8080]
            F_SIDE[Sidecar<br/>network_mode: service:formatter]
        end
    end

    RMQ <-->|AMQP| D_SIDE
    D_SIDE -->|HTTP 127.0.0.1:8080| D_CPP
    D_SIDE -->|AMQP Publish| RMQ
    RMQ <-->|AMQP| G_SIDE
    G_SIDE -->|HTTP 127.0.0.1:8080| G_PY
    G_SIDE -->|AMQP Publish| RMQ
    RMQ <-->|AMQP| T_SIDE
    T_SIDE -->|HTTP 127.0.0.1:8080| T_PY
    T_SIDE -->|AMQP Publish| RMQ
    RMQ <-->|AMQP| F_SIDE
    F_SIDE -->|HTTP 127.0.0.1:8080| F_PY
    F_SIDE -->|AMQP Publish| RMQ

    D_CPP -.->|Resolves via DNS| RMQ
    D_SIDE -.->|Resolves via DNS| RMQ

    style D_NET fill:#fff9c4
    style G_NET fill:#fff9c4
    style T_NET fill:#fff9c4
    style F_NET fill:#fff9c4
    style RMQ fill:#f3e5f5
    style MINIO fill:#f3e5f5
```

---

## How to Render These Diagrams

These diagrams use **Mermaid** syntax. You can render them in:

1. **VS Code** with the [Markdown Preview Mermaid Support](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) extension
2. **GitHub** — Mermaid is natively supported in Markdown files
3. **Any browser** via [Mermaid Live Editor](https://mermaid.live/) — copy-paste the diagram code
4. **Obsidian**, **Notion**, or **GitLab** — all support Mermaid natively

If you prefer a static image, paste any diagram block into [Mermaid Live Editor](https://mermaid.live/) and export as PNG/SVG.
