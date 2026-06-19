#!/usr/bin/env bash
# P0-T14 — create the local dev SQS queue + DLQ on LocalStack ready (RT: LocalStack SQS queue creation).
set -euo pipefail

awslocal sqs create-queue --queue-name raku-ingest-dlq
DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url "$(awslocal sqs get-queue-url --queue-name raku-ingest-dlq --query QueueUrl --output text)" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

awslocal sqs create-queue --queue-name raku-ingest \
  --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}"

echo "created SQS queues: raku-ingest (+ raku-ingest-dlq)"
