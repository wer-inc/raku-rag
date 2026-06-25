import { Controller, Get } from "@nestjs/common";

const OPENAPI_DOC = {
  openapi: "3.0.3",
  info: {
    title: "raku-rag API",
    version: "0.1.0",
    description: "Production facade for the local-first RAG core.",
  },
  servers: [{ url: "/v1" }],
  components: {
    securitySchemes: {
      bearerAuth: { type: "http", scheme: "bearer" },
      userToken: { type: "apiKey", in: "header", name: "X-User-Token" },
    },
    headers: {
      ApiVersion: {
        description: "API major version that served the response.",
        schema: { type: "string", enum: ["1"] },
      },
      Deprecation: {
        description: "Present when the served API version is deprecated.",
        schema: { type: "string" },
      },
      Sunset: {
        description: "Present with Deprecation when a deprecated API version has a scheduled sunset.",
        schema: { type: "string" },
      },
    },
    schemas: {
      Principal: {
        type: "object",
        required: ["tenant_id", "user_id", "groups", "roles"],
        properties: {
          tenant_id: { type: "string" },
          user_id: { type: "string" },
          groups: { type: "array", items: { type: "string" } },
          roles: { type: "array", items: { type: "string" } },
        },
      },
      AnswerRequest: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          collection_id: { type: "string" },
        },
      },
      SearchRequest: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          collection_id: { type: "string" },
          top_k: { type: "number" },
        },
      },
      IngestRequest: {
        type: "object",
        required: ["collection_id", "source_id", "document_id", "ref"],
        properties: {
          collection_id: { type: "string" },
          source_id: { type: "string" },
          document_id: { type: "string" },
          ref: { type: "string" },
          content_type: { type: "string" },
        },
      },
      IngestResponse: {
        type: "object",
        required: ["ingestion_run_id", "document_id", "status", "status_url"],
        properties: {
          ingestion_run_id: { type: "string" },
          document_id: { type: "string" },
          status: {
            type: "string",
            enum: [
              "queued",
              "running",
              "succeeded",
              "failed",
              "canceled",
              "partially_succeeded",
              "dead_letter",
            ],
          },
          status_url: { type: "string" },
          failure_reason: { type: "string" },
          chunk_count: { type: "number" },
        },
      },
      AdminSourceSyncResponse: {
        type: "object",
        required: [
          "source_id",
          "collection_id",
          "status",
          "ingestion_run_id",
          "status_url",
          "observed_count",
          "changed_count",
          "failed_count",
          "runs",
        ],
        properties: {
          source_id: { type: "string" },
          collection_id: { type: "string" },
          status: { type: "string", enum: ["queued", "syncing", "succeeded", "failed", "partially_succeeded"] },
          ingestion_run_id: { type: "string" },
          sync_run_id: { type: "string" },
          queued: { type: "boolean" },
          sqs_message_id: { type: "string" },
          status_url: { type: "string" },
          observed_count: { type: "number" },
          changed_count: { type: "number" },
          failed_count: { type: "number" },
          runs: { type: "array", items: { $ref: "#/components/schemas/IngestResponse" } },
        },
      },
      AdminDataSource: {
        type: "object",
        required: ["source_id", "tenant_id", "collection_id", "type", "config", "status"],
        properties: {
          source_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string" },
          type: { type: "string", enum: ["upload", "object_storage", "confluence", "database", "notion", "box", "google_drive"] },
          config: { type: "object" },
          sync_schedule: { type: "string", nullable: true },
          last_synced_at: { type: "string", nullable: true },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          provider_config_audit_event_id: { type: "string" },
          audit_events: { type: "array", items: { $ref: "#/components/schemas/ProviderConfigAuditEvent" } },
        },
      },
      DataSourceUpsertRequest: {
        type: "object",
        required: ["collection_id", "type"],
        properties: {
          collection_id: { type: "string" },
          type: { type: "string", enum: ["upload", "object_storage", "confluence", "database", "notion", "box", "google_drive"] },
          config: { type: "object" },
          credentials: { type: "object", description: "Write-only datasource credentials." },
          sync_schedule: { type: "string", nullable: true },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          reason: { type: "string" },
        },
      },
      QueryProfileSettings: {
        type: "object",
        required: ["profile_id", "tenant_id", "score_threshold", "top_k", "minimum_evidence_count"],
        properties: {
          profile_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string", nullable: true },
          score_threshold: { type: "number" },
          top_k: { type: "number" },
          minimum_evidence_count: { type: "number" },
          rerank_enabled: { type: "boolean" },
          rerank_top_n: { type: "number" },
          max_context_tokens: { type: "number" },
          max_context_chunks: { type: "number" },
          max_synchronous_llm_calls: { type: "number" },
          retrieval_profile_id: { type: "string" },
          llm_model: { type: "string" },
          captioning_enabled: { type: "boolean" },
          captioning_budget_limit: { type: "number", nullable: true },
          profile_version: { type: "number" },
          schema_version: { type: "number" },
          effective_from: { type: "string", nullable: true },
          deprecated_at: { type: "string", nullable: true },
          provider_config_audit_event_id: { type: "string" },
          audit_events: { type: "array", items: { $ref: "#/components/schemas/ProviderConfigAuditEvent" } },
        },
      },
      QueryProfileUpsertRequest: {
        type: "object",
        properties: {
          collection_id: { type: "string", nullable: true },
          score_threshold: { type: "number" },
          top_k: { type: "number" },
          minimum_evidence_count: { type: "number" },
          rerank_enabled: { type: "boolean" },
          rerank_top_n: { type: "number" },
          max_context_tokens: { type: "number" },
          max_context_chunks: { type: "number" },
          max_synchronous_llm_calls: { type: "number" },
          retrieval_profile_id: { type: "string" },
          llm_model: { type: "string" },
          captioning_enabled: { type: "boolean" },
          captioning_budget_limit: { type: "number", nullable: true },
          reason: { type: "string" },
        },
      },
      ProviderPolicySettings: {
        type: "object",
        required: [
          "provider_policy_id",
          "tenant_id",
          "name",
          "status",
          "parser_mode",
          "zero_retention_required",
          "no_train_required",
          "customer_opt_in_required",
        ],
        properties: {
          provider_policy_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string", nullable: true },
          name: { type: "string" },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          parser_mode: {
            type: "string",
            enum: [
              "aws_only",
              "azure_document_intelligence_allowed",
              "google_document_ai_allowed",
              "customer_managed_parser",
              "oss_only",
            ],
          },
          allowed_parser_providers: { type: "array", items: { type: "string" } },
          allowed_ocr_providers: { type: "array", items: { type: "string" } },
          allowed_llm_providers: { type: "array", items: { type: "string" } },
          allowed_embedding_providers: { type: "array", items: { type: "string" } },
          allowed_rerank_providers: { type: "array", items: { type: "string" } },
          allowed_regions: { type: "array", items: { type: "string" } },
          provider_regions: { type: "object" },
          data_residency_requirement: { type: "string" },
          cross_cloud_processing_allowed: { type: "boolean" },
          zero_retention_required: { type: "boolean" },
          no_train_required: { type: "boolean" },
          customer_opt_in_required: { type: "boolean" },
          customer_opt_in_status: { type: "string", enum: ["pending", "granted", "revoked"] },
          provider_capability_snapshot: { type: "object" },
          fallback_policy: { type: "object" },
          audit_events: { type: "array", items: { $ref: "#/components/schemas/ProviderConfigAuditEvent" } },
          profile_version: { type: "number" },
          schema_version: { type: "number" },
          effective_from: { type: "string", nullable: true },
          deprecated_at: { type: "string", nullable: true },
          provider_config_audit_event_id: { type: "string" },
        },
      },
      ProviderPolicyUpsertRequest: {
        type: "object",
        properties: {
          collection_id: { type: "string", nullable: true },
          parser_mode: { type: "string" },
          allowed_parser_providers: { type: "array", items: { type: "string" } },
          allowed_ocr_providers: { type: "array", items: { type: "string" } },
          allowed_llm_providers: { type: "array", items: { type: "string" } },
          allowed_embedding_providers: { type: "array", items: { type: "string" } },
          allowed_rerank_providers: { type: "array", items: { type: "string" } },
          allowed_regions: { type: "array", items: { type: "string" } },
          provider_regions: { type: "object" },
          cross_cloud_processing_allowed: { type: "boolean" },
          zero_retention_required: { type: "boolean" },
          no_train_required: { type: "boolean" },
          customer_opt_in_required: { type: "boolean" },
          customer_opt_in_status: { type: "string" },
          fallback_policy: { type: "object" },
          reason: { type: "string" },
        },
      },
      ProviderPolicyValidationRequest: {
        type: "object",
        required: ["operation"],
        properties: {
          collection_id: { type: "string" },
          document_sample_refs: { type: "array", items: { type: "string" } },
          operation: { type: "string", enum: ["parse", "ocr", "embed", "rerank", "llm", "log"] },
          provider: { type: "string" },
        },
      },
      ProviderPolicyValidationResponse: {
        type: "object",
        required: ["allowed", "reasons"],
        properties: {
          allowed: { type: "boolean" },
          reasons: { type: "array", items: { type: "string" } },
          required_opt_in: { type: "boolean" },
          effective_provider: { type: "string" },
          fallback_provider: { type: "string" },
        },
      },
      RetrievalProfileSettings: {
        type: "object",
        required: [
          "retrieval_profile_id",
          "tenant_id",
          "name",
          "status",
          "metadata_filter_required",
          "identifier_match_enabled",
          "vector_search_enabled",
          "rerank_enabled",
        ],
        properties: {
          retrieval_profile_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string", nullable: true },
          name: { type: "string" },
          version: { type: "number" },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          metadata_filter_required: { type: "boolean" },
          identifier_match_enabled: { type: "boolean" },
          identifier_fields: { type: "array", items: { type: "string" } },
          keyword_match_enabled: { type: "boolean" },
          keyword_strategy: {
            type: "string",
            enum: ["postgres_fts", "pg_bigm", "pgroonga", "opensearch", "disabled"],
          },
          vector_search_enabled: { type: "boolean" },
          vector_top_k: { type: "number" },
          vector_score_threshold: { type: "number" },
          rerank_provider: { type: "string" },
          rerank_model: { type: "string" },
          rerank_candidate_limit: { type: "number" },
          final_context_limit: { type: "number" },
          max_context_tokens: { type: "number" },
          exact_candidate_limit: { type: "number" },
          hybrid_candidate_limit: { type: "number" },
          minimum_evidence_count: { type: "number" },
          fallback_behavior: {
            type: "string",
            enum: ["insufficient_evidence", "vector_only_disabled", "temporarily_unavailable"],
          },
          profile_version: { type: "number" },
          schema_version: { type: "number" },
          effective_from: { type: "string", nullable: true },
          deprecated_at: { type: "string", nullable: true },
          provider_config_audit_event_id: { type: "string" },
          audit_events: { type: "array", items: { $ref: "#/components/schemas/ProviderConfigAuditEvent" } },
        },
      },
      RetrievalProfileUpsertRequest: {
        type: "object",
        properties: {
          collection_id: { type: "string", nullable: true },
          metadata_filter_required: { type: "boolean" },
          identifier_match_enabled: { type: "boolean" },
          identifier_fields: { type: "array", items: { type: "string" } },
          keyword_strategy: { type: "string" },
          vector_top_k: { type: "number" },
          rerank_enabled: { type: "boolean" },
          rerank_candidate_limit: { type: "number" },
          final_context_limit: { type: "number" },
          max_context_tokens: { type: "number" },
          minimum_evidence_count: { type: "number" },
          reason: { type: "string" },
        },
      },
      RetrievalProfileBenchmarkRequest: {
        type: "object",
        properties: {
          eval_set_id: { type: "string" },
          industry_id: { type: "string" },
          sample_size: { type: "number" },
          compare_to_profile_id: { type: "string" },
        },
      },
      RetrievalProfileBenchmarkResponse: {
        type: "object",
        required: ["evaluation_run_id", "status_url"],
        properties: {
          evaluation_run_id: { type: "string" },
          status_url: { type: "string" },
        },
      },
      LoggingPolicySettings: {
        type: "object",
        required: [
          "logging_policy_id",
          "tenant_id",
          "raw_user_query_storage",
          "raw_retrieved_context_storage",
          "model_input_storage",
          "model_output_storage",
        ],
        properties: {
          logging_policy_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string", nullable: true },
          name: { type: "string" },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          raw_user_query_storage: { type: "string", enum: ["disabled", "redacted", "full_opt_in"] },
          raw_retrieved_context_storage: { type: "string", enum: ["disabled", "redacted", "full_opt_in"] },
          model_input_storage: { type: "string", enum: ["disabled", "redacted", "full_opt_in"] },
          model_output_storage: { type: "string", enum: ["disabled", "redacted", "full_opt_in"] },
          store_citation_ids: { type: "boolean" },
          store_chunk_ids: { type: "boolean" },
          store_prompt_template_version: { type: "boolean" },
          store_model_metadata: { type: "boolean" },
          store_latency: { type: "boolean" },
          store_cost: { type: "boolean" },
          production_sampling_rate: { type: "number" },
          high_risk_trace_policy: { type: "string" },
          pii_redaction_policy_ref: { type: "string" },
          secret_redaction_policy_ref: { type: "string" },
          retention_policy_ref: { type: "string" },
          profile_version: { type: "number" },
          schema_version: { type: "number" },
          effective_from: { type: "string", nullable: true },
          deprecated_at: { type: "string", nullable: true },
          provider_config_audit_event_id: { type: "string" },
          audit_events: { type: "array", items: { $ref: "#/components/schemas/ProviderConfigAuditEvent" } },
        },
      },
      LoggingPolicyUpsertRequest: {
        type: "object",
        properties: {
          raw_user_query_storage: { type: "string" },
          raw_retrieved_context_storage: { type: "string" },
          model_input_storage: { type: "string" },
          model_output_storage: { type: "string" },
          production_sampling_rate: { type: "number" },
          retention_policy_ref: { type: "string" },
          reason: { type: "string" },
        },
      },
      ProviderConfigAuditEvent: {
        type: "object",
        required: [
          "provider_config_audit_event_id",
          "tenant_id",
          "event_type",
          "actor",
          "redacted_before",
          "redacted_after",
          "created_at",
        ],
        properties: {
          provider_config_audit_event_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string", nullable: true },
          event_type: {
            type: "string",
            enum: [
              "provider_policy_changed",
              "retrieval_profile_changed",
              "logging_policy_changed",
              "model_changed",
              "parser_provider_changed",
              "residency_override",
              "opt_in_changed",
              "query_profile_changed",
              "data_source_changed",
              "acl_changed",
              "budget_changed",
            ],
          },
          actor: { type: "string" },
          redacted_before: { type: "object" },
          redacted_after: { type: "object" },
          reason: { type: "string" },
          approval_ref: { type: "string" },
          created_at: { type: "string" },
          correlation_id: { type: "string" },
        },
      },
      AdminACLGrant: {
        type: "object",
        required: ["grant_id", "tenant_id", "scope_type", "scope_id", "subject_type", "subject_id", "permission"],
        properties: {
          grant_id: { type: "string" },
          tenant_id: { type: "string" },
          scope_type: { type: "string", enum: ["tenant", "collection", "document"] },
          scope_id: { type: "string" },
          subject_type: { type: "string", enum: ["user", "group", "role"] },
          subject_id: { type: "string" },
          permission: { type: "string", enum: ["read"] },
          created_at: { type: "string" },
        },
      },
      ACLSettingsRequest: {
        type: "object",
        properties: {
          grants: { type: "array", items: { $ref: "#/components/schemas/AdminACLGrant" } },
          revoke_grant_ids: { type: "array", items: { type: "string" } },
          reason: { type: "string" },
        },
      },
      ACLSettingsResponse: {
        type: "object",
        required: ["grants"],
        properties: {
          grants: { type: "array", items: { $ref: "#/components/schemas/AdminACLGrant" } },
          provider_config_audit_event_id: { type: "string" },
        },
      },
      AdminBudget: {
        type: "object",
        required: ["budget_id", "tenant_id", "scope_type", "scope_id", "limit"],
        properties: {
          budget_id: { type: "string" },
          tenant_id: { type: "string" },
          scope_type: { type: "string", enum: ["tenant", "collection", "query", "job"] },
          scope_id: { type: "string" },
          limit: { type: "number", nullable: true },
          spent: { type: "number" },
          currency: { type: "string" },
          period: { type: "string", enum: ["daily", "monthly", "none"] },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          updated_at: { type: "string" },
        },
      },
      BudgetSettingsRequest: {
        type: "object",
        properties: {
          budgets: { type: "array", items: { $ref: "#/components/schemas/AdminBudget" } },
          reason: { type: "string" },
        },
      },
      BudgetSettingsResponse: {
        type: "object",
        required: ["budgets"],
        properties: {
          budgets: { type: "array", items: { $ref: "#/components/schemas/AdminBudget" } },
          provider_config_audit_event_id: { type: "string" },
        },
      },
      DeleteDocumentResponse: {
        type: "object",
        required: [
          "job_id",
          "document_id",
          "status",
          "tombstoned_chunks",
          "invalidated_cache_entries",
          "purged_chunks",
        ],
        properties: {
          job_id: { type: "string" },
          document_id: { type: "string" },
          status: { type: "string", enum: ["succeeded", "failed"] },
          tombstoned_chunks: { type: "number" },
          invalidated_cache_entries: { type: "number" },
          purged_chunks: { type: "number" },
          tombstoned_crops: { type: "number" },
          invalidated_visual_cache_entries: { type: "number" },
          tombstoned_visual_assets: { type: "number" },
          tombstoned_visual_regions: { type: "number" },
          tombstoned_visual_embeddings: { type: "number" },
        },
      },
      ReindexRequest: {
        type: "object",
        properties: {
          source_id: { type: "string" },
          document_ids: { type: "array", items: { type: "string" } },
          reason: {
            type: "string",
            enum: [
              "parser_version_change",
              "chunking_config_change",
              "embedding_model_change",
              "manual",
              "recovery",
            ],
          },
          target_parser_version: { type: "string" },
          target_chunking_config_version: { type: "string" },
          target_embedding_model_version: { type: "string" },
        },
      },
      ReindexResponse: {
        type: "object",
        required: ["reindex_plan_id", "collection_id", "status", "status_url", "affected_document_count"],
        properties: {
          reindex_plan_id: { type: "string" },
          collection_id: { type: "string" },
          source_id: { type: "string" },
          status: { type: "string", enum: ["planned", "running", "succeeded", "failed", "canceled"] },
          status_url: { type: "string" },
          affected_document_count: { type: "number" },
          dagster_backfill_id: { type: "string" },
        },
      },
      IngestionRunSummary: {
        type: "object",
        required: ["observed_count", "changed_count", "deleted_count", "skipped_count", "failed_count"],
        properties: {
          observed_count: { type: "number" },
          changed_count: { type: "number" },
          deleted_count: { type: "number" },
          skipped_count: { type: "number" },
          failed_count: { type: "number" },
        },
      },
      AdminJobSummary: {
        type: "object",
        required: ["job_id", "type", "status"],
        properties: {
          job_id: { type: "string" },
          ingestion_run_id: { type: "string" },
          type: { type: "string" },
          trigger: { type: "string" },
          status: { type: "string" },
          source_id: { type: "string" },
          document_id: { type: "string" },
          failure_reason: { type: "string" },
          retry_count: { type: "number" },
          started_at: { type: "string" },
          finished_at: { type: "string" },
          dagster_run_id: { type: "string" },
          dagster_run_url: { type: "string" },
        },
      },
      DocumentProcessingStatus: {
        type: "object",
        required: ["document_id", "parse_status", "chunk_status", "embedding_status", "index_status"],
        properties: {
          document_id: { type: "string" },
          source_document_id: { type: "string" },
          ingestion_run_id: { type: "string" },
          content_checksum: { type: "string" },
          parser_version: { type: "string" },
          chunking_config_version: { type: "string" },
          embedding_model_version: { type: "string" },
          parse_status: { type: "string" },
          chunk_status: { type: "string" },
          embedding_status: { type: "string" },
          index_status: { type: "string" },
          last_indexed_at: { type: "string" },
          last_error: { type: "string" },
          dagster_run_id: { type: "string" },
        },
      },
      SourceSyncStatus: {
        type: "object",
        required: [
          "source_id",
          "collection_id",
          "status",
          "observed_count",
          "changed_count",
          "deleted_count",
          "skipped_count",
          "failed_count",
        ],
        properties: {
          source_id: { type: "string" },
          collection_id: { type: "string" },
          status: {
            type: "string",
            enum: [
              "idle",
              "queued",
              "observing",
              "syncing",
              "succeeded",
              "partially_succeeded",
              "failed",
            ],
          },
          last_ingestion_run_id: { type: "string" },
          observed_count: { type: "number" },
          changed_count: { type: "number" },
          deleted_count: { type: "number" },
          skipped_count: { type: "number" },
          failed_count: { type: "number" },
          freshness: { type: "object" },
          last_error: { type: "string" },
          dagster_run_id: { type: "string" },
          dagster_run_url: { type: "string" },
        },
      },
      IngestionRunStatus: {
        type: "object",
        required: ["ingestion_run_id", "type", "trigger", "status", "summary", "documents"],
        properties: {
          ingestion_run_id: { type: "string" },
          type: { type: "string" },
          trigger: { type: "string" },
          status: { type: "string" },
          collection_id: { type: "string" },
          source_id: { type: "string" },
          document_id: { type: "string" },
          retry_count: { type: "number" },
          failure_reason: { type: "string" },
          started_at: { type: "string" },
          finished_at: { type: "string" },
          summary: { $ref: "#/components/schemas/IngestionRunSummary" },
          documents: {
            type: "array",
            items: { $ref: "#/components/schemas/DocumentProcessingStatus" },
          },
          asset_materializations: { type: "array", items: { type: "object" } },
          dagster_run_id: { type: "string" },
          dagster_run_url: { type: "string" },
          correlation_id: { type: "string" },
        },
      },
      Citation: {
        type: "object",
        properties: {
          kind: { type: "string" },
          document_id: { type: "string" },
          source_id: { type: "string" },
          version: { type: "number" },
          retrieval_score: { type: "number" },
          chunk_id: { type: "string" },
          approval_status: {
            type: "string",
            enum: ["draft", "pending_review", "approved", "obsolete"],
          },
          effective_date: { type: "string", nullable: true },
          approval_source: { type: "string", nullable: true },
        },
      },
      UsedChunk: {
        type: "object",
        required: ["chunk_id", "document_id", "retrieval_score"],
        properties: {
          chunk_id: { type: "string" },
          document_id: { type: "string" },
          retrieval_score: { type: "number" },
        },
      },
      Freshness: {
        type: "object",
        required: ["indexed_at", "document_version"],
        properties: {
          indexed_at: { type: "string", nullable: true },
          document_version: { type: "number", nullable: true },
          source_freshness: { type: "string", nullable: true },
        },
      },
      SearchResultItem: {
        type: "object",
        required: [
          "source_id",
          "document_id",
          "chunk_id",
          "version",
          "retrieval_score",
          "heading_path",
          "freshness",
        ],
        properties: {
          source_id: { type: "string" },
          document_id: { type: "string" },
          chunk_id: { type: "string" },
          version: { type: "number" },
          retrieval_score: { type: "number" },
          heading_path: { type: "array", items: { type: "string" } },
          text: { type: "string" },
          freshness: { $ref: "#/components/schemas/Freshness" },
        },
      },
      SearchResponse: {
        type: "object",
        required: ["results", "correlation_id"],
        properties: {
          results: {
            type: "array",
            items: { $ref: "#/components/schemas/SearchResultItem" },
          },
          correlation_id: { type: "string" },
        },
      },
      AnswerResponse: {
        type: "object",
        required: ["status", "citations", "used_chunks"],
        properties: {
          status: {
            type: "string",
            enum: ["ok", "insufficient_evidence", "budget_exceeded", "temporarily_unavailable"],
          },
          text: { type: "string", nullable: true },
          confidence: { type: "number", nullable: true },
          answer_template_version: { type: "string" },
          display_sections: {
            type: "array",
            items: {
              type: "object",
              required: ["id", "title"],
              properties: {
                id: { type: "string" },
                title: { type: "string" },
                text: { type: "string" },
                fields: { type: "object" },
                items: { type: "array", items: { type: "object" } },
              },
            },
          },
          citations: { type: "array", items: { $ref: "#/components/schemas/Citation" } },
          used_chunks: { type: "array", items: { $ref: "#/components/schemas/UsedChunk" } },
          correlation_id: { type: "string" },
        },
      },
      ManufacturingAnswerRequest: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          collection_id: { type: "string" },
          intent_hint: { type: "string" },
          manufacturing_filters: { type: "object" },
        },
      },
      ManufacturingSafetyExtension: {
        type: "object",
        required: ["high_risk", "high_risk_reason_codes"],
        properties: {
          high_risk: { type: "boolean" },
          high_risk_reason_codes: { type: "array", items: { type: "string" } },
          safety_block_reason: { type: "string", nullable: true },
          obsolete_warning: { type: "boolean" },
          requires_onsite_confirmation: { type: "boolean" },
          notice: { type: "string", nullable: true },
        },
      },
      ManufacturingAnswerResponse: {
        type: "object",
        required: ["status", "citations", "used_chunks", "manufacturing"],
        properties: {
          status: {
            type: "string",
            enum: ["ok", "insufficient_evidence", "budget_exceeded", "temporarily_unavailable"],
          },
          text: { type: "string", nullable: true },
          confidence: { type: "number", nullable: true },
          answer_template_version: { type: "string" },
          display_sections: {
            type: "array",
            items: {
              type: "object",
              required: ["id", "title"],
              properties: {
                id: { type: "string" },
                title: { type: "string" },
                text: { type: "string" },
                fields: { type: "object" },
                items: { type: "array", items: { type: "object" } },
              },
            },
          },
          citations: { type: "array", items: { $ref: "#/components/schemas/Citation" } },
          used_chunks: { type: "array", items: { $ref: "#/components/schemas/UsedChunk" } },
          correlation_id: { type: "string" },
          manufacturing: { $ref: "#/components/schemas/ManufacturingSafetyExtension" },
        },
      },
      ManufacturingDataUsePolicy: {
        type: "object",
        required: [
          "tenant_id",
          "no_train_default",
          "training_opt_in",
          "provider_no_train_required",
          "no_train_fallback",
          "retention_customer",
          "retention_audit",
          "export_enabled",
          "policy_version",
        ],
        properties: {
          tenant_id: { type: "string" },
          no_train_default: { type: "boolean" },
          training_opt_in: { type: "boolean" },
          opt_in_contract_ref: { type: "string", nullable: true },
          provider_no_train_required: { type: "boolean" },
          no_train_fallback: { type: "string", enum: ["block"] },
          retention_customer: { type: "number" },
          retention_audit: { type: "number" },
          export_enabled: { type: "boolean" },
          policy_version: { type: "string" },
          updated_by: { type: "string", nullable: true },
          updated_at: { type: "string", nullable: true },
        },
      },
      ManufacturingDataUsePolicyPatch: {
        type: "object",
        properties: {
          no_train_default: { type: "boolean" },
          training_opt_in: { type: "boolean" },
          opt_in_contract_ref: { type: "string" },
          provider_no_train_required: { type: "boolean" },
          no_train_fallback: { type: "string", enum: ["block"] },
          retention_customer: { type: "number" },
          retention_audit: { type: "number" },
          export_enabled: { type: "boolean" },
        },
      },
      ManufacturingGovernanceStatus: {
        type: "object",
        required: ["tenant_id", "policy_version", "no_train", "audit_coverage", "safety_gate"],
        properties: {
          tenant_id: { type: "string" },
          policy_version: { type: "string" },
          no_train: { type: "object" },
          audit_coverage: { type: "object" },
          safety_gate: { type: "object" },
          draft_review: { type: "object" },
          groundedness: { type: "object" },
          retention: { type: "object" },
          ismap_readiness_memo: { type: "string" },
        },
      },
      ManufacturingAuditExportResponse: {
        type: "object",
        required: ["format"],
        properties: {
          format: { type: "string", enum: ["dict", "jsonl", "csv"] },
          records: { type: "array", items: { type: "object" } },
          content: { type: "string" },
        },
      },
      BoundingBox: {
        type: "object",
        required: ["x", "y", "width", "height"],
        properties: {
          x: { type: "number" },
          y: { type: "number" },
          width: { type: "number" },
          height: { type: "number" },
        },
      },
      AssetRegion: {
        type: "object",
        required: ["region_id", "chunk_id", "region_type", "page_number", "bbox", "crop_uri"],
        properties: {
          region_id: { type: "string" },
          chunk_id: { type: "string" },
          region_type: { type: "string" },
          page_number: { type: "number" },
          bbox: { $ref: "#/components/schemas/BoundingBox" },
          crop_uri: { type: "string" },
          sensitive_detected: { type: "boolean" },
          sensitive_detection_labels: { type: "array", items: { type: "string" } },
          visual_region_redaction_required: { type: "boolean" },
          visual_region_redaction_status: { type: "string" },
          visual_redaction_policy_ref: { type: "string" },
        },
      },
      AssetCrop: {
        type: "object",
        required: ["crop_id", "asset_id", "region_id", "crop_uri", "bbox", "redaction_policy_ref"],
        properties: {
          crop_id: { type: "string" },
          asset_id: { type: "string" },
          region_id: { type: "string" },
          crop_uri: { type: "string" },
          bbox: { $ref: "#/components/schemas/BoundingBox" },
          redaction_policy_ref: { type: "string" },
          sensitive_detected: { type: "boolean" },
          sensitive_detection_labels: { type: "array", items: { type: "string" } },
          visual_region_redaction_required: { type: "boolean" },
          visual_region_redaction_status: { type: "string" },
        },
      },
      VisualAssetResponse: {
        type: "object",
        required: [
          "asset_id",
          "tenant_id",
          "collection_id",
          "document_id",
          "source_id",
          "version",
          "storage_uri",
          "content_type",
          "page_number",
          "regions",
          "crops",
        ],
        properties: {
          asset_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string" },
          document_id: { type: "string" },
          source_id: { type: "string" },
          version: { type: "number" },
          storage_uri: { type: "string" },
          content_type: { type: "string" },
          page_number: { type: "number" },
          regions: { type: "array", items: { $ref: "#/components/schemas/AssetRegion" } },
          crops: { type: "array", items: { $ref: "#/components/schemas/AssetCrop" } },
        },
      },
      EvaluationSetCreateRequest: {
        type: "object",
        required: ["items"],
        properties: {
          items: {
            type: "array",
            items: {
              type: "object",
              required: ["question", "expected_evidence"],
              properties: {
                question: { type: "string" },
                expected_answer: { type: "string" },
                expected_evidence: {
                  type: "array",
                  items: {
                    type: "object",
                    required: ["document_id"],
                    properties: {
                      document_id: { type: "string" },
                      chunk_id: { type: "string" },
                    },
                  },
                },
              },
            },
          },
        },
      },
      EvaluationSetCreateResponse: {
        type: "object",
        required: ["eval_set_id", "item_count", "status"],
        properties: {
          eval_set_id: { type: "string" },
          dataset_version: { type: "string" },
          item_count: { type: "number" },
          status: { type: "string", enum: ["created"] },
        },
      },
      EvaluationRunCreateRequest: {
        type: "object",
        required: ["eval_set_id"],
        properties: {
          eval_set_id: { type: "string" },
          baseline: { type: "boolean" },
          collection_id: { type: "string" },
        },
      },
      EvaluationRunCreateResponse: {
        type: "object",
        required: ["run_id", "status_url"],
        properties: {
          run_id: { type: "string" },
          status_url: { type: "string" },
        },
      },
      EvaluationRunStatus: {
        type: "object",
        required: ["run_id", "eval_set_id", "tenant_id", "status", "metrics", "security_checks", "gate_result"],
        properties: {
          run_id: { type: "string" },
          eval_set_id: { type: "string" },
          tenant_id: { type: "string" },
          status: { type: "string", enum: ["queued", "running", "succeeded", "failed"] },
          baseline: { type: "boolean" },
          metrics: { type: "object" },
          baseline_comparison: { type: "object" },
          security_checks: { type: "object" },
          gate_result: { type: "string", enum: ["passed", "blocked"] },
          version_registry: { type: "object" },
        },
      },
      FeedbackRequest: {
        type: "object",
        required: ["subject", "rating"],
        properties: {
          answer_id: { type: "string" },
          evaluation_run_id: { type: "string" },
          subject: { type: "string", enum: ["user", "eval_job"] },
          rating: { type: "number" },
          comment: { type: "string" },
        },
      },
      FeedbackResponse: {
        type: "object",
        required: ["feedback_id", "status"],
        properties: {
          feedback_id: { type: "string" },
          status: { type: "string", enum: ["accepted"] },
        },
      },
      IndustryListResponse: {
        type: "object",
        required: ["industries"],
        properties: {
          tenant_id: { type: "string" },
          industries: {
            type: "array",
            items: {
              type: "object",
              required: ["industry_id", "name", "status", "version"],
              properties: {
                industry_id: { type: "string" },
                name: { type: "string" },
                status: { type: "string", enum: ["active", "draft", "archived"] },
                version: { type: "number" },
              },
            },
          },
        },
      },
      IndustryProfileResponse: {
        type: "object",
        required: [
          "industry_id",
          "version",
          "document_types",
          "metadata_schema",
          "workflows",
          "draft_artifact_types",
          "kpis",
          "dashboard_widgets",
          "governance_profile",
        ],
        properties: {
          industry_id: { type: "string" },
          version: { type: "number" },
          document_types: { type: "array", items: { type: "object" } },
          metadata_schema: { type: "object" },
          workflows: { type: "array", items: { type: "object" } },
          draft_artifact_types: { type: "array", items: { type: "object" } },
          kpis: { type: "array", items: { type: "object" } },
          dashboard_widgets: { type: "array", items: { type: "object" } },
          governance_profile: { type: "object" },
        },
      },
      IndustryMetadataValidationResponse: {
        type: "object",
        required: ["industry_id", "valid", "errors"],
        properties: {
          industry_id: { type: "string" },
          schema_id: { type: "string" },
          version: { type: "number" },
          valid: { type: "boolean" },
          errors: { type: "array", items: { type: "string" } },
        },
      },
      IndustryWorkflowRunRequest: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string" },
          collection_id: { type: "string" },
          metadata: { type: "object" },
          citations: { type: "array", items: { type: "object" } },
          payload: { type: "object" },
        },
      },
      IndustryWorkflowRunResponse: {
        type: "object",
        required: ["status", "industry_id", "workflow_id"],
        properties: {
          status: { type: "string" },
          text: { type: "string" },
          industry_id: { type: "string" },
          workflow_id: { type: "string" },
          review_required: { type: "boolean" },
          blocked: { type: "boolean" },
          risk_decision: { type: "object" },
          evidence_decision: { type: "object" },
          citations: { type: "array", items: { type: "object" } },
          draft_artifact: { type: "object", nullable: true },
          audit_events: { type: "array", items: { type: "object" } },
          cost_events: { type: "array", items: { type: "object" } },
        },
      },
      IndustryDraftResponse: {
        type: "object",
        properties: {
          draft: { type: "object" },
          audit_events: { type: "array", items: { type: "object" } },
        },
      },
      IndustryDashboardResponse: {
        type: "object",
        required: ["tenant_id", "industry_id", "widgets", "kpis", "denied_widget_ids"],
        properties: {
          tenant_id: { type: "string" },
          industry_id: { type: "string" },
          widgets: { type: "array", items: { type: "object" } },
          kpis: { type: "array", items: { type: "object" } },
          denied_widget_ids: { type: "array", items: { type: "string" } },
        },
      },
      IndustryKpiResponse: {
        type: "object",
        required: ["tenant_id", "industry_id", "kpis"],
        properties: {
          tenant_id: { type: "string" },
          industry_id: { type: "string" },
          kpis: { type: "array", items: { type: "object" } },
        },
      },
      IndustryGovernanceStatus: {
        type: "object",
        required: ["industry_id", "status", "no_train_enforced", "audit_ready", "provider_ready"],
        properties: {
          industry_id: { type: "string" },
          status: { type: "string", enum: ["ready", "action_required"] },
          no_train_enforced: { type: "boolean" },
          audit_ready: { type: "boolean" },
          provider_ready: { type: "boolean" },
          retention_ready: { type: "boolean" },
          facts: { type: "object" },
        },
      },
      RealEstateMetadataImportResponse: {
        type: "object",
        required: ["import_run_id", "accepted_count", "rejected_count", "status_url"],
        properties: {
          import_run_id: { type: "string" },
          accepted_count: { type: "number" },
          rejected_count: { type: "number" },
          status_url: { type: "string" },
          errors: { type: "array", items: { type: "object" } },
        },
      },
      RealEstateDocumentEnrichmentResponse: {
        type: "object",
        required: ["document_id", "real_estate_metadata", "warnings"],
        properties: {
          document_id: { type: "string" },
          real_estate_metadata: { type: "object" },
          warnings: { type: "array", items: { type: "string" } },
          validation: { type: "object" },
        },
      },
      RealEstateWorkflowResponse: {
        type: "object",
        required: ["status"],
        properties: {
          status: { type: "string" },
          answer: { type: "string" },
          summary: { type: "string" },
          citations: { type: "array", items: { type: "object" } },
          risk_decision: { type: "object" },
          gate_decision: { type: "object" },
          review_required: { type: "boolean" },
          warnings: { type: "array", items: { type: "string" } },
          similar_cases: { type: "array", items: { type: "object" } },
        },
      },
      RealEstateDraftResponse: {
        type: "object",
        required: ["artifact_id", "artifact_type", "status"],
        properties: {
          artifact_id: { type: "string" },
          artifact_type: { type: "string" },
          status: { type: "string" },
          payload: { type: "object" },
          source_citations: { type: "array", items: { type: "object" } },
          review_state: { type: "object" },
          audit_log_ref: { type: "string" },
        },
      },
      RealEstateDashboardResponse: {
        type: "object",
        required: ["widgets", "warnings"],
        properties: {
          widgets: { type: "array", items: { type: "object" } },
          warnings: { type: "array", items: { type: "string" } },
        },
      },
      RealEstateGovernanceStatus: {
        type: "object",
        required: ["no_train", "audit_coverage", "risk_gate", "draft_review", "poc_readiness"],
        properties: {
          no_train: { type: "object" },
          audit_coverage: { type: "object" },
          risk_gate: { type: "object" },
          draft_review: { type: "object" },
          personal_data_redaction: { type: "object" },
          provider_governance: { type: "object" },
          ismap_readiness_memo: { type: "string" },
          poc_readiness: { type: "string" },
        },
      },
      InvestmentMetadataImportResponse: {
        type: "object",
        required: ["import_run_id", "accepted_count", "rejected_count", "status_url"],
        properties: {
          import_run_id: { type: "string" },
          accepted_count: { type: "number" },
          rejected_count: { type: "number" },
          status_url: { type: "string" },
          errors: { type: "array", items: { type: "object" } },
        },
      },
      InvestmentDocumentEnrichmentResponse: {
        type: "object",
        required: ["document_id", "investment_metadata", "normalized_aliases", "warnings"],
        properties: {
          document_id: { type: "string" },
          investment_metadata: { type: "object" },
          normalized_aliases: { type: "object" },
          warnings: { type: "array", items: { type: "string" } },
          validation: { type: "object" },
        },
      },
      InvestmentWorkflowResponse: {
        type: "object",
        required: ["status"],
        properties: {
          status: { type: "string" },
          answer: { type: "string" },
          citations: { type: "array", items: { type: "object" } },
          risk_decision: { type: "object" },
          gate_decision: { type: "object" },
          review_required: { type: "boolean" },
          warnings: { type: "array", items: { type: "string" } },
        },
      },
      InvestmentDraftResponse: {
        type: "object",
        required: ["artifact_id", "artifact_type", "status", "compliance_review_status"],
        properties: {
          artifact_id: { type: "string" },
          artifact_type: { type: "string" },
          status: { type: "string" },
          compliance_review_status: { type: "string" },
          payload: { type: "object" },
          source_citations: { type: "array", items: { type: "object" } },
          disclosure_evidence_ids: { type: "array", items: { type: "string" } },
          contradiction_results: { type: "array", items: { type: "object" } },
          audit_log_ref: { type: "string" },
        },
      },
      InvestmentDashboardResponse: {
        type: "object",
        required: ["widgets", "warnings"],
        properties: {
          widgets: { type: "array", items: { type: "object" } },
          warnings: { type: "array", items: { type: "string" } },
        },
      },
      InvestmentGovernanceStatus: {
        type: "object",
        required: [
          "no_train",
          "audit_coverage",
          "advice_boundary",
          "regulated_activity",
          "disclosure_evidence",
          "compliance_review",
          "poc_readiness",
        ],
        properties: {
          no_train: { type: "object" },
          audit_coverage: { type: "object" },
          advice_boundary: { type: "object" },
          regulated_activity: { type: "object" },
          disclosure_evidence: { type: "object" },
          compliance_review: { type: "object" },
          record_retention: { type: "object" },
          provider_governance: { type: "object" },
          financial_ai_governance_notes: { type: "string" },
          poc_readiness: { type: "string" },
        },
      },
      ErrorResponse: {
        type: "object",
        properties: {
          statusCode: { type: "number" },
          message: { type: "string" },
          error: { type: "string" },
        },
      },
    },
  },
  paths: {
    "/health": {
      get: {
        operationId: "getHealth",
        security: [],
        responses: {
          "200": {
            description: "API health",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  required: ["status", "service"],
                  properties: {
                    status: { type: "string", enum: ["ok"] },
                    service: { type: "string" },
                    phase: { type: "number" },
                  },
                },
              },
            },
          },
        },
      },
    },
    "/whoami": {
      get: {
        operationId: "getWhoami",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Authenticated principal",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    principal: { $ref: "#/components/schemas/Principal" },
                  },
                },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
        },
      },
    },
    "/answer": {
      post: {
        operationId: "postAnswer",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/AnswerRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Grounded answer or insufficient evidence response",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/AnswerResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": {
            description: "Answer service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/manufacturing/answer": {
      post: {
        operationId: "postManufacturingAnswer",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ManufacturingAnswerRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Manufacturing safety-gated grounded answer",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ManufacturingAnswerResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Answer service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/manufacturing/policy/data-use": {
      get: {
        operationId: "getManufacturingDataUsePolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Tenant manufacturing DataUsePolicy",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ManufacturingDataUsePolicy" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Answer service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putManufacturingDataUsePolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ManufacturingDataUsePolicyPatch" } },
          },
        },
        responses: {
          "200": {
            description: "Updated tenant manufacturing DataUsePolicy",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ManufacturingDataUsePolicy" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Answer service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/manufacturing/governance/status": {
      get: {
        operationId: "getManufacturingGovernanceStatus",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Manufacturing governance readiness status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ManufacturingGovernanceStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Answer service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/manufacturing/audit/export": {
      get: {
        operationId: "getManufacturingAuditExport",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "fmt", in: "query", required: false, schema: { type: "string", enum: ["dict", "jsonl", "csv"] } }],
        responses: {
          "200": {
            description: "Tenant-scoped manufacturing audit export",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ManufacturingAuditExportResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Answer service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/search": {
      post: {
        operationId: "postSearch",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/SearchRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Search results over authorized chunks",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/SearchResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": {
            description: "Search service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/assets/{asset_id}": {
      get: {
        operationId: "getVisualAsset",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "asset_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        responses: {
          "200": {
            description: "Authorized visual asset regions and crops",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/VisualAssetResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": {
            description: "Asset not found, unauthorized, or deleted",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
          "502": {
            description: "Asset service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/ingest": {
      post: {
        operationId: "postIngest",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/IngestRequest" } },
          },
        },
        responses: {
          "202": {
            description: "Ingestion accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IngestResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/jobs": {
      get: {
        operationId: "getAdminJobs",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "status",
            in: "query",
            required: false,
            schema: { type: "string" },
          },
          {
            name: "source_id",
            in: "query",
            required: false,
            schema: { type: "string" },
          },
        ],
        responses: {
          "200": {
            description: "Admin job summaries",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  required: ["jobs"],
                  properties: {
                    jobs: {
                      type: "array",
                      items: { $ref: "#/components/schemas/AdminJobSummary" },
                    },
                  },
                },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/sources/{source_id}/sync-status": {
      get: {
        operationId: "getSourceSyncStatus",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "source_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        responses: {
          "200": {
            description: "Source sync status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/SourceSyncStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/sources/{source_id}/test-connection": {
      post: {
        operationId: "testAdminSourceConnection",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "source_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        requestBody: {
          required: false,
          content: {
            "application/json": {
              schema: {
                type: "object",
                properties: {
                  collection_id: { type: "string" },
                  limit: { type: "number" },
                },
              },
            },
          },
        },
        responses: {
          "200": {
            description: "Datasource connection test result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    ok: { type: "boolean" },
                    source_id: { type: "string" },
                    sample_count: { type: "number" },
                    error: { type: "string" },
                  },
                },
              },
            },
          },
          "400": { description: "Connection test failed", content: { "application/json": {} } },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/sources/{source_id}/sync": {
      post: {
        operationId: "syncAdminSource",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "source_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        requestBody: {
          required: false,
          content: {
            "application/json": {
              schema: {
                type: "object",
                properties: {
                  collection_id: { type: "string" },
                  limit: { type: "number" },
                  manufacturing: { type: "object" },
                },
              },
            },
          },
        },
        responses: {
          "202": {
            description: "Datasource sync accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/AdminSourceSyncResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/ingestion-runs/{ingestion_run_id}": {
      get: {
        operationId: "getIngestionRun",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "ingestion_run_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        responses: {
          "200": {
            description: "Ingestion run detail",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IngestionRunStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/ingestion-runs/{ingestion_run_id}/retry": {
      post: {
        operationId: "retryIngestionRun",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "ingestion_run_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        responses: {
          "202": {
            description: "Ingestion retry accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IngestResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/documents/{document_id}/processing-status": {
      get: {
        operationId: "getDocumentProcessingStatus",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "document_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        responses: {
          "200": {
            description: "Document processing status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DocumentProcessingStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Ingestion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/documents/{document_id}": {
      delete: {
        operationId: "deleteDocument",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          {
            name: "document_id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
        ],
        responses: {
          "202": {
            description: "Document tombstoned and deletion cascade accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/DeleteDocumentResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": {
            description: "Deletion service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/collections/{collection_id}/reindex": {
      post: {
        operationId: "reindexCollection",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ReindexRequest" } },
          },
        },
        responses: {
          "202": {
            description: "Collection reindex plan accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ReindexResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": {
            description: "Reindex service unavailable",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ErrorResponse" } },
            },
          },
        },
      },
    },
    "/admin/datasources": {
      get: {
        operationId: "listAdminDataSources",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Tenant data sources",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/AdminDataSource" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/datasources/{source_id}": {
      get: {
        operationId: "getAdminDataSource",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "source_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Data source settings",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/AdminDataSource" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putAdminDataSource",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "source_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/DataSourceUpsertRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Data source settings saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/AdminDataSource" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/query-profiles": {
      get: {
        operationId: "listQueryProfiles",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Query profiles",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/QueryProfileSettings" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/query-profiles/{profile_id}": {
      get: {
        operationId: "getQueryProfile",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "profile_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Query profile settings",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/QueryProfileSettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putQueryProfile",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "profile_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/QueryProfileUpsertRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Query profile saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/QueryProfileSettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/provider-policies": {
      get: {
        operationId: "listProviderPolicies",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Provider policies",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/ProviderPolicySettings" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/provider-policies/{provider_policy_id}": {
      get: {
        operationId: "getProviderPolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "provider_policy_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Provider policy detail",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ProviderPolicySettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putProviderPolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "provider_policy_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ProviderPolicyUpsertRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Provider policy saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ProviderPolicySettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/provider-policies/{provider_policy_id}/validate": {
      post: {
        operationId: "validateProviderPolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "provider_policy_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ProviderPolicyValidationRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Provider policy validation result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ProviderPolicyValidationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/retrieval-profiles": {
      get: {
        operationId: "listRetrievalProfiles",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Retrieval profiles",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/RetrievalProfileSettings" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/retrieval-profiles/{retrieval_profile_id}": {
      get: {
        operationId: "getRetrievalProfile",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "retrieval_profile_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Retrieval profile detail",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RetrievalProfileSettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putRetrievalProfile",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "retrieval_profile_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/RetrievalProfileUpsertRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Retrieval profile saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RetrievalProfileSettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/retrieval-profiles/{retrieval_profile_id}/benchmark": {
      post: {
        operationId: "benchmarkRetrievalProfile",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "retrieval_profile_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/RetrievalProfileBenchmarkRequest" } },
          },
        },
        responses: {
          "202": {
            description: "Retrieval benchmark accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RetrievalProfileBenchmarkResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/logging-policies": {
      get: {
        operationId: "listLoggingPolicies",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Logging policies",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/LoggingPolicySettings" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/logging-policies/{logging_policy_id}": {
      get: {
        operationId: "getLoggingPolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "logging_policy_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Logging policy detail",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/LoggingPolicySettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putLoggingPolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "logging_policy_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/LoggingPolicyUpsertRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Logging policy saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/LoggingPolicySettings" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/provider-config-audit-events": {
      get: {
        operationId: "listProviderConfigAuditEvents",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "event_type", in: "query", required: false, schema: { type: "string" } },
          { name: "correlation_id", in: "query", required: false, schema: { type: "string" } },
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Provider configuration audit events",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/ProviderConfigAuditEvent" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/acl": {
      get: {
        operationId: "getAdminAcl",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "ACL grants",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ACLSettingsResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putAdminAcl",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ACLSettingsRequest" } },
          },
        },
        responses: {
          "200": {
            description: "ACL grants saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ACLSettingsResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/admin/budgets": {
      get: {
        operationId: "getAdminBudgets",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scope_type", in: "query", required: false, schema: { type: "string" } },
          { name: "scope_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Budget settings",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { type: "array", items: { $ref: "#/components/schemas/AdminBudget" } },
              },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
      put: {
        operationId: "putAdminBudgets",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/BudgetSettingsRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Budget settings saved",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/BudgetSettingsResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Settings service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/evaluations/sets": {
      post: {
        operationId: "createEvaluationSet",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/EvaluationSetCreateRequest" } },
          },
        },
        responses: {
          "201": {
            description: "Evaluation set created",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/EvaluationSetCreateResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Evaluation service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/evaluations/runs": {
      post: {
        operationId: "createEvaluationRun",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/EvaluationRunCreateRequest" } },
          },
        },
        responses: {
          "202": {
            description: "Evaluation run accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/EvaluationRunCreateResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Evaluation service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/evaluations/runs/{run_id}": {
      get: {
        operationId: "getEvaluationRun",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "run_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Evaluation run status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/EvaluationRunStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Evaluation service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/feedback": {
      post: {
        operationId: "createFeedback",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/FeedbackRequest" } },
          },
        },
        responses: {
          "202": {
            description: "Feedback accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/FeedbackResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Feedback service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries": {
      get: {
        operationId: "listIndustries",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Tenant-visible industry profiles",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryListResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/profile": {
      get: {
        operationId: "getIndustryProfile",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "industry_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Industry profile contract",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryProfileResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/metadata/validate": {
      post: {
        operationId: "validateIndustryMetadata",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "industry_id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Metadata validation result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryMetadataValidationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/documents/enrich": {
      post: {
        operationId: "enrichIndustryDocument",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "industry_id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Industry-enriched document metadata",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { type: "object" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/workflows/{workflow_id}/run": {
      post: {
        operationId: "runIndustryWorkflow",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "industry_id", in: "path", required: true, schema: { type: "string" } },
          { name: "workflow_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/IndustryWorkflowRunRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Workflow execution result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryWorkflowRunResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/drafts/{artifact_type}": {
      post: {
        operationId: "createIndustryDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "industry_id", in: "path", required: true, schema: { type: "string" } },
          { name: "artifact_type", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Draft artifact created",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/drafts/{artifact_id}": {
      get: {
        operationId: "getIndustryDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "industry_id", in: "path", required: true, schema: { type: "string" } },
          { name: "artifact_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Draft artifact",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { type: "object" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/drafts/{artifact_id}/review": {
      post: {
        operationId: "reviewIndustryDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "industry_id", in: "path", required: true, schema: { type: "string" } },
          { name: "artifact_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Draft review transition result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/dashboard": {
      get: {
        operationId: "getIndustryDashboard",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "industry_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Industry dashboard",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryKpiResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/kpi": {
      get: {
        operationId: "getIndustryKpi",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "industry_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Industry KPI values",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryDashboardResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/industries/{industry_id}/governance/status": {
      get: {
        operationId: "getIndustryGovernanceStatus",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "industry_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Industry governance status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/IndustryGovernanceStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Industry service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/metadata/import": {
      post: {
        operationId: "importRealEstateMetadata",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "202": {
            description: "Real estate metadata import accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateMetadataImportResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/documents/enrich": {
      post: {
        operationId: "enrichRealEstateDocument",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Real estate metadata enrichment",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDocumentEnrichmentResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/properties/{property_id}/knowledge": {
      get: {
        operationId: "getRealEstatePropertyKnowledge",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "property_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Property-scoped knowledge view",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/units/{unit_id}/knowledge": {
      get: {
        operationId: "getRealEstateUnitKnowledge",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "unit_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Unit-scoped knowledge view",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/workflows/contract-question": {
      post: {
        operationId: "runRealEstateContractQuestion",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Contract question answer",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateWorkflowResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/workflows/repair-investigation": {
      post: {
        operationId: "runRealEstateRepairInvestigation",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Repair investigation result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateWorkflowResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/workflows/occupant-reply-draft": {
      post: {
        operationId: "createRealEstateOccupantReplyDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Occupant reply draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/workflows/owner-report-draft": {
      post: {
        operationId: "createRealEstateOwnerReportDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Owner report draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/workflows/move-out-checklist-draft": {
      post: {
        operationId: "createRealEstateMoveOutChecklistDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Move-out checklist draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/workflows/restoration-explanation-draft": {
      post: {
        operationId: "createRealEstateRestorationExplanationDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Restoration explanation draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/drafts/{artifact_id}": {
      get: {
        operationId: "getRealEstateDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "artifact_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Real estate draft artifact",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/drafts/{artifact_id}/review": {
      post: {
        operationId: "reviewRealEstateDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "artifact_id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Draft review transition result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/dashboard": {
      get: {
        operationId: "getRealEstateDashboard",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Real estate dashboard",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateDashboardResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/kpi": {
      get: {
        operationId: "getRealEstateKpi",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Real estate KPI",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/audit": {
      get: {
        operationId: "getRealEstateAudit",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Real estate audit events",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/real-estate/governance/status": {
      get: {
        operationId: "getRealEstateGovernanceStatus",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Real estate governance status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/RealEstateGovernanceStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Real estate service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/metadata/import": {
      post: {
        operationId: "importInvestmentMetadata",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "202": {
            description: "Investment metadata import accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentMetadataImportResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/documents/enrich": {
      post: {
        operationId: "enrichInvestmentDocument",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Investment metadata enrichment",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDocumentEnrichmentResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/funds/{fund_id}/knowledge": {
      get: {
        operationId: "getInvestmentFundKnowledge",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "fund_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Fund-scoped knowledge view",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/fund-question": {
      post: {
        operationId: "runInvestmentFundQuestion",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Fund question answer",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentWorkflowResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/rfp-response-draft": {
      post: {
        operationId: "createInvestmentRfpResponseDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "RFP response draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/ddq-response-draft": {
      post: {
        operationId: "createInvestmentDdqResponseDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "DDQ response draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/inquiry-reply-draft": {
      post: {
        operationId: "createInvestmentInquiryReplyDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Inquiry reply draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/marketing-material-check": {
      post: {
        operationId: "runInvestmentMarketingMaterialCheck",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Marketing material check result",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/monthly-commentary-draft": {
      post: {
        operationId: "createInvestmentMonthlyCommentaryDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "201": {
            description: "Monthly commentary draft",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/workflows/compliance-rule-question": {
      post: {
        operationId: "runInvestmentComplianceRuleQuestion",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Compliance rule question answer",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentWorkflowResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/drafts/{artifact_id}": {
      get: {
        operationId: "getInvestmentDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "artifact_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Investment draft artifact",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDraftResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/drafts/{artifact_id}/review": {
      post: {
        operationId: "reviewInvestmentDraft",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "artifact_id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Investment draft review transition",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/drafts/{artifact_id}/compliance-review": {
      post: {
        operationId: "reviewInvestmentDraftCompliance",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "artifact_id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: { required: true, content: { "application/json": { schema: { type: "object" } } } },
        responses: {
          "200": {
            description: "Investment compliance review transition",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/disclosure-evidence/{artifact_id}": {
      get: {
        operationId: "getInvestmentDisclosureEvidence",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [{ name: "artifact_id", in: "path", required: true, schema: { type: "string" } }],
        responses: {
          "200": {
            description: "Investment disclosure evidence",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Not found", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/dashboard": {
      get: {
        operationId: "getInvestmentDashboard",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Investment dashboard",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentDashboardResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/kpi": {
      get: {
        operationId: "getInvestmentKpi",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Investment KPI",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/audit": {
      get: {
        operationId: "getInvestmentAudit",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Investment audit events",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: { "application/json": { schema: { type: "object" } } },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/investment/governance/status": {
      get: {
        operationId: "getInvestmentGovernanceStatus",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Investment governance status",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/InvestmentGovernanceStatus" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Investment service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/openapi.json": {
      get: {
        operationId: "getOpenApi",
        security: [],
        responses: {
          "200": {
            description: "OpenAPI document",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
          },
        },
      },
    },
  },
} as const;

@Controller({ path: "openapi.json", version: "1" })
export class OpenApiController {
  @Get()
  openapi() {
    return OPENAPI_DOC;
  }
}
