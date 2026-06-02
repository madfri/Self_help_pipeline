#!/usr/bin/env python3
"""
Part 5: test_pipeline.py
========================
Test orchestration script for the end-to-end POC.

Modes:
  --inject-only   Publish the Initial Envelope to decoder.cplusplus.
  --verify        Consume from pipeline.completed and print the final envelope.
  (no args)       Inject, then verify with a timeout.

Environment Variables:
  RABBITMQ_HOST   - Broker hostname (default: localhost).
  RABBITMQ_PORT   - Broker port (default: 5672).
  RABBITMQ_USER   - Broker username (default: guest).
  RABBITMQ_PASS   - Broker password (default: guest).
  RABBITMQ_VHOST  - Virtual host (default: /).

Usage:
  python test_pipeline.py --inject-only
  python test_pipeline.py --verify
  python test_pipeline.py
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | test-pipeline | %(message)s",
)
logger = logging.getLogger("test-pipeline")

# ---------------------------------------------------------------------------
# RabbitMQ Connection Settings (can be overridden via environment variables)
# ---------------------------------------------------------------------------
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/")

# Queue names
QUEUE_DECODER = "decoder.cplusplus"
QUEUE_COMPLETED = "pipeline.completed"

# Initial envelope as specified in the architectural requirements
INITIAL_ENVELOPE: Dict[str, Any] = {
    "pcap_uri": "s3://packet-storage/raw/2026/06/file_123.pcap",
    "decoded_data_uri": "",
    "fingerprint": "0x8100",
    "itinerary": ["decoder.cplusplus", "enrichment.geoip", "formatter.json"],
}


def create_channel() -> BlockingChannel:
    """Create a RabbitMQ channel."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
        connection_attempts=5,
        retry_delay=2,
    )
    logger.info("Connecting to RabbitMQ at %s:%s", RABBITMQ_HOST, RABBITMQ_PORT)
    connection = pika.BlockingConnection(parameters)
    return connection.channel()


def inject_initial_envelope() -> None:
    """Publish the Initial Envelope to the decoder.cplusplus queue."""
    channel = create_channel()
    try:
        channel.queue_declare(queue=QUEUE_DECODER, durable=True, auto_delete=False)

        body = json.dumps(INITIAL_ENVELOPE, ensure_ascii=False).encode("utf-8")
        properties = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # persistent
        )
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_DECODER,
            body=body,
            properties=properties,
        )
        logger.info("Injected Initial Envelope into '%s'", QUEUE_DECODER)
        logger.info("Payload: %s", json.dumps(INITIAL_ENVELOPE, indent=2))
    finally:
        channel.close()


def verify_completion(timeout_seconds: int = 60) -> Optional[Dict[str, Any]]:
    """
    Consume from pipeline.completed and return the final envelope.
    Returns None if no message arrives within the timeout.
    """
    channel = create_channel()
    result: Optional[Dict[str, Any]] = None
    received_event = False

    def on_message(
        ch: BlockingChannel,
        method: Any,
        properties: Any,
        body: bytes,
    ) -> None:
        nonlocal result, received_event
        try:
            result = json.loads(body.decode("utf-8"))
            logger.info("Received completed message from '%s'", QUEUE_COMPLETED)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            received_event = True
        except Exception as exc:
            logger.error("Failed to process completed message: %s", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    try:
        channel.queue_declare(queue=QUEUE_COMPLETED, durable=True, auto_delete=False)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=QUEUE_COMPLETED, on_message_callback=on_message, auto_ack=False)

        logger.info("Waiting up to %d seconds for message on '%s'...", timeout_seconds, QUEUE_COMPLETED)

        start = time.time()
        while time.time() - start < timeout_seconds:
            channel.connection.process_data_events(time_limit=1)
            if received_event:
                break

        if not received_event:
            logger.warning("No message received on '%s' within timeout.", QUEUE_COMPLETED)
            return None

        return result
    finally:
        channel.close()


def print_journey(envelope: Dict[str, Any]) -> None:
    """Pretty-print the final envelope and pipeline journey summary."""
    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETION REPORT")
    print("=" * 70)
    print(json.dumps(envelope, indent=2))
    print("=" * 70)

    # Summarize what happened
    print("\nJourney Summary:")
    print(f"  Original PCAP URI:      {envelope.get('pcap_uri')}")
    print(f"  Decoded Data URI:       {envelope.get('decoded_data_uri')}")
    print(f"  Fingerprint:            {envelope.get('fingerprint')}")

    if "enrichments" in envelope:
        print(f"  Enrichments Applied:    {len(envelope['enrichments'])}")
        for e in envelope["enrichments"]:
            print(f"    - {e.get('enrichment_stage')} ({e.get('source_country')} -> {e.get('destination_country')})")
    else:
        print("  Enrichments Applied:    0")

    if "decoder_metadata" in envelope:
        dm = envelope["decoder_metadata"]
        print(f"  Decoder Runtime:        {dm.get('runtime')}")
        print(f"  Threat Detected:        {dm.get('threat_detected')}")

    if "formatter_metadata" in envelope:
        fm = envelope["formatter_metadata"]
        print(f"  Formatter Schema:       {fm.get('output_schema')}")
        print(f"  Pipeline Status:        {fm.get('stage')}")

    print(f"  Remaining Itinerary:    {envelope.get('itinerary', [])}")
    print("\n" + "=" * 70 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="POC Pipeline Test Script")
    parser.add_argument(
        "--inject-only",
        action="store_true",
        help="Only inject the initial envelope and exit.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify completion by consuming from pipeline.completed.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout in seconds for verification (default: 60).",
    )
    args = parser.parse_args()

    if args.inject_only:
        inject_initial_envelope()
        return 0

    if args.verify:
        final = verify_completion(timeout_seconds=args.timeout)
        if final:
            print_journey(final)
            return 0
        else:
            logger.error("Verification failed: no completed message found.")
            return 1

    # Default: inject then verify
    inject_initial_envelope()
    logger.info("Waiting 5 seconds for pipeline to process...")
    time.sleep(5)
    final = verify_completion(timeout_seconds=args.timeout)
    if final:
        print_journey(final)
        return 0
    else:
        logger.error("End-to-end test failed: no completed message found.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
