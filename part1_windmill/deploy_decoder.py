#!/usr/bin/env python3
"""
Windmill Backend Script: deploy_decoder_k8s
=====================================================
Triggered by the "Developer Onboarding Portal" UI form submission.
Uses the kubernetes Python client to dynamically create a Deployment
manifest containing the developer's custom decoder container and the
platform-managed AMQP sidecar container.

Arguments (mapped from Windmill UI form fields):
    developer_name (str): Human-readable developer identifier.
    protocol_fingerprint (str): Hex protocol fingerprint (e.g., "0x8100").
    runtime_language (str): Programming runtime (e.g., "C++").
    docker_image_uri (str): Fully-qualified image URI for the decoder container.
    target_queue (str): RabbitMQ queue this decoder will consume from.
"""

import os
import re
import hashlib
from typing import Dict, Any, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException


def sanitize_name(input_str: str) -> str:
    """
    Sanitize a string to be a valid Kubernetes resource name segment.
    Converts to lowercase, replaces invalid characters with hyphens,
    and truncates to 50 characters.
    """
    sanitized = re.sub(r"[^a-z0-9-]", "-", input_str.lower())
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    return sanitized[:50]


def generate_deployment_name(developer_name: str, fingerprint: str) -> str:
    """
    Generate a unique, deterministic Deployment name.
    Format: decoder-{developer}-{fingerprint-hash}-{random-suffix}
    """
    dev_part = sanitize_name(developer_name)
    # Use first 6 chars of SHA256(fingerprint) for uniqueness
    fp_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:6]
    base = f"decoder-{dev_part}-{fp_hash}"
    # Ensure total length <= 63 (K8s limit for names)
    if len(base) > 58:
        base = base[:58]
    return base


def build_deployment_manifest(
    deployment_name: str,
    developer_name: str,
    protocol_fingerprint: str,
    runtime_language: str,
    docker_image_uri: str,
    target_queue: str,
    namespace: str = "pelt-platform",
    sidecar_image: str = "registry.example.com/platform/sidecar:latest",
    replicas: int = 2,
) -> Dict[str, Any]:
    """
    Build a production-grade Kubernetes Deployment manifest.

    The resulting Pod contains:
      1. business-logic: The developer's decoder image, exposing port 8080.
      2. sidecar: The platform-managed AMQP sidecar image.

    Both containers share the Pod's localhost network interface (127.0.0.1).
    """

    # Platform-enforced resource quotas to prevent noisy neighbors
    resource_limits = {
        "cpu": "1000m",
        "memory": "512Mi",
    }
    resource_requests = {
        "cpu": "250m",
        "memory": "128Mi",
    }

    # Standardized labels for observability and cost allocation
    labels = {
        "app": deployment_name,
        "component": "decoder",
        "developer": sanitize_name(developer_name),
        "fingerprint": protocol_fingerprint.lower().replace("0x", ""),
        "runtime": sanitize_name(runtime_language),
        "managed-by": "windmill-self-help-portal",
    }

    manifest: Dict[str, Any] = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {
                "self-help.windmill.dev/developer-name": developer_name,
                "self-help.windmill.dev/protocol-fingerprint": protocol_fingerprint,
                "self-help.windmill.dev/runtime-language": runtime_language,
                "self-help.windmill.dev/docker-image": docker_image_uri,
                "self-help.windmill.dev/target-queue": target_queue,
            },
        },
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": {
                    "app": deployment_name,
                },
            },
            "template": {
                "metadata": {
                    "labels": labels,
                    "annotations": {
                        "prometheus.io/scrape": "true",
                        "prometheus.io/port": "8080",
                        "prometheus.io/path": "/metrics",
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "business-logic",
                            "image": docker_image_uri,
                            "imagePullPolicy": "Always",
                            "ports": [
                                {
                                    "containerPort": 8080,
                                    "name": "http",
                                    "protocol": "TCP",
                                }
                            ],
                            "env": [
                                {
                                    "name": "FINGERPRINT",
                                    "value": protocol_fingerprint,
                                },
                                {
                                    "name": "RUNTIME_LANGUAGE",
                                    "value": runtime_language,
                                },
                                {
                                    "name": "DEVELOPER_NAME",
                                    "value": developer_name,
                                },
                                {
                                    "name": "DECODER_LOG_LEVEL",
                                    "value": "info",
                                },
                            ],
                            "resources": {
                                "limits": resource_limits,
                                "requests": resource_requests,
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/health",
                                    "port": 8080,
                                },
                                "initialDelaySeconds": 10,
                                "periodSeconds": 15,
                                "failureThreshold": 3,
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": "/ready",
                                    "port": 8080,
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                                "failureThreshold": 3,
                            },
                            # Security hardening
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "capabilities": {
                                    "drop": ["ALL"],
                                },
                            },
                        },
                        {
                            "name": "sidecar",
                            "image": sidecar_image,
                            "imagePullPolicy": "Always",
                            "env": [
                                {
                                    "name": "MY_QUEUE",
                                    "value": target_queue,
                                },
                                {
                                    "name": "RABBITMQ_HOST",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "rabbitmq-credentials",
                                            "key": "host",
                                        }
                                    },
                                },
                                {
                                    "name": "RABBITMQ_PORT",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "rabbitmq-credentials",
                                            "key": "port",
                                        }
                                    },
                                },
                                {
                                    "name": "RABBITMQ_USER",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "rabbitmq-credentials",
                                            "key": "username",
                                        }
                                    },
                                },
                                {
                                    "name": "RABBITMQ_PASS",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "rabbitmq-credentials",
                                            "key": "password",
                                        }
                                    },
                                },
                                {
                                    "name": "RABBITMQ_VHOST",
                                    "value": "/",
                                },
                                {
                                    "name": "SIDECAR_LOG_LEVEL",
                                    "value": "INFO",
                                },
                                {
                                    "name": "HTTP_BUSINESS_ENDPOINT",
                                    "value": "http://127.0.0.1:8080/process",
                                },
                                {
                                    "name": "POD_NAME",
                                    "valueFrom": {
                                        "fieldRef": {
                                            "fieldPath": "metadata.name",
                                        }
                                    },
                                },
                                {
                                    "name": "POD_NAMESPACE",
                                    "valueFrom": {
                                        "fieldRef": {
                                            "fieldPath": "metadata.namespace",
                                        }
                                    },
                                },
                            ],
                            "resources": {
                                "limits": {
                                    "cpu": "500m",
                                    "memory": "256Mi",
                                },
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "64Mi",
                                },
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "capabilities": {
                                    "drop": ["ALL"],
                                },
                            },
                        },
                    ],
                    "restartPolicy": "Always",
                    "terminationGracePeriodSeconds": 30,
                    # Topology spread for multi-tenancy resilience
                    "topologySpreadConstraints": [
                        {
                            "maxSkew": 1,
                            "topologyKey": "kubernetes.io/hostname",
                            "whenUnsatisfiable": "ScheduleAnyway",
                            "labelSelector": {
                                "matchLabels": {
                                    "app": deployment_name,
                                }
                            },
                        }
                    ],
                },
            },
        },
    }

    return manifest


