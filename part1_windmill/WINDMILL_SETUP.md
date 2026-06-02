# Windmill Self-Help Portal: Complete Setup & UI Configuration Guide

This guide walks you through deploying Windmill locally, creating the **Developer Onboarding Portal** app, wiring it to the backend deployment script, and verifying that submitting the form dynamically creates a Kubernetes Deployment.

---

## Prerequisites

- Docker & Docker Compose
- A Kubernetes cluster (or `kubectl` + `kind`/`k3d` for local testing)
- The `kubernetes` Python package available in the Windmill worker environment

---

## Step 1: Start Windmill

```bash
cd part1_windmill/windmill_deployment
docker compose up -d
```

Wait for all services to be healthy:

```bash
docker compose ps
```

You should see `windmill-server`, `windmill-worker`, `windmill-lsp`, and `db` all in a healthy/running state.

Open your browser to:

```
http://localhost:8000
```

**Default credentials:**
- Email: `admin@windmill.dev`
- Password: `changeme`

> **Security:** Change the default password immediately after your first login via **Settings** → **Account**.

---

## Step 2: Configure the Windmill Worker for Kubernetes

The Windmill worker container must be able to talk to your Kubernetes API server and have the `kubernetes` Python library installed.

### Option A: Local `kind` / `k3d` Cluster

If you are using a local Kubernetes cluster (e.g., `kind` or `k3d`), copy your kubeconfig into the worker container or mount it:

```bash
# Example for kind
docker cp ~/.kube/config windmill-worker:/root/.kube/config
```

### Option B: In-Cluster Deployment (Production)

In production, Windmill itself runs inside Kubernetes. The worker uses the in-cluster ServiceAccount. Ensure that ServiceAccount is bound to a Role that can create Deployments:

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

### Install the `kubernetes` Package in Windmill

Windmill workers need the `kubernetes` Python library. You can install it via Windmill's **Custom Python Requirements** feature:

1. In Windmill, go to **Workspace Settings** (gear icon, top-right).
2. Navigate to the **Python Requirements** tab (or **Custom Environment Variables / Init Scripts**).
3. Add `kubernetes==29.0.0` to the worker's Python dependencies.
4. Restart the worker container:
   ```bash
   docker restart windmill-worker
   ```

Alternatively, if you built a custom Windmill worker image, bake the dependency in:

```dockerfile
FROM ghcr.io/windmill-labs/windmill:main
RUN pip install kubernetes==29.0.0
```

---

## Step 3: Create the Backend Deployment Script

Before building the UI, create the Python script that the form will trigger.

1. In Windmill, click **Scripts** in the left sidebar.
2. Click **New Script**.
3. Choose **Python** as the language.
4. Set the script path to: `u/admin/deploy_decoder_k8s`
5. Copy the **entire contents** of `part1_windmill/deploy_decoder.py` into the editor.
6. In the script's **Arguments** section on the right panel, define the following fields (Windmill will auto-detect them if you use the function signature, but you can also lock them manually):

| Argument Name          | Type   | Required | Default               |
|------------------------|--------|----------|-----------------------|
| `developer_name`       | str    | Yes      | —                     |
| `protocol_fingerprint` | str    | Yes      | —                     |
| `runtime_language`     | str    | Yes      | `"C++"`               |
| `docker_image_uri`     | str    | Yes      | —                     |
| `target_queue`         | str    | Yes      | `"decoder.cplusplus"` |

7. Click **Save** (top-right).
8. Click **Run** to test the script manually once. It should execute without error (or gracefully handle the lack of K8s connectivity if running locally without a cluster).

---

## Step 4: Create the "Developer Onboarding Portal" App

Now build the low-code UI that external developers will interact with.

### 4.1 Create a New App

1. In the Windmill sidebar, click **Apps**.
2. Click **New App**.
3. Name the app: `Developer Onboarding Portal`
4. Set the app path to: `f/self_help/developer_onboarding_portal`
5. Click **Create**.

You are now in the **App Editor** canvas.

