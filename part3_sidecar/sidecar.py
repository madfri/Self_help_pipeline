#!/usr/bin/env python3
"""
Part 3: The High-Reliability AMQP Sidecar (sidecar.py)
======================================================
A robust, long-running Python script using `pika` to run as the infrastructure
sidecar container within a Kubernetes Pod.

Responsibilities:
  1. Consume messages from the RabbitMQ queue specified by MY_QUEUE env var.
  2. Forward the JSON envelope to the local business-logic container via HTTP.
  3. On success: pop the current queue from itinerary, route to next queue,
     and ACK the message.
  4. On failure (HTTP 500, timeout, crash): NACK with requeue=False to DLQ.
  5. Handle connection recovery, graceful shutdown, and structured logging.

Environment Variables:
  MY_QUEUE                - The RabbitMQ queue to consume from (required).
  RABBITMQ_HOST           - Broker hostname (default: localhost).
  RABBITMQ_PORT           - Broker port (default: 5672).
  RABBITMQ_USER           - Broker username (default: guest).
  RABBITMQ_PASS           - Broker password (default: guest).
  RABBITMQ_VHOST          - Virtual host (default: /).
  HTTP_BUSINESS_ENDPOINT  - URL of the decoder server (default: http://127.0.0.1:8080/process).
  SIDECAR_LOG_LEVEL       - Logging level (default: INFO).
  POD_NAME                - Pod identifier for logging (optional).
  POD_NAMESPACE           - Namespace identifier for logging (optional).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------------

SHUTDOWN_EVENT = threading.Event()

LOG_LEVEL = os.environ.get("SIDECAR_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("sidecar")

# RabbitMQ configuration
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")

MY_QUEUE = os.environ.get("MY_QUEUE", "")
if not MY_QUEUE:
    logger.error("Environment variable MY_QUEUE is not set. Exiting.")
    sys.exit(1)

# Downstream routing
COMPLETED_QUEUE = "pipeline.completed"
DLQ_QUEUE = "pipeline.dlq"

# HTTP configuration
HTTP_BUSINESS_ENDPOINT = os.environ.get(
    "HTTP_BUSINESS_ENDPOINT", "http://127.0.0.1:8080/process"
)
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30.0"))

# Pod identity for enriched logging
POD_NAME = os.environ.get("POD_NAME", "unknown-pod")
POD_NAMESPACE = os.environ.get("POD_NAMESPACE", "unknown-namespace")

# ---------------------------------------------------------------------------
# HTTP Session with Retry Logic
# ---------------------------------------------------------------------------

def create_http_session() -> requests.Session:
    """Create a resilient HTTP session for talking to the business-logic container."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=5, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


http_session = create_http_session()

# ---------------------------------------------------------------------------
# RabbitMQ Connection Factory
# ---------------------------------------------------------------------------

def create_connection() -> pika.BlockingConnection:
    """Establish a blocking connection to RabbitMQ with credentials and heartbeat."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300,
        connection_attempts=5,
        retry_delay=5,
    )
    logger.info(
        "Connecting to RabbitMQ at %s:%s (vhost=%s) for queue=%s",
        RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_VHOST, MY_QUEUE,
    )
    return pika.BlockingConnection(parameters)


def declare_infrastructure(channel: BlockingChannel) -> None:
    """
    Declare the target queue, completed queue, DLQ, and their bindings.
    Uses durable queues to survive broker restarts.
    """
    # Main pipeline queues
    queues = [MY_QUEUE, COMPLETED_QUEUE, DLQ_QUEUE]
    for queue_name in queues:
        channel.queue_declare(queue=queue_name, durable=True, auto_delete=False)
        logger.info("Queue declared: %s", queue_name)

# ---------------------------------------------------------------------------
# Core Message Processing Logic
# ---------------------------------------------------------------------------

def pop_current_itinerary(itinerary: List[str], current_queue: str) -> List[str]:
    """
    Remove the current queue from the front of the itinerary if present.
    This represents progression through the choreography.
    """
    if itinerary and itinerary[0] == current_queue:
        return itinerary[1:]
    return itinerary


def determine_next_queue(itinerary: List[str]) -> str:
    """
    Return the next queue name from the itinerary.
    If the itinerary is exhausted, route to the completion queue.
    """
    if not itinerary:
        return COMPLETED_QUEUE
    return itinerary[0]


def forward_to_business_logic(envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    POST the envelope to the local business-logic HTTP server.
    Returns the parsed JSON response on success, or raises on failure.
    """
    headers = {"Content-Type": "application/json"}
    payload = json.dumps(envelope).encode("utf-8")

    logger.info(
        "Forwarding message to business logic at %s (payload %d bytes)",
        HTTP_BUSINESS_ENDPOINT, len(payload),
    )

    response = http_session.post(
        HTTP_BUSINESS_ENDPOINT,
        data=payload,
        headers=headers,
        timeout=(5.0, HTTP_TIMEOUT_SECONDS),  # (connect timeout, read timeout)
    )

    response.raise_for_status()

    if response.status_code != 200:
        raise RuntimeError(
            f"Business logic returned unexpected status {response.status_code}: {response.text}"
        )

    parsed = response.json()
    logger.info("Business logic responded with HTTP 200")
    return parsed


