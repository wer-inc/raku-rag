"""Unit contract for the SQS queue adapter without requiring boto3/LocalStack."""

from __future__ import annotations

import json
import unittest

from raku_rag.workers.queue.sqs import SqsTaskQueue


class FakeSqsClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.deleted: list[dict] = []
        self.visibility: list[dict] = []
        self.messages: list[dict] = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m1"}

    def receive_message(self, **kwargs):
        return {"Messages": list(self.messages)}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)

    def change_message_visibility(self, **kwargs):
        self.visibility.append(kwargs)


class TestSqsTaskQueue(unittest.TestCase):
    def test_send_receive_ack_and_fail(self) -> None:
        client = FakeSqsClient()
        queue = SqsTaskQueue("http://sqs/raku-ingest", client=client)

        message_id = queue.enqueue_message({"tenant_id": "t", "document_id": "d"})
        self.assertEqual(message_id, "m1")
        self.assertEqual(json.loads(client.sent[0]["MessageBody"])["document_id"], "d")

        client.messages = [
            {
                "MessageId": "m2",
                "ReceiptHandle": "rh2",
                "Body": json.dumps({"idempotency_key": "k"}),
                "Attributes": {"ApproximateReceiveCount": "3"},
            }
        ]
        envelope = queue.receive()[0]
        self.assertEqual(envelope.message_id, "m2")
        self.assertEqual(envelope.receive_count, 3)
        self.assertEqual(envelope.body["idempotency_key"], "k")

        queue.ack(envelope)
        self.assertEqual(client.deleted[0]["ReceiptHandle"], "rh2")

        moved = queue.fail(envelope, "retry")
        self.assertFalse(moved)
        self.assertEqual(client.visibility[0]["VisibilityTimeout"], 5)


if __name__ == "__main__":
    unittest.main()