### 4.2 Add the Title Header

1. From the component palette on the right, drag a **Text** component onto the canvas.
2. Place it at the top.
3. In the component's configuration panel (right side), set:
   - **Value**: `Developer Onboarding Portal`
   - **Style**: `H1` (or set font size to `24px`, bold)
   - **Text Color**: `#1a73e8`

### 4.3 Add the Input Form Fields

Drag each component from the palette onto the canvas in order. After placing each one, configure it using the right-hand property panel.

#### Field 1: Developer Name
- **Component Type**: `Text Input` (under Inputs)
- **Label**: `Developer Name`
- **Placeholder**: `Jane Doe`
- **Required**: `true`
- **Validation**: `^[a-zA-Z0-9_\-\s]{2,64}$`
- **Custom Validation Message**: `Name must be 2-64 alphanumeric characters.`
- **Output / Variable Name**: `developer_name`

#### Field 2: Protocol ID (Fingerprint)
- **Component Type**: `Text Input`
- **Label**: `Protocol ID (Fingerprint)`
- **Placeholder**: `0x8100`
- **Required**: `true`
- **Validation**: `^0x[0-9A-Fa-f]{2,8}$`
- **Custom Validation Message**: `Enter a valid hex fingerprint like 0x8100.`
- **Output / Variable Name**: `protocol_fingerprint`

#### Field 3: Runtime Language
- **Component Type**: `Select` (under Inputs)
- **Label**: `Runtime Language`
- **Items / Options**:
  ```json
  [
    { "value": "C++", "label": "C++" },
    { "value": "Rust", "label": "Rust" },
    { "value": "Go", "label": "Go" }
  ]
  ```
- **Default Value**: `C++`
- **Required**: `true`
- **Output / Variable Name**: `runtime_language`

#### Field 4: Docker Image Registry URI
- **Component Type**: `Text Input`
- **Label**: `Docker Image Registry URI`
- **Placeholder**: `registry.example.com/decoders/my-decoder:v1.2.3`
- **Required**: `true`
- **Validation**: `^[a-z0-9._-]+/[a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+$`
- **Custom Validation Message**: `Must be a valid image URI (registry/repo:tag).`
- **Output / Variable Name**: `docker_image_uri`

#### Field 5: Target Queue Name
- **Component Type**: `Text Input`
- **Label**: `Target Queue Name`
- **Placeholder**: `decoder.cplusplus`
- **Required**: `true`
- **Default Value**: `decoder.cplusplus`
- **Output / Variable Name**: `target_queue`

> **Tip:** In Windmill, each input component exposes its value as a reactive variable. You can see them listed in the **Context Variables** panel on the left.

### 4.4 Add the Submit Button

1. Drag a **Button** component onto the canvas, below all the inputs.
2. Configure it:
   - **Label**: `Deploy Decoder`
   - **Color**: `Primary` (blue)
   - **Size**: `md` (medium)

### 4.5 Bind the Button to the Backend Script

This is the critical wiring step.

1. Click the **Deploy Decoder** button to select it.
2. In the right-hand configuration panel, find the **On Click** section.
3. Change the action type from `None` to **Run Script** (or `Runnable`).
4. A script picker will appear. Search for and select: `u/admin/deploy_decoder_k8s`
5. Windmill will automatically detect the script's arguments and show input fields.
6. For each argument, bind it to the corresponding form component variable:

| Script Argument        | Binding (ctx variable)              |
|------------------------|-------------------------------------|
| `developer_name`       | `a.developer_name`                  |
| `protocol_fingerprint` | `a.protocol_fingerprint`            |
| `runtime_language`     | `a.runtime_language`                |
| `docker_image_uri`     | `a.docker_image_uri`                |
| `target_queue`         | `a.target_queue`                    |

> In Windmill's binding syntax, `a.` refers to App-level context variables (your form components).

7. Toggle **Wait for result** to `true` so the button shows a loading spinner while the K8s manifest is being applied.

### 4.6 Add a Success / Result Display (Optional but Recommended)