def publish_to_next_queue(
    channel: BlockingChannel,
    envelope: Dict[str, Any],
    next_queue: str,
) -> None:
    """
    Publish the updated envelope to the next queue in the itinerary.
    Declares the queue durably if it does not already exist.
    Messages are persistent (delivery_mode=2).
    """
    # Defensively declare the target queue to avoid message loss
    # if the downstream sidecar has not yet started.
    channel.queue_declare(queue=next_queue, durable=True, auto_delete=False)

    body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    properties = pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,  # persistent
    )
    channel.basic_publish(
        exchange="",
        routing_key=next_queue,
        body=body,
        properties=properties,
    )
    logger.info("Published message to next queue: %s", next_queue)

# ---------------------------------------------------------------------------
# RabbitMQ Consumer Callback
# ---------------------------------------------------------------------------

def on_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> None:
    """
    Main message callback invoked by RabbitMQ.
    Orchestrates: decode -> business logic -> route -> ack/nack.
    """
    delivery_tag = method.delivery_tag
    logger.info("Received message (delivery_tag=%s, size=%d bytes)", delivery_tag, len(body))

    try:
        # 1. Parse incoming envelope
        try:
            envelope: Dict[str, Any] = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse JSON envelope: %s", exc)
            # Unparseable messages go to DLQ; do NOT requeue
            channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
            return

        # 2. Forward to business-logic container
        updated_envelope = forward_to_business_logic(envelope)

        # 3. Itinerary progression: pop current queue from itinerary
        itinerary = updated_envelope.get("itinerary", [])
        if isinstance(itinerary, list):
            updated_itinerary = pop_current_itinerary(itinerary, MY_QUEUE)
            updated_envelope["itinerary"] = updated_itinerary
            next_queue = determine_next_queue(updated_itinerary)
        else:
            logger.warning("Invalid itinerary in response; routing to DLQ")
            channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
            return

        # 4. Publish to next queue
        publish_to_next_queue(channel, updated_envelope, next_queue)

        # 5. ACK the original message
        channel.basic_ack(delivery_tag=delivery_tag)
        logger.info(
            "Message fully processed and acknowledged (next_queue=%s)", next_queue
        )

    except requests.exceptions.Timeout as exc:
        logger.error("HTTP timeout communicating with business logic: %s", exc)
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
    except requests.exceptions.ConnectionError as exc:
        logger.error("HTTP connection error to business logic: %s", exc)
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
    except requests.exceptions.HTTPError as exc:
        logger.error("Business logic returned HTTP error: %s", exc)
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
    except Exception as exc:
        logger.exception("Unhandled exception during message processing: %s", exc)
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)

# ---------------------------------------------------------------------------
# Main Loop with Connection Recovery
# ---------------------------------------------------------------------------

def run_consumer() -> None:
    """
    Long-running consumer loop with automatic connection recovery.
    Handles graceful shutdown via SIGTERM/SIGINT.
    """
    connection: Optional[pika.BlockingConnection] = None
    channel: Optional[BlockingChannel] = None

    def signal_handler(signum: int, _frame: Any) -> None:
        logger.info("Received signal %d, initiating graceful shutdown...", signum)
        SHUTDOWN_EVENT.set()
        if connection and connection.is_open:
            try:
                connection.add_callback_threadsafe(connection.close)
            except Exception:
                pass

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(
        "Sidecar starting | pod=%s/%s | queue=%s | business_endpoint=%s",
        POD_NAMESPACE, POD_NAME, MY_QUEUE, HTTP_BUSINESS_ENDPOINT,
    )

    while not SHUTDOWN_EVENT.is_set():
        try:
            connection = create_connection()
            channel = connection.channel()

            # QoS: prefetch 1 message at a time for fair work distribution
            channel.basic_qos(prefetch_count=1)

            declare_infrastructure(channel)

            channel.basic_consume(queue=MY_QUEUE, on_message_callback=on_message, auto_ack=False)
            logger.info("Consumer registered on queue '%s'. Waiting for messages...", MY_QUEUE)

            # Block and process messages until interrupted or connection drops
            channel.start_consuming()

        except pika.exceptions.ConnectionClosedByBroker as exc:
            logger.warning("Connection closed by broker: %s", exc)
            break
        except pika.exceptions.AMQPChannelError as exc:
            logger.error("AMQP channel error: %s", exc)
        except pika.exceptions.AMQPConnectionError as exc:
            logger.error("AMQP connection error: %s", exc)
        except Exception as exc:
            logger.exception("Unexpected error in consumer loop: %s", exc)
        finally:
            try:
                if channel and channel.is_open:
                    channel.stop_consuming()
                    channel.close()
            except Exception:
                pass
            try:
                if connection and connection.is_open:
                    connection.close()
            except Exception:
                pass

        if not SHUTDOWN_EVENT.is_set():
            logger.info("Reconnecting in 5 seconds...")
            time.sleep(5)

    logger.info("Sidecar shutdown complete.")


if __name__ == "__main__":
    run_consumer()
