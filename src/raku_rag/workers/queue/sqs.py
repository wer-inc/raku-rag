"""SQS-backed message queue adapter.

The adapter is intentionally small and duck-typed: tests can pass a fake client, while production can
let it build a boto3 SQS client when ``boto3`` is installed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from raku_rag.providers.task_queue import QueueEnvelope


@dataclass
class SqsTaskQueue:
    queue_url: str
    client: object | None = None
    dead_letter_queue_url: str = ""
    max_receive_count: int = 5
    wait_time_seconds: int = 1
    visibility_timeout: int = 30
    retry_visibility_timeout: int = 5

    def __post_init__(self) -> None:
        if not self.dead_letter_queue_url:
            self.dead_letter_queue_url = os.environ.get("SQS_DLQ_URL", "")
        self.max_receive_count = int(
            os.environ.get("SQS_MAX_RECEIVE_COUNT", str(self.max_receive_count))
        )
        if self.client is None:
            try:
                import boto3  # type: ignore
            except Exception as exc:  # pragma: no cover - depends on optional prod dep
                raise RuntimeError(
                    "boto3 is required for SqsTaskQueue without an injected client"
                ) from exc
            endpoint_url = os.environ.get("SQS_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL")
            region_name = os.environ.get("AWS_REGION", "us-east-1")
            self.client = boto3.client("sqs", endpoint_url=endpoint_url, region_name=region_name)

    def enqueue_message(self, body: dict) -> str:
        assert self.client is not None
        res = self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(body))
        return str(res.get("MessageId", ""))

    def receive(self, max_messages: int = 1) -> list[QueueEnvelope]:
        assert self.client is not None
        res = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=self.wait_time_seconds,
            VisibilityTimeout=self.visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
        )
        envelopes: list[QueueEnvelope] = []
        for msg in res.get("Messages", []):
            attrs = msg.get("Attributes") or {}
            body = json.loads(msg.get("Body") or "{}")
            envelopes.append(
                QueueEnvelope(
                    message_id=str(msg.get("MessageId", "")),
                    receipt_handle=str(msg.get("ReceiptHandle", "")),
                    body=body,
                    receive_count=int(attrs.get("ApproximateReceiveCount", "1")),
                )
            )
        return envelopes

    def ack(self, envelope: QueueEnvelope) -> None:
        assert self.client is not None
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=envelope.receipt_handle)

    def fail(self, envelope: QueueEnvelope, reason: str) -> bool:
        assert self.client is not None
        if envelope.receive_count >= self.max_receive_count:
            if self.dead_letter_queue_url:
                self.client.send_message(
                    QueueUrl=self.dead_letter_queue_url,
                    MessageBody=json.dumps(envelope.body),
                    MessageAttributes={
                        "OriginalMessageId": {
                            "DataType": "String",
                            "StringValue": envelope.message_id,
                        },
                        "FailureReason": {
                            "DataType": "String",
                            "StringValue": reason[:1024],
                        },
                    },
                )
                self.client.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=envelope.receipt_handle,
                )
            else:
                # In AWS, the queue redrive policy will move the message to its DLQ after the
                # final failed receive. Returning True keeps the app status projection in sync.
                self.client.change_message_visibility(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=envelope.receipt_handle,
                    VisibilityTimeout=self.retry_visibility_timeout,
                )
            return True
        self.client.change_message_visibility(
            QueueUrl=self.queue_url,
            ReceiptHandle=envelope.receipt_handle,
            VisibilityTimeout=self.retry_visibility_timeout,
        )
        return False

    def retry_later(
        self, envelope: QueueEnvelope, *, delay_seconds: int = 5, reason: str = ""
    ) -> None:
        assert self.client is not None
        self.client.change_message_visibility(
            QueueUrl=self.queue_url,
            ReceiptHandle=envelope.receipt_handle,
            VisibilityTimeout=max(0, int(delay_seconds or self.retry_visibility_timeout)),
        )