1. Drag a **Text** component below the button.
2. Set its **Value** to:
   ```
   Result: {{ b.result }}
   ```
   (or whatever the default variable name is for your button's runnable result)
3. Set **Condition**: only show when the button has been clicked. In Windmill, you can use the **Hidden** toggle with a condition like `!b.result` (hide when no result).

Alternatively, drag an **Alert** component and bind its message to the result.

### 4.7 Save the App

1. Click **Save** (top-right).
2. Click **Publish** to make the app available to users.
3. Copy the **App URL** (e.g., `http://localhost:8000/apps/f/self_help/developer_onboarding_portal`) and share it with your developers.

---

## Step 5: Test the End-to-End Flow

### 5.1 Submit a Test Registration

1. Open the app URL in a new tab.
2. Fill in the form:
   - **Developer Name**: `alice-dev`
   - **Protocol ID**: `0x8100`
   - **Runtime Language**: `C++`
   - **Docker Image**: `registry.example.com/decoders/alice-decoder:v1.0.0`
   - **Target Queue**: `decoder.cplusplus`
3. Click **Deploy Decoder**.

### 5.2 Verify in Kubernetes

If your Windmill worker has access to Kubernetes, run:

```bash
kubectl get deployments -n pelt-platform -l managed-by=windmill-self-help-portal
```

You should see a new Deployment named something like:

```
decoder-alice-dev-a1b2c3
```

Describe it to confirm the Pod spec contains both containers:

```bash
kubectl describe deployment decoder-alice-dev-a1b2c3 -n pelt-platform
```

Look for:
- Container `business-logic` with the developer's image
- Container `sidecar` with `MY_QUEUE=decoder.cplusplus` in its environment variables

---

## Step 6: Hardening for Production

### Workspace & RBAC

1. In Windmill, create a dedicated **Workspace** for external developers (e.g., `external-devs`).
2. Set folder-level permissions so developers can only see the onboarding app, not the underlying script code.
3. Enable **Approval Policies** if you want human review before K8s Deployments are created.

### Image Registry & Security

1. Pin the `sidecar_image` in `deploy_decoder.py` to an immutable digest rather than `:latest`.
2. Add admission webhooks (OPA Gatekeeper / Kyverno) to enforce:
   - Resource limits
   - Read-only root filesystems
   - Non-root users
   - Allowed image registries

### Audit & Observability

1. Windmill automatically logs every script execution. Go to **Runs** to see the full history of who deployed what and when.
2. Export these logs to your SIEM (Splunk, Datadog, etc.) via the Windmill API or by configuring the `RUST_LOG` environment variable.

---

## Troubleshooting

### "kubernetes module not found" when running the script

The Windmill worker doesn't have the `kubernetes` Python package installed. Follow Step 2 to add it to the worker environment and restart the container.

### "Connection refused" to K8s API

The worker can't reach the Kubernetes API server. If running locally:
- Ensure your kubeconfig is mounted into the worker container.
- If using Docker Desktop's built-in K8s, you may need to set `KUBECONFIG` inside the worker or use `network_mode: host` (not recommended for production).

### App variables not binding correctly

In the App Editor, open the **Context Variables** panel (left sidebar). Verify that:
- Each input component shows up as a variable (e.g., `a.developer_name`).
- The button's runnable inputs are bound to `a.<variable_name>` and not hardcoded strings.

### Script times out

Creating a Deployment can take 10-30 seconds. Increase the script timeout in Windmill:
- Go to the script editor → **Settings** → **Timeout** → set to `60` seconds or more.

---

## Next Steps

- **Iterate on the decoder**: Have external developers build their C++ images and push them to your registry.
- **Add approval gates**: Use Windmill's **Flows** feature to insert a manual approval step between form submission and K8s deployment.
- **Auto-cleanup**: Schedule a Windmill script that deletes stale decoder Deployments after 30 days of inactivity.
- **Metrics**: Export Prometheus metrics from the sidecars and RabbitMQ to Grafana for pipeline observability.