def apply_deployment(
    manifest: Dict[str, Any], namespace: str = "pelt-platform"
) -> Optional[Dict[str, Any]]:
    """
    Apply the Deployment manifest to the cluster.
    Uses server-side apply for idempotency.
    """
    api = client.AppsV1Api()
    name = manifest["metadata"]["name"]

    try:
        response = api.create_namespaced_deployment(
            namespace=namespace,
            body=manifest,
        )
        return response.to_dict()
    except ApiException as e:
        if e.status == 409:
            # Deployment already exists; patch it
            response = api.replace_namespaced_deployment(
                name=name,
                namespace=namespace,
                body=manifest,
            )
            return response.to_dict()
        raise


def main(
    developer_name: str,
    protocol_fingerprint: str,
    runtime_language: str,
    docker_image_uri: str,
    target_queue: str = "decoder.cplusplus",
) -> Dict[str, Any]:
    """
    Main entrypoint invoked by Windmill upon form submission.
    """
    # Load in-cluster config if running inside K8s; otherwise load kubeconfig
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    deployment_name = generate_deployment_name(developer_name, protocol_fingerprint)

    # Allow override via environment variable for testing
    sidecar_image = os.environ.get(
        "PLATFORM_SIDECAR_IMAGE",
        "registry.example.com/platform/sidecar:latest",
    )
    namespace = os.environ.get("TARGET_NAMESPACE", "pelt-platform")
    replicas = int(os.environ.get("DEFAULT_REPLICAS", "2"))

    manifest = build_deployment_manifest(
        deployment_name=deployment_name,
        developer_name=developer_name,
        protocol_fingerprint=protocol_fingerprint,
        runtime_language=runtime_language,
        docker_image_uri=docker_image_uri,
        target_queue=target_queue,
        namespace=namespace,
        sidecar_image=sidecar_image,
        replicas=replicas,
    )

    result = apply_deployment(manifest, namespace=namespace)

    return {
        "status": "success",
        "deployment_name": deployment_name,
        "namespace": namespace,
        "target_queue": target_queue,
        "manifest_applied": True,
        "kubernetes_response": result,
    }


if __name__ == "__main__":
    # For local testing outside of Windmill
    import sys

    if len(sys.argv) < 5:
        print(
            "Usage: python deploy_decoder.py <developer_name> <fingerprint> <runtime> <image> [target_queue]"
        )
        sys.exit(1)

    outcome = main(
        developer_name=sys.argv[1],
        protocol_fingerprint=sys.argv[2],
        runtime_language=sys.argv[3],
        docker_image_uri=sys.argv[4],
        target_queue=sys.argv[5] if len(sys.argv) > 5 else "decoder.cplusplus",
    )
    print(outcome)
