# Full SaaS Screen GAPs

P0 output only. Do not implement backend behavior from this file directly. For every missing endpoint,
the next implementation phase must freeze a JSON schema under a screen-specific contract, use a typed
mock until the backend exists, and keep the GAP visible in `screens.manifest.json`.

## Backend Endpoint GAPs

| screen | missing API | purpose |
|---|---|---|
| `home-dashboard` | `GET /v1/manufacturing/drafts` | Review backlog summary for the SaaS home dashboard. |
| `answer-history` | `GET /v1/manufacturing/answers/history` | User/tenant-scoped answer history with filters, citations, and feedback. |
| `add-source` | `POST /v1/admin/datasources` | Create a reusable datasource/connector record before ingestion. |
| `add-source` | `POST /v1/admin/datasources/:source_id/test-connection` | Validate connector credentials/settings before enabling sync. |
| `document-list` | `GET /v1/admin/documents` | Tenant-scoped document inventory with approval, freshness, source, and ACL columns. |
| `document-detail` | `GET /v1/admin/documents/:document_id` | Document metadata/body/chunk summary for review and governance workflows. |
| `review-queue` | `GET /v1/manufacturing/drafts` | Queue of AI-authored drafts awaiting assignment/review. |
| `review-queue` | `GET /v1/admin/documents?approval_status=pending_review` | Queue of documents waiting for approval review. |
| `approval-workflow-settings` | `GET /v1/manufacturing/approval-workflow` | Read approval rules, required reviewers, and allowed state transitions. |
| `approval-workflow-settings` | `PUT /v1/manufacturing/approval-workflow` | Update approval workflow rules with auditability. |
| `quality-kpi` | `GET /v1/evaluations/runs` | List evaluation runs for quality trend and comparison views. |
| `audit-log` | `GET /v1/manufacturing/audit/events` | Paginated/filterable audit event browser separate from export. |
| `users` | `GET /v1/admin/users` | Tenant user directory. |
| `users` | `POST /v1/admin/users/invites` | Invite a user to the tenant. |
| `users` | `PATCH /v1/admin/users/:user_id` | Update user status, membership, or profile fields. |
| `users` | `DELETE /v1/admin/users/:user_id` | Deactivate/remove tenant membership. |
| `roles-groups-acl` | `GET /v1/admin/roles` | List available role definitions. |
| `roles-groups-acl` | `GET /v1/admin/groups` | List tenant groups for assignment and ACL rules. |
| `roles-groups-acl` | `PUT /v1/admin/groups/:group_id` | Update group membership/settings. |
| `integrations` | `GET /v1/admin/integrations` | List SaaS integrations beyond datasource records. |
| `integrations` | `POST /v1/admin/integrations` | Create/connect an external integration. |
| `integrations` | `PUT /v1/admin/integrations/:integration_id` | Update integration settings. |
| `integrations` | `DELETE /v1/admin/integrations/:integration_id` | Disconnect an integration. |
| `api-keys-webhooks` | `GET /v1/admin/api-keys` | List API keys without exposing secrets. |
| `api-keys-webhooks` | `POST /v1/admin/api-keys` | Create an API key and reveal the secret once. |
| `api-keys-webhooks` | `DELETE /v1/admin/api-keys/:key_id` | Revoke an API key. |
| `api-keys-webhooks` | `GET /v1/admin/webhooks` | List webhook subscriptions and delivery state. |
| `api-keys-webhooks` | `PUT /v1/admin/webhooks/:webhook_id` | Update webhook URL, status, or scopes. |
| `usage-billing` | `GET /v1/admin/usage` | Usage summary by period, tenant, feature, and quota dimension. |
| `usage-billing` | `GET /v1/admin/billing/plan` | Current billing plan and entitlement summary. |
| `usage-billing` | `GET /v1/admin/billing/invoices` | Invoice list and billing history. |

## Shared GAPs

- `GET /v1/manufacturing/drafts` is shared by `home-dashboard` and `review-queue`.
- Document list/detail endpoints are the main blocker for making approval state manageable without
  asking users to type document IDs.
- Admin user/group/role endpoints are required before RBAC-aware navigation can be product-grade.
- API key, webhook, integration, and billing endpoints should remain typed mocks until product and
  security contracts are frozen.
