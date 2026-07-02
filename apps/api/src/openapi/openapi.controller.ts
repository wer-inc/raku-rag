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
          ref: {
            type: "string",
            description:
              "Connector ref. Production S3 uploads must use an allowed bucket and tenants/<tenant>/uploads/... key.",
          },
          content_type: { type: "string" },
          manufacturing: { $ref: "#/components/schemas/ManufacturingIngestMetadata" },
        },
      },
      ManufacturingIngestMetadata: {
        // Optional manufacturing approval/safety metadata forwarded verbatim to the answer-service,
        // which persists it on the Document so the safety overlay fires (mirrors dto/ingest.ts).
        type: "object",
        properties: {
          approval_status: {
            type: "string",
            enum: ["draft", "pending_review", "approved", "obsolete"],
          },
          effective_date: { type: "string", nullable: true },
          approval_source: { type: "string", enum: ["imported", "workflow"] },
          approved_by: { type: "string" },
          approved_at: { type: "string" },
          obsolete_at: { type: "string" },
          superseded_by: { type: "string" },
          document_kind: { type: "string" },
          safety_category: { type: "string" },
          quality_category: { type: "string" },
          equipment_operation_category: { type: "string" },
          hazard_tags: { type: "array", items: { type: "string" } },
          equipment_id: { type: "string" },
          process_id: { type: "string" },
          alarm_code: { type: "string" },
          defect_type: { type: "string" },
          part_no: { type: "string" },
          customer: { type: "string" },
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
      AdminDataSourceDocumentCounts: {
        type: "object",
        required: ["total", "approved", "pending_review", "draft", "obsolete", "unknown"],
        properties: {
          total: { type: "number" },
          approved: { type: "number" },
          pending_review: { type: "number" },
          draft: { type: "number" },
          obsolete: { type: "number" },
          unknown: { type: "number" },
        },
      },
      AdminDataSourceSyncOverview: {
        type: "object",
        required: ["status", "summary"],
        properties: {
          status: { type: "string" },
          summary: {
            type: "object",
            properties: {
              observed_count: { type: "number" },
              changed_count: { type: "number" },
              deleted_count: { type: "number" },
              skipped_count: { type: "number" },
              failed_count: { type: "number" },
            },
          },
          freshness: { $ref: "#/components/schemas/Freshness" },
          last_ingestion_run_id: { type: "string" },
        },
      },
      AdminDataSourceOverview: {
        type: "object",
        required: [
          "source_id",
          "tenant_id",
          "collection_id",
          "type",
          "status",
          "display_name",
          "source_type",
          "sync",
          "document_counts",
        ],
        properties: {
          source_id: { type: "string" },
          tenant_id: { type: "string" },
          collection_id: { type: "string" },
          type: { type: "string", enum: ["upload", "object_storage", "confluence", "database", "notion", "box", "google_drive"] },
          status: { type: "string", enum: ["active", "draft", "archived"] },
          display_name: { type: "string" },
          source_type: { type: "string" },
          credential_status: { type: "string" },
          approval_policy: { type: "string" },
          approval_effective_date: { type: "string", nullable: true },
          sync_schedule: { type: "string", nullable: true },
          last_synced_at: { type: "string", nullable: true },
          sync: { $ref: "#/components/schemas/AdminDataSourceSyncOverview", nullable: true },
          document_counts: { $ref: "#/components/schemas/AdminDataSourceDocumentCounts" },
        },
      },
      AdminDataSourceOverviewResponse: {
        type: "object",
        required: ["sources"],
        properties: {
          sources: { type: "array", items: { $ref: "#/components/schemas/AdminDataSourceOverview" } },
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
      DataSourceMappingProfile: {
        type: "object",
        properties: {
          profile_type: {
            type: "string",
            enum: ["auto", "manufacturing", "faq", "manual", "generic"],
          },
          data_profile: {
            type: "string",
            enum: ["auto", "manufacturing", "faq", "manual", "generic"],
          },
          field_mapping: { type: "object", additionalProperties: { type: "string" } },
          mapping: { type: "object", additionalProperties: { type: "string" } },
          defaults: { type: "object" },
          required_fields: { type: "array", items: { type: "string" } },
        },
      },
      DataSourcePreviewRequest: {
        type: "object",
        properties: {
          collection_id: { type: "string" },
          limit: { type: "number" },
          sample_documents: { type: "number" },
          sample_rows: { type: "number" },
          profile_type: {
            type: "string",
            enum: ["auto", "manufacturing", "faq", "manual", "generic"],
          },
          data_profile: {
            type: "string",
            enum: ["auto", "manufacturing", "faq", "manual", "generic"],
          },
          mapping_profile: { $ref: "#/components/schemas/DataSourceMappingProfile" },
          field_mapping: { type: "object", additionalProperties: { type: "string" } },
          defaults: { type: "object" },
          required_fields: { type: "array", items: { type: "string" } },
        },
      },
      DataSourcePreviewDocument: {
        type: "object",
        required: ["document_id", "document_ref", "content_type", "kind", "sample_row_count"],
        properties: {
          document_id: { type: "string" },
          document_ref: { type: "string" },
          content_type: { type: "string" },
          kind: { type: "string", enum: ["table", "text"] },
          sample_row_count: { type: "number" },
          text_preview: { type: "string" },
        },
      },
      DataSourcePreviewProfileOption: {
        type: "object",
        required: ["profile_type", "label"],
        properties: {
          profile_type: {
            type: "string",
            enum: ["auto", "manufacturing", "faq", "manual", "generic"],
          },
          label: { type: "string" },
        },
      },
      DataSourcePreviewCanonicalSection: {
        type: "object",
        required: ["label", "fields"],
        properties: {
          label: { type: "string" },
          fields: { type: "array", items: { type: "string" } },
        },
      },
      DataSourcePreviewRowValidation: {
        type: "object",
        required: ["status", "errors", "warnings"],
        properties: {
          status: { type: "string", enum: ["valid", "needs_review"] },
          errors: { type: "array", items: { type: "string" } },
          warnings: { type: "array", items: { type: "string" } },
        },
      },
      DataSourcePreviewSampleRow: {
        type: "object",
        required: ["document_id", "sheet_name", "row_number", "raw", "normalized", "validation"],
        properties: {
          document_id: { type: "string" },
          sheet_name: { type: "string" },
          row_number: { type: "number" },
          raw: { type: "object" },
          normalized: { type: "object" },
          validation: { $ref: "#/components/schemas/DataSourcePreviewRowValidation" },
        },
      },
      DataSourcePreviewResponse: {
        type: "object",
        required: [
          "source_id",
          "profile_type",
          "profile_label",
          "profile_options",
          "canonical_sections",
          "document_count",
          "documents",
          "canonical_fields",
          "detected_columns",
          "explicit_mapping",
          "suggested_mapping",
          "mapping_confidence",
          "defaults",
          "required_fields",
          "sample_rows",
          "validation",
        ],
        properties: {
          source_id: { type: "string" },
          profile_type: {
            type: "string",
            enum: ["manufacturing", "faq", "manual", "generic"],
          },
          profile_label: { type: "string" },
          profile_options: {
            type: "array",
            items: { $ref: "#/components/schemas/DataSourcePreviewProfileOption" },
          },
          canonical_sections: {
            type: "array",
            items: { $ref: "#/components/schemas/DataSourcePreviewCanonicalSection" },
          },
          document_count: { type: "number" },
          documents: {
            type: "array",
            items: { $ref: "#/components/schemas/DataSourcePreviewDocument" },
          },
          canonical_fields: { type: "array", items: { type: "string" } },
          detected_columns: { type: "array", items: { type: "string" } },
          explicit_mapping: { type: "object" },
          suggested_mapping: { type: "object" },
          mapping_confidence: { type: "object" },
          defaults: { type: "object" },
          required_fields: { type: "array", items: { type: "string" } },
          sample_rows: {
            type: "array",
            items: { $ref: "#/components/schemas/DataSourcePreviewSampleRow" },
          },
          validation: {
            type: "object",
            required: ["valid_count", "needs_review_count", "error_count", "warning_count", "errors", "warnings"],
            properties: {
              valid_count: { type: "number" },
              needs_review_count: { type: "number" },
              error_count: { type: "number" },
              warning_count: { type: "number" },
              errors: { type: "array", items: { type: "string" } },
              warnings: { type: "array", items: { type: "string" } },
            },
          },
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
          allowed_layout_providers: { type: "array", items: { type: "string" } },
          allowed_structured_providers: { type: "array", items: { type: "string" } },
          allowed_llm_providers: { type: "array", items: { type: "string" } },
          allowed_embedding_providers: { type: "array", items: { type: "string" } },
          allowed_visual_embedding_providers: { type: "array", items: { type: "string" } },
          allowed_vlm_providers: { type: "array", items: { type: "string" } },
          allowed_caption_providers: { type: "array", items: { type: "string" } },
          allowed_rerank_providers: { type: "array", items: { type: "string" } },
          allowed_regions: { type: "array", items: { type: "string" } },
          provider_regions: { type: "object" },
          data_residency_requirement: { type: "string" },
          cross_cloud_processing_allowed: { type: "boolean" },
          zero_retention_required: { type: "boolean" },
          no_train_required: { type: "boolean" },
          customer_opt_in_required: { type: "boolean" },
          customer_opt_in_status: { type: "string", enum: ["pending", "granted", "revoked"] },
          opt_in_status_by_family: { type: "object" },
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
          allowed_layout_providers: { type: "array", items: { type: "string" } },
          allowed_structured_providers: { type: "array", items: { type: "string" } },
          allowed_llm_providers: { type: "array", items: { type: "string" } },
          allowed_embedding_providers: { type: "array", items: { type: "string" } },
          allowed_visual_embedding_providers: { type: "array", items: { type: "string" } },
          allowed_vlm_providers: { type: "array", items: { type: "string" } },
          allowed_caption_providers: { type: "array", items: { type: "string" } },
          allowed_rerank_providers: { type: "array", items: { type: "string" } },
          allowed_regions: { type: "array", items: { type: "string" } },
          provider_regions: { type: "object" },
          cross_cloud_processing_allowed: { type: "boolean" },
          zero_retention_required: { type: "boolean" },
          no_train_required: { type: "boolean" },
          customer_opt_in_required: { type: "boolean" },
          customer_opt_in_status: { type: "string" },
          opt_in_status_by_family: { type: "object" },
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
          operation: {
            type: "string",
            enum: [
              "parse",
              "ocr",
              "layout",
              "structured",
              "embed",
              "embedding",
              "visual_embedding",
              "rerank",
              "llm",
              "vlm",
              "caption",
              "log",
            ],
          },
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
          kind: {
            type: "string",
            enum: [
              "text",
              "visual",
              "spreadsheet",
              "table_row",
              "form_field",
              "chart_series",
              "figure_caption",
            ],
          },
          document_id: { type: "string" },
          source_id: { type: "string" },
          version: { type: "number" },
          retrieval_score: { type: "number" },
          chunk_id: { type: "string", nullable: true },
          text_range: { type: "array", items: { type: "number" }, nullable: true },
          asset_id: { type: "string", nullable: true },
          page_number: { type: "number", nullable: true },
          region_id: { type: "string", nullable: true },
          bbox: { $ref: "#/components/schemas/BoundingBox", nullable: true },
          sheet_name: { type: "string", nullable: true },
          cell_range: { type: "string", nullable: true },
          row_id: { type: "string", nullable: true },
          table_id: { type: "string", nullable: true },
          form_id: { type: "string", nullable: true },
          field_name: { type: "string", nullable: true },
          chart_id: { type: "string", nullable: true },
          series_name: { type: "string", nullable: true },
          point_index: { type: "number", nullable: true },
          column_name: { type: "string", nullable: true },
          pixel_derived: { type: "boolean" },
          visual_evidence_verified: { type: "boolean" },
          visual_verifier_verdicts: {
            type: "array",
            items: { type: "object" },
          },
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
        required: ["status", "citations", "used_chunks", "correlation_id"],
        properties: {
          status: {
            type: "string",
            enum: ["ok", "insufficient_evidence", "budget_exceeded", "temporarily_unavailable"],
          },
          route: {
            type: "string",
            enum: ["rag", "structured_tool", "refused_structured_tool_required"],
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
      ChatQuickReply: {
        type: "object",
        required: ["label", "value"],
        properties: {
          label: { type: "string" },
          value: { type: "string" },
        },
      },
      ChatAssistantMessage: {
        type: "object",
        required: ["message_id", "message", "message_type", "ai_action", "quick_replies", "citations"],
        properties: {
          message_id: { type: "string" },
          message: { type: "string" },
          message_type: { type: "string" },
          ai_action: { type: "string" },
          quick_replies: { type: "array", items: { $ref: "#/components/schemas/ChatQuickReply" } },
          citations: { type: "array", items: { $ref: "#/components/schemas/Citation" } },
        },
      },
      ChatConversationState: {
        type: "object",
        required: ["status"],
        properties: {
          status: { type: "string" },
          response_state: {
            type: "string",
            enum: [
              "sending",
              "thinking",
              "checking_rag",
              "checking_action",
              "delayed",
              "retryable_error",
              "handoff_available",
              "completed",
            ],
          },
          current_intent: { type: "string", nullable: true },
          current_step: { type: "string", nullable: true },
          scenario_id: { type: "string", nullable: true },
          scenario_version_id: { type: "string", nullable: true },
          collected_slots: { type: "object" },
          missing_slots: { type: "array", items: { type: "string" } },
          summary: { type: "string" },
          handoff_required: { type: "boolean" },
        },
      },
      ChatRagInteraction: {
        type: "object",
        required: ["rag_interaction_id", "status", "answerable", "latency_ms"],
        properties: {
          rag_interaction_id: { type: "string" },
          status: { type: "string" },
          answerable: { type: "boolean" },
          confidence: { type: "number", nullable: true },
          no_answer_reason: { type: "string", nullable: true },
          trace_id: { type: "string", nullable: true },
          latency_ms: { type: "number" },
          citations: { type: "array", items: { $ref: "#/components/schemas/Citation" } },
          source_policy_id: { type: "string", nullable: true },
        },
      },
      ChatHandoffPackage: {
        type: "object",
        required: ["handoff_package_id", "session_id", "status", "reason"],
        properties: {
          handoff_package_id: { type: "string" },
          session_id: { type: "string" },
          status: { type: "string" },
          reason: { type: "string" },
          priority: { type: "string" },
          summary: { type: "string" },
          collected_slots: { type: "object" },
          missing_slots: { type: "array", items: { type: "string" } },
          rag_citations: { type: "array", items: { $ref: "#/components/schemas/Citation" } },
          recommended_action: { type: "string" },
        },
      },
      ChatTicketStub: {
        type: "object",
        required: ["ticket_id", "status"],
        properties: {
          ticket_id: { type: "string" },
          status: { type: "string" },
          idempotency_key: { type: "string" },
          created_at: { type: "string" },
        },
      },
      ChatCreateSessionRequest: {
        type: "object",
        properties: {
          channel: { type: "string" },
          initial_message: { type: "string" },
          collection_id: { type: "string" },
          metadata: { type: "object" },
        },
      },
      ChatPublicWidgetSessionRequest: {
        type: "object",
        required: ["widget_token"],
        properties: {
          widget_token: { type: "string" },
          initial_message: { type: "string" },
          metadata: { type: "object" },
        },
      },
      ChatCreateSessionResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "session_id", "status", "processed_initial_message", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          session_id: { type: "string" },
          status: { type: "string" },
          processed_initial_message: { type: "boolean" },
          user_message_id: { type: "string" },
          assistant_message: { $ref: "#/components/schemas/ChatAssistantMessage" },
          state: { $ref: "#/components/schemas/ChatConversationState" },
          rag: { $ref: "#/components/schemas/ChatRagInteraction", nullable: true },
          handoff: { $ref: "#/components/schemas/ChatHandoffPackage", nullable: true },
          ticket: { $ref: "#/components/schemas/ChatTicketStub", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      ChatMessageRequest: {
        type: "object",
        required: ["message"],
        properties: {
          message: { type: "string" },
          client_message_id: { type: "string" },
          collection_id: { type: "string" },
          stream: { type: "boolean" },
        },
      },
      ChatMessageResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "session_id", "user_message_id", "assistant_message", "state", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          session_id: { type: "string" },
          status: { type: "string" },
          user_message_id: { type: "string" },
          assistant_message: { $ref: "#/components/schemas/ChatAssistantMessage" },
          state: { $ref: "#/components/schemas/ChatConversationState" },
          rag: { $ref: "#/components/schemas/ChatRagInteraction", nullable: true },
          handoff: { $ref: "#/components/schemas/ChatHandoffPackage", nullable: true },
          ticket: { $ref: "#/components/schemas/ChatTicketStub", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      ChatStoredMessage: {
        type: "object",
        required: ["message_id", "role", "content_redacted"],
        properties: {
          message_id: { type: "string" },
          role: { type: "string" },
          content_redacted: { type: "string" },
          created_at: { type: "string" },
          message: { type: "string" },
          message_type: { type: "string" },
          ai_action: { type: "string", nullable: true },
          quick_replies: { type: "array", items: { $ref: "#/components/schemas/ChatQuickReply" } },
          citations: { type: "array", items: { $ref: "#/components/schemas/Citation" } },
        },
      },
      ChatSessionDetailResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "session_id", "status", "messages", "state", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          session_id: { type: "string" },
          status: { type: "string" },
          current_intent: { type: "string", nullable: true },
          scenario_id: { type: "string", nullable: true },
          scenario_version_id: { type: "string", nullable: true },
          summary: { type: "string" },
          messages: { type: "array", items: { $ref: "#/components/schemas/ChatStoredMessage" } },
          state: { $ref: "#/components/schemas/ChatConversationState" },
          handoff: { $ref: "#/components/schemas/ChatHandoffPackage", nullable: true },
          ticket: { $ref: "#/components/schemas/ChatTicketStub", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      ChatSessionSummary: {
        type: "object",
        required: ["session_id", "started_at", "last_message_at", "status", "handoff_required"],
        properties: {
          session_id: { type: "string" },
          started_at: { type: "string" },
          last_message_at: { type: "string" },
          current_intent: { type: "string", nullable: true },
          status: { type: "string" },
          resolution_status: { type: "string" },
          handoff_required: { type: "boolean" },
          scenario_version_id: { type: "string", nullable: true },
        },
      },
      ChatSessionListResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "items", "next_cursor", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          items: { type: "array", items: { $ref: "#/components/schemas/ChatSessionSummary" } },
          next_cursor: { type: "string", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      ChatHandoffRequest: {
        type: "object",
        properties: {
          reason: { type: "string" },
          comment: { type: "string" },
        },
      },
      ChatHandoffResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "session_id", "handoff_package_id", "status", "reason", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          session_id: { type: "string" },
          handoff_package_id: { type: "string" },
          status: { type: "string" },
          reason: { type: "string" },
          correlation_id: { type: "string" },
        },
      },
      ChatFeedbackRequest: {
        type: "object",
        properties: {
          message_id: { type: "string" },
          rating: { type: "number" },
          issue_type: { type: "string" },
          comment: { type: "string" },
        },
      },
      ChatFeedbackResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "evaluation_id", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          evaluation_id: { type: "string" },
          improvement_item_id: { type: "string", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      ChatMetricsResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "summary", "top_intents", "top_handoff_reasons", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          summary: {
            type: "object",
            required: [
              "conversation_count",
              "bot_resolution_rate",
              "handoff_rate",
              "unanswered_rate",
              "rag_answerable_rate",
              "average_turns",
              "p95_response_latency_ms",
            ],
            properties: {
              conversation_count: { type: "number" },
              bot_resolution_rate: { type: "number" },
              handoff_rate: { type: "number" },
              unanswered_rate: { type: "number" },
              rag_answerable_rate: { type: "number" },
              average_turns: { type: "number" },
              p95_response_latency_ms: { type: "number" },
            },
          },
          top_intents: { type: "array", items: { type: "object" } },
          top_handoff_reasons: { type: "array", items: { type: "object" } },
          correlation_id: { type: "string" },
        },
      },
      ChatbotSourceExposurePolicy: {
        type: "object",
        required: ["policy_id", "source_id", "exposure_mode"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          policy_id: { type: "string" },
          source_id: { type: "string" },
          collection_id: { type: "string" },
          exposure_mode: {
            type: "string",
            enum: [
              "disabled",
              "internal_authenticated",
              "external_authenticated",
              "external_anonymous",
            ],
          },
          allowed_channels: { type: "array", items: { type: "string" } },
          allowed_scenario_ids: { type: "array", items: { type: "string" } },
          allowed_intents: { type: "array", items: { type: "string" } },
          required_document_tags: { type: "array", items: { type: "string" } },
          blocked_document_tags: { type: "array", items: { type: "string" } },
          require_approved_effective: { type: "boolean" },
          allow_obsolete_primary_evidence: { type: "boolean" },
          allowed_domains: { type: "array", items: { type: "string" } },
          status: { type: "string" },
          unsupported_reason: { type: "string" },
          correlation_id: { type: "string" },
        },
      },
      ChatbotSourceExposureListResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "items", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          items: { type: "array", items: { $ref: "#/components/schemas/ChatbotSourceExposurePolicy" } },
          correlation_id: { type: "string" },
        },
      },
      ChatbotSourceExposureValidationResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "allowed", "reasons", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          allowed: { type: "boolean" },
          reasons: { type: "array", items: { type: "string" } },
          correlation_id: { type: "string" },
        },
      },
      ChatScenarioVersion: {
        type: "object",
        required: ["version_id", "status"],
        properties: {
          version_id: { type: "string" },
          status: { type: "string" },
          required_slots: { type: "array", items: { type: "string" } },
          optional_slots: { type: "array", items: { type: "string" } },
          steps: { type: "array", items: { type: "object" } },
          validation_rules: { type: "array", items: { type: "object" } },
          rag_policy: { type: "object" },
          actions: { type: "array", items: { type: "object" } },
          response_templates: { type: "object" },
          handoff_conditions: { type: "array", items: { type: "object" } },
          updated_at: { type: "string" },
          approved_by: { type: "string", nullable: true },
          approved_at: { type: "string", nullable: true },
          published_by: { type: "string", nullable: true },
          published_at: { type: "string", nullable: true },
        },
      },
      ChatScenarioResponse: {
        type: "object",
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          scenario_id: { type: "string" },
          name: { type: "string" },
          intents: { type: "array", items: { type: "string" } },
          status: { type: "string" },
          active_version_id: { type: "string", nullable: true },
          versions: { type: "array", items: { $ref: "#/components/schemas/ChatScenarioVersion" } },
          correlation_id: { type: "string" },
        },
      },
      ChatScenarioListResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "items", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          items: { type: "array", items: { $ref: "#/components/schemas/ChatScenarioResponse" } },
          correlation_id: { type: "string" },
        },
      },
      PhoneCitationRef: {
        type: "object",
        required: ["source_id", "document_id", "chunk_id", "retrieval_score"],
        properties: {
          source_id: { type: "string" },
          document_id: { type: "string" },
          chunk_id: { type: "string" },
          version: { type: "string", nullable: true },
          retrieval_score: { type: "number" },
          approval_status: { type: "string", nullable: true },
          effective_date: { type: "string", nullable: true },
          snippet_redacted: { type: "string", nullable: true },
        },
      },
      PhoneUtterance: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: ["speech", "dtmf", "barge_in", "hold", "resume", "hangup", "provider_failure"],
          },
          text: { type: "string" },
          dtmf_digits: { type: "string" },
          asr_confidence: { type: "number" },
          failed_provider: { type: "string" },
        },
      },
      PhoneSimulateCallRequest: {
        type: "object",
        properties: {
          caller: {
            type: "object",
            properties: {
              phone_number: { type: "string" },
              customer_id: { type: "string" },
            },
          },
          channel: { type: "string" },
          scenario_id: { type: "string" },
          collection_id: { type: "string" },
          utterances: { type: "array", items: { $ref: "#/components/schemas/PhoneUtterance" } },
          options: {
            type: "object",
            properties: {
              recording_enabled: { type: "boolean" },
              force_asr_confidence: { type: "number" },
            },
          },
        },
      },
      PhoneTurnRequest: {
        type: "object",
        properties: {
          event_type: { type: "string" },
          text: { type: "string" },
          dtmf_digits: { type: "string", nullable: true },
          asr_confidence: { type: "number" },
          collection_id: { type: "string" },
          failed_provider: { type: "string" },
        },
      },
      PhoneSafetyDecision: {
        type: "object",
        required: ["answered_with_evidence"],
        properties: {
          answered_with_evidence: { type: "boolean" },
          blocked_reason: { type: "string", nullable: true },
        },
      },
      PhoneHandoffSummary: {
        type: "object",
        required: ["handoff_package_id", "reason", "destination_type", "destination_id", "status"],
        properties: {
          handoff_package_id: { type: "string" },
          reason: { type: "string" },
          destination_type: { type: "string" },
          destination_id: { type: "string" },
          status: { type: "string" },
        },
      },
      PhoneTurnResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "call_id", "turn_id", "call_state", "safety", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          call_id: { type: "string" },
          turn_id: { type: "string" },
          call_state: { type: "string" },
          ai_action: { type: "string", nullable: true },
          ai_response_text: { type: "string", nullable: true },
          tts_audio_ref: { type: "string", nullable: true },
          citations: { type: "array", items: { $ref: "#/components/schemas/PhoneCitationRef" } },
          // Nullable in practice; the doc references the shape (contract test requires $ref|typed).
          handoff: { $ref: "#/components/schemas/PhoneHandoffSummary" },
          safety: { $ref: "#/components/schemas/PhoneSafetyDecision" },
          correlation_id: { type: "string" },
        },
      },
      PhoneSimulateCallResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "call_id", "status", "status_url", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          call_id: { type: "string" },
          status: { type: "string" },
          status_url: { type: "string" },
          turns: { type: "array", items: { $ref: "#/components/schemas/PhoneTurnResponse" } },
          correlation_id: { type: "string" },
        },
      },
      PhoneCallSummaryItem: {
        type: "object",
        required: ["call_id", "started_at", "state", "handoff_required"],
        properties: {
          call_id: { type: "string" },
          started_at: { type: "string" },
          ended_at: { type: "string", nullable: true },
          caller_phone_number_masked: { type: "string", nullable: true },
          customer_id: { type: "string", nullable: true },
          intent: { type: "string", nullable: true },
          state: { type: "string" },
          resolution_status: { type: "string", nullable: true },
          handoff_required: { type: "boolean" },
          handoff_reason: { type: "string", nullable: true },
          scenario_id: { type: "string", nullable: true },
          scenario_version_id: { type: "string", nullable: true },
        },
      },
      PhoneCallListResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "items", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          items: { type: "array", items: { $ref: "#/components/schemas/PhoneCallSummaryItem" } },
          next_cursor: { type: "string", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      PhoneTranscriptTurn: {
        type: "object",
        required: ["turn_id", "sequence_no", "speaker", "event_type"],
        properties: {
          turn_id: { type: "string" },
          sequence_no: { type: "integer" },
          speaker: { type: "string" },
          event_type: { type: "string" },
          redacted_text: { type: "string", nullable: true },
          created_at: { type: "string" },
          asr_confidence: { type: "number", nullable: true },
          dtmf_digits: { type: "string" },
          barge_in: { type: "boolean" },
          ai_action: { type: "string", nullable: true },
          tts_audio_ref: { type: "string", nullable: true },
          citations: { type: "array", items: { $ref: "#/components/schemas/PhoneCitationRef" } },
          latency_ms: { type: "object", additionalProperties: true },
          safety: { $ref: "#/components/schemas/PhoneSafetyDecision" },
          handoff_reason: { type: "string" },
        },
      },
      PhoneCallDetailResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "call_id", "state", "transcript", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          call_id: { type: "string" },
          state: { type: "string" },
          started_at: { type: "string" },
          ended_at: { type: "string", nullable: true },
          caller_phone_number_masked: { type: "string", nullable: true },
          customer_id: { type: "string", nullable: true },
          intent: { type: "string", nullable: true },
          summary: { type: "string" },
          resolution_status: { type: "string", nullable: true },
          scenario_id: { type: "string", nullable: true },
          scenario_version_id: { type: "string", nullable: true },
          recording_enabled: { type: "boolean" },
          recording_disclosure_played: { type: "boolean" },
          transcript_redaction_status: { type: "string" },
          transcript: { type: "array", items: { $ref: "#/components/schemas/PhoneTranscriptTurn" } },
          // Nullable in practice; the doc references the shape (contract test requires $ref|typed).
          handoff: { $ref: "#/components/schemas/PhoneHandoffPackage" },
          correlation_id: { type: "string" },
        },
      },
      PhoneHandoffPackage: {
        type: "object",
        required: ["handoff_package_id", "call_id", "status", "reason", "destination_type", "destination_id", "summary"],
        properties: {
          handoff_package_id: { type: "string" },
          call_id: { type: "string" },
          status: { type: "string" },
          reason: { type: "string" },
          priority: { type: "string" },
          destination_type: { type: "string" },
          destination_id: { type: "string" },
          customer: {
            type: "object",
            properties: {
              customer_id: { type: "string", nullable: true },
              phone_number_masked: { type: "string", nullable: true },
            },
          },
          intent: { type: "string", nullable: true },
          summary: { type: "string" },
          transcript_excerpt_redacted: { type: "string" },
          confirmed_slots: { type: "object", additionalProperties: { type: "string" } },
          citations: { type: "array", items: { $ref: "#/components/schemas/PhoneCitationRef" } },
          sentiment: { type: "string", nullable: true },
          recommended_next_action: { type: "string", nullable: true },
          operator_id: { type: "string", nullable: true },
          accepted_at: { type: "string", nullable: true },
          failure_reason: { type: "string", nullable: true },
          created_at: { type: "string" },
        },
      },
      PhoneHandoffAcceptRequest: {
        type: "object",
        properties: {
          operator_id: { type: "string" },
          queue_id: { type: "string" },
        },
      },
      PhoneHandoffAcceptResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "handoff_package_id", "status", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          handoff_package_id: { type: "string" },
          status: { type: "string" },
          accepted_at: { type: "string", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      PhoneScenarioSummary: {
        type: "object",
        required: ["scenario_id", "name", "intent", "status"],
        properties: {
          scenario_id: { type: "string" },
          name: { type: "string" },
          intent: { type: "string" },
          status: { type: "string" },
          active_version_id: { type: "string", nullable: true },
          updated_at: { type: "string" },
        },
      },
      PhoneScenarioListResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "items", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          items: { type: "array", items: { $ref: "#/components/schemas/PhoneScenarioSummary" } },
          correlation_id: { type: "string" },
        },
      },
      PhoneScenarioCreateRequest: {
        type: "object",
        required: ["name", "intent"],
        properties: {
          scenario_id: { type: "string" },
          name: { type: "string" },
          intent: { type: "string" },
          description: { type: "string" },
          owner_group: { type: "string" },
        },
      },
      PhoneScenarioVersionRequest: {
        type: "object",
        properties: {
          entry_conditions: { type: "array", items: { type: "object", additionalProperties: true } },
          steps: { type: "array", items: { type: "object", additionalProperties: true } },
          required_slots: {
            type: "array",
            items: {
              type: "object",
              required: ["slot"],
              properties: {
                slot: { type: "string" },
                prompt: { type: "string" },
                max_attempts: { type: "integer" },
              },
            },
          },
          branch_conditions: { type: "array", items: { type: "object", additionalProperties: true } },
          allowed_actions: { type: "array", items: { type: "string" } },
          handoff_conditions: {
            type: "array",
            items: {
              type: "object",
              required: ["reason"],
              properties: {
                reason: { type: "string" },
                enabled: { type: "boolean" },
              },
            },
          },
          fallback_message: { type: "string" },
          response_templates: { type: "array", items: { type: "object", additionalProperties: true } },
        },
      },
      PhoneScenarioMutationResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "scenario_id", "status", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          scenario_id: { type: "string" },
          scenario_version_id: { type: "string" },
          status: { type: "string" },
          active_version_id: { type: "string", nullable: true },
          scheduled_publish_at: { type: "string", nullable: true },
          rollback_target_version_id: { type: "string", nullable: true },
          correlation_id: { type: "string" },
        },
      },
      PhoneScenarioPreviewRequest: {
        type: "object",
        required: ["utterances"],
        properties: {
          // Plain utterance strings (contract example); structured PhoneUtterance objects are
          // also accepted by the service.
          utterances: { type: "array", items: { type: "string" } },
          collection_id: { type: "string" },
        },
      },
      PhoneScenarioPreviewResponse: {
        type: "object",
        required: ["api_version", "tenant_id", "scenario_id", "scenario_version_id", "turns", "would_handoff", "correlation_id"],
        properties: {
          api_version: { type: "string" },
          tenant_id: { type: "string" },
          scenario_id: { type: "string" },
          scenario_version_id: { type: "string" },
          turns: {
            type: "array",
            items: {
              type: "object",
              properties: {
                ai_action: { type: "string", nullable: true },
                ai_response_text: { type: "string", nullable: true },
                citations: { type: "array", items: { $ref: "#/components/schemas/PhoneCitationRef" } },
              },
            },
          },
          would_handoff: { type: "boolean" },
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
        required: ["status", "citations", "used_chunks", "correlation_id", "manufacturing"],
        properties: {
          status: {
            type: "string",
            enum: ["ok", "insufficient_evidence", "budget_exceeded", "temporarily_unavailable"],
          },
          route: {
            type: "string",
            enum: ["rag", "structured_tool", "refused_structured_tool_required"],
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
    "/chat/public-widget/sessions": {
      post: {
        operationId: "createPublicWidgetChatSession",
        security: [],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatPublicWidgetSessionRequest" } },
          },
        },
        responses: {
          "201": {
            description: "Created restricted anonymous public widget ChatBot session",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatCreateSessionResponse" } },
            },
          },
          "401": { description: "Invalid widget token", content: { "application/json": {} } },
          "403": { description: "Anonymous chat disabled or widget domain not allowed", content: { "application/json": {} } },
          "429": { description: "Public widget rate limit exceeded", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/sessions": {
      get: {
        operationId: "listChatSessions",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "intent", in: "query", required: false, schema: { type: "string" } },
          { name: "status", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Tenant-scoped ChatBot sessions",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatSessionListResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: ChatBot admin role required", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
      post: {
        operationId: "createChatSession",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatCreateSessionRequest" } },
          },
        },
        responses: {
          "201": {
            description: "Created ChatBot session",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatCreateSessionResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/sessions/{session_id}": {
      get: {
        operationId: "getChatSession",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "session_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "ChatBot session detail",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatSessionDetailResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Chat session not found", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/sessions/{session_id}/messages": {
      post: {
        operationId: "postChatMessage",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "session_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatMessageRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Completed non-streaming ChatBot turn",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatMessageResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Chat session not found", content: { "application/json": {} } },
          "409": { description: "Chat session is terminal", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/sessions/{session_id}/handoff": {
      post: {
        operationId: "requestChatHandoff",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "session_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: false,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatHandoffRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Queued ChatBot handoff package",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatHandoffResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Chat session not found", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/handoffs/{handoff_package_id}": {
      get: {
        operationId: "getChatHandoff",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "handoff_package_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "ChatBot handoff package",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatHandoffPackage" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: handoff read role required", content: { "application/json": {} } },
          "404": { description: "Handoff not found", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/sessions/{session_id}/feedback": {
      post: {
        operationId: "postChatFeedback",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "session_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatFeedbackRequest" } },
          },
        },
        responses: {
          "201": {
            description: "Created ChatBot feedback record",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatFeedbackResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Chat session not found", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/metrics": {
      get: {
        operationId: "getChatMetrics",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "ChatBot operational metrics",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatMetricsResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: metrics role required", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/source-exposure-policies": {
      get: {
        operationId: "listChatSourceExposurePolicies",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "ChatBot source exposure policies",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatbotSourceExposureListResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: source exposure policy role required", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/source-exposure-policies/{policy_id}": {
      put: {
        operationId: "putChatSourceExposurePolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "policy_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatbotSourceExposurePolicy" } },
          },
        },
        responses: {
          "200": {
            description: "Updated ChatBot source exposure policy",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatbotSourceExposurePolicy" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: source exposure policy role required", content: { "application/json": {} } },
          "422": { description: "Invalid exposure policy", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/source-exposure-policies/validate": {
      post: {
        operationId: "validateChatSourceExposurePolicy",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatbotSourceExposurePolicy" } },
          },
        },
        responses: {
          "200": {
            description: "Validation result for a ChatBot source exposure policy",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatbotSourceExposureValidationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: source exposure policy role required", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/scenarios": {
      get: {
        operationId: "listChatScenarios",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "ChatBot scenarios",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatScenarioListResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario role required", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
      post: {
        operationId: "createChatScenario",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { type: "object" } },
          },
        },
        responses: {
          "201": {
            description: "Created ChatBot scenario",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatScenarioResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario manage role required", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/scenarios/{scenario_id}/versions/{version_id}": {
      put: {
        operationId: "putChatScenarioVersion",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
          { name: "version_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/ChatScenarioVersion" } },
          },
        },
        responses: {
          "200": {
            description: "Updated draft ChatBot scenario version",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatScenarioResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario manage role required", content: { "application/json": {} } },
          "404": { description: "Scenario not found", content: { "application/json": {} } },
          "409": { description: "Scenario version is immutable", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/scenarios/{scenario_id}/versions/{version_id}/{action}": {
      post: {
        operationId: "postChatScenarioAction",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
          { name: "version_id", in: "path", required: true, schema: { type: "string" } },
          { name: "action", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: false,
          content: {
            "application/json": { schema: { type: "object" } },
          },
        },
        responses: {
          "200": {
            description: "Preview or transition a ChatBot scenario version",
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
          "403": { description: "Forbidden: scenario role required", content: { "application/json": {} } },
          "404": { description: "Scenario not found", content: { "application/json": {} } },
          "409": { description: "Scenario state conflict", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/chat/scenarios/{scenario_id}/rollback": {
      post: {
        operationId: "rollbackChatScenario",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Rollback ChatBot scenario to a published version",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/ChatScenarioResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario approver role required", content: { "application/json": {} } },
          "404": { description: "Scenario not found", content: { "application/json": {} } },
          "502": { description: "Chat service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/calls/simulate": {
      post: {
        operationId: "simulatePhoneCall",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PhoneSimulateCallRequest" } },
          },
        },
        responses: {
          "202": {
            description: "Deterministic simulated inbound phone call accepted",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneSimulateCallResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: phone simulate role required", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/calls": {
      get: {
        operationId: "listPhoneCalls",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "from", in: "query", required: false, schema: { type: "string" } },
          { name: "to", in: "query", required: false, schema: { type: "string" } },
          { name: "customer_id", in: "query", required: false, schema: { type: "string" } },
          { name: "phone_number", in: "query", required: false, schema: { type: "string" } },
          { name: "intent", in: "query", required: false, schema: { type: "string" } },
          { name: "state", in: "query", required: false, schema: { type: "string" } },
          { name: "handoff_reason", in: "query", required: false, schema: { type: "string" } },
          { name: "scenario_id", in: "query", required: false, schema: { type: "string" } },
          { name: "limit", in: "query", required: false, schema: { type: "integer" } },
          { name: "cursor", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Tenant-scoped phone call history",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneCallListResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: call history role required", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/calls/{call_id}": {
      get: {
        operationId: "getPhoneCall",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "call_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Redacted phone call detail with transcript and citation trace",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneCallDetailResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Call not found or not visible", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/calls/{call_id}/turns": {
      post: {
        operationId: "postPhoneCallTurn",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "call_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PhoneTurnRequest" } },
          },
        },
        responses: {
          "200": {
            description: "AI turn decision: answer_with_citations / ask_clarification / handoff / fallback / end_call",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneTurnResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "404": { description: "Call not found or not visible", content: { "application/json": {} } },
          "409": { description: "Terminal call cannot receive turns (call_terminal)", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/handoffs/{handoff_package_id}": {
      get: {
        operationId: "getPhoneHandoffPackage",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "handoff_package_id", in: "path", required: true, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Operator handoff package (masked/redacted caller context)",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneHandoffPackage" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: handoff read role required", content: { "application/json": {} } },
          "404": { description: "Handoff package not found", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/handoffs/{handoff_package_id}/accept": {
      post: {
        operationId: "acceptPhoneHandoff",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "handoff_package_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PhoneHandoffAcceptRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Handoff accepted by operator",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneHandoffAcceptResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: handoff read role required", content: { "application/json": {} } },
          "404": { description: "Handoff package not found", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/scenarios": {
      get: {
        operationId: "listPhoneScenarios",
        security: [{ bearerAuth: [], userToken: [] }],
        responses: {
          "200": {
            description: "Tenant-scoped phone call scenarios",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioListResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario role required", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
      post: {
        operationId: "createPhoneScenario",
        security: [{ bearerAuth: [], userToken: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioCreateRequest" } },
          },
        },
        responses: {
          "201": {
            description: "Created phone scenario draft (with seeded draft version)",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioMutationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario admin role required", content: { "application/json": {} } },
          "409": { description: "Scenario already exists", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/scenarios/{scenario_id}/versions/{version_id}": {
      put: {
        operationId: "upsertPhoneScenarioVersion",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
          { name: "version_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioVersionRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Draft phone scenario version updated",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioMutationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario admin role required", content: { "application/json": {} } },
          "404": { description: "Scenario not found", content: { "application/json": {} } },
          "409": { description: "Published scenario version is immutable (scenario_version_immutable)", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/scenarios/{scenario_id}/versions/{version_id}/test": {
      post: {
        operationId: "previewPhoneScenario",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
          { name: "version_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioPreviewRequest" } },
          },
        },
        responses: {
          "200": {
            description: "Non-persisted preview conversation for a scenario version",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioPreviewResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario role required", content: { "application/json": {} } },
          "404": { description: "Scenario or version not found", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/scenarios/{scenario_id}/versions/{version_id}/{action}": {
      post: {
        operationId: "phoneScenarioAction",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
          { name: "version_id", in: "path", required: true, schema: { type: "string" } },
          {
            name: "action",
            in: "path",
            required: true,
            schema: {
              type: "string",
              enum: ["submit-review", "approve", "publish", "schedule", "archive"],
            },
          },
        ],
        requestBody: {
          required: false,
          content: { "application/json": { schema: { type: "object", additionalProperties: true } } },
        },
        responses: {
          "200": {
            description: "Phone scenario version lifecycle action applied",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioMutationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario approver role required for approve/publish/schedule/archive", content: { "application/json": {} } },
          "404": { description: "Scenario or version not found", content: { "application/json": {} } },
          "409": { description: "Publish before approval (scenario_version_not_approved) or immutable version", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
        },
      },
    },
    "/phone/scenarios/{scenario_id}/rollback": {
      post: {
        operationId: "rollbackPhoneScenario",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "scenario_id", in: "path", required: true, schema: { type: "string" } },
        ],
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["target_version_id"],
                properties: {
                  target_version_id: { type: "string" },
                  rollback_comment: { type: "string" },
                },
              },
            },
          },
        },
        responses: {
          "200": {
            description: "New published version referencing the rollback target",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PhoneScenarioMutationResponse" } },
            },
          },
          "401": { description: "Unauthorized", content: { "application/json": {} } },
          "403": { description: "Forbidden: scenario approver role required", content: { "application/json": {} } },
          "404": { description: "Scenario or target version not found", content: { "application/json": {} } },
          "409": { description: "Rollback target was never approved (scenario_version_not_approved)", content: { "application/json": {} } },
          "502": { description: "Phone service unavailable", content: { "application/json": {} } },
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
    "/admin/sources/{source_id}/preview": {
      post: {
        operationId: "previewAdminSource",
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
              schema: { $ref: "#/components/schemas/DataSourcePreviewRequest" },
            },
          },
        },
        responses: {
          "200": {
            description: "Datasource onboarding preview",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/DataSourcePreviewResponse" },
              },
            },
          },
          "400": { description: "Preview failed", content: { "application/json": {} } },
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
    "/admin/datasources/overview": {
      get: {
        operationId: "listAdminDataSourceOverview",
        security: [{ bearerAuth: [], userToken: [] }],
        parameters: [
          { name: "collection_id", in: "query", required: false, schema: { type: "string" } },
        ],
        responses: {
          "200": {
            description: "Datasource operations overview",
            headers: {
              "api-version": { $ref: "#/components/headers/ApiVersion" },
              Deprecation: { $ref: "#/components/headers/Deprecation" },
              Sunset: { $ref: "#/components/headers/Sunset" },
            },
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/AdminDataSourceOverviewResponse" },
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
