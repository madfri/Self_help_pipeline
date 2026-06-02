# Part 1: Windmill Self-Help Developer Onboarding Portal

## Architectural Overview

The Windmill Developer Onboarding Portal serves as the single control plane for external
developers to register custom protocol decoders. Upon form submission, Windmill triggers
a Python script that uses the `kubernetes` client library to dynamically create a
Kubernetes Deployment containing two containers: the developer's business logic decoder
and the platform-managed AMQP sidecar.

## Prerequisites

1. Windmill instance running in-cluster or with outbound access to the K8s API server.
2. A Kubernetes ServiceAccount bound to a Role with permissions to create Deployments
   and Services in the target namespace.
3. The `kubernetes` Python library installed in the Windmill execution environment.

## Step-by-Step Windmill UI Configuration

### Step 1: Create a New Windmill App

1. Log in to Windmill.
2. Navigate to **Apps** → **New App**.
3. Name the app: `Developer Onboarding Portal`.
4. Set the app path to: `f/self_help/developer_onboarding_portal`.

### Step 2: Add Input Form Fields

Drag the following components onto the canvas in order:

#### Field 1: Developer Name
- **Component Type**: `Text Input`
- **Label**: `Developer Name`
- **Variable Name**: `developer_name`
- **Placeholder**: `Jane Doe`
- **Required**: `true`
- **Validation Regex**: `^[a-zA-Z0-9_\-\s]{2,64}$`

#### Field 2: Protocol ID (Fingerprint)
- **Component Type**: `Text Input`
- **Label**: `Protocol ID (Fingerprint)`
- **Variable Name**: `protocol_fingerprint`
- **Placeholder**: `0x8100`
- **Required**: `true`
- **Validation Regex**: `^0x[0-9A-Fa-f]{2,8}$`

#### Field 3: Runtime Language
- **Component Type**: `Select`
- **Label**: `Runtime Language`
- **Variable Name**: `runtime_language`
- **Options**: `["C++", "Rust", "Go"]`
- **Default Value**: `C++`
- **Required**: `true`

#### Field 4: Docker Image Registry URI
- **Component Type**: `Text Input`
- **Label**: `Docker Image Registry URI`
- **Variable Name**: `docker_image_uri`
- **Placeholder**: `registry.example.com/decoders/my-decoder:v1.2.3`
- **Required**: `true`
- **Validation Regex**: `^[a-z0-9._-]+/[a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+$`

#### Field 5: Target Queue Name
- **Component Type**: `Text Input`
- **Label**: `Target Queue Name`
- **Variable Name**: `target_queue`
- **Placeholder**: `decoder.cplusplus`
- **Required**: `true`
- **Default Value**: `decoder.cplusplus`

### Step 3: Configure the Submit Button

- **Component Type**: `Button`
- **Label**: `Deploy Decoder`
- **Color**: `Blue`
- **Runnable**: Link to the backend script `u/admin/deploy_decoder_k8s`.

### Step 4: Bind Form Data to the Backend Script

In the Button's **Runnable Inputs** panel, map each form variable to the script arguments:

| App Variable           | Script Argument        |
|------------------------|------------------------|
| `developer_name`       | `developer_name`       |
| `protocol_fingerprint` | `protocol_fingerprint` |
| `runtime_language`     | `runtime_language`     |
| `docker_image_uri`     | `docker_image_uri`     |
| `target_queue`         | `target_queue`         |

## Backend Script Deployment

Upload the `deploy_decoder.py` script (provided alongside this guide) to Windmill at:
```
u/admin/deploy_decoder_k8s
```

Set the script type to **Python** and expose the arguments:
- `developer_name: str`
- `protocol_fingerprint: str`
- `runtime_language: str`
- `docker_image_uri: str`
- `target_queue: str = "decoder.cplusplus"`

## RBAC Requirements

The Windmill worker pods must run under a ServiceAccount with the following permissions:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: windmill-deployment-manager
  namespace: pelt-platform
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["create", "get", "list", "watch", "update", "patch"]
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["create", "get", "list"]
```

## Operational Notes

- The sidecar image is pinned by the platform and is NOT editable by external developers.
- Each Deployment receives a unique name based on the developer name and a short hash
to prevent collisions.
- Resource limits are enforced by the platform to prevent noisy-neighbor issues in
the multi-tenant cluster.
- The `MY_QUEUE` environment variable injected into the sidecar binds it to the correct
RabbitMQ queue for this decoder's protocol fingerprint.
