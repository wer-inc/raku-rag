import { Inject, Injectable, Optional } from "@nestjs/common";

export const BEDROCK_GUARDRAILS_PROVIDER = "bedrock";
export const BEDROCK_GUARDRAILS_RUNTIME = "BEDROCK_GUARDRAILS_RUNTIME";

export type GuardrailSource = "INPUT" | "OUTPUT";
export type GuardrailAction = "NONE" | "GUARDRAIL_INTERVENED" | "UNAVAILABLE";
export type GuardrailOutputScope = "INTERVENTIONS" | "FULL";
export type GuardrailQualifier = "grounding_source" | "query" | "guard_content";
export type PrimaryControlName = "ACL" | "RequiredEvidencePolicy" | "GroundednessGate" | "RiskGate";

export interface ApplyGuardrailRequest {
  guardrailIdentifier: string;
  guardrailVersion: string;
  source: GuardrailSource;
  content: Array<{
    text: {
      text: string;
      qualifiers?: GuardrailQualifier[];
    };
  }>;
  outputScope?: GuardrailOutputScope;
}

export interface ApplyGuardrailResponse {
  action?: GuardrailAction;
  actionReason?: string;
  outputs?: Array<{ text?: string }>;
  assessments?: unknown[];
  usage?: Record<string, number>;
}

export interface BedrockGuardrailsRuntime {
  applyGuardrail(request: ApplyGuardrailRequest): Promise<ApplyGuardrailResponse> | ApplyGuardrailResponse;
}

export interface BedrockGuardrailsPolicy {
  guardrailIdentifier?: string;
  guardrailVersion?: string;
  outputScope?: GuardrailOutputScope;
  qualifiers?: GuardrailQualifier[];
}

export interface GuardrailDecision {
  allowed: boolean;
  action: GuardrailAction;
  reason: string;
  sanitized_text?: string;
  assessments: unknown[];
  usage: Record<string, number>;
  trace: {
    provider: typeof BEDROCK_GUARDRAILS_PROVIDER;
    source: GuardrailSource;
    latency_ms: number;
    guardrail_identifier?: string;
    guardrail_version?: string;
  };
}

export interface PrimaryControlDecision {
  control: PrimaryControlName;
  allowed: boolean;
  reason: string;
}

export interface GuardrailEnforcementResult {
  allowed: boolean;
  reasons: string[];
  guardrail: GuardrailDecision;
  primary_controls: PrimaryControlDecision[];
}

@Injectable()
export class BedrockGuardrailsAdapter {
  constructor(
    @Optional()
    @Inject(BEDROCK_GUARDRAILS_RUNTIME)
    private readonly runtime?: BedrockGuardrailsRuntime,
  ) {}

  checkInput(text: string, policy: BedrockGuardrailsPolicy): Promise<GuardrailDecision> {
    return this.check("INPUT", text, policy);
  }

  checkOutput(text: string, policy: BedrockGuardrailsPolicy): Promise<GuardrailDecision> {
    return this.check("OUTPUT", text, policy);
  }

  async check(source: GuardrailSource, text: string, policy: BedrockGuardrailsPolicy): Promise<GuardrailDecision> {
    const started = Date.now();
    if (!this.runtime || !policy.guardrailIdentifier || !policy.guardrailVersion) {
      return this.decision({
        source,
        started,
        policy,
        action: "UNAVAILABLE",
        reason: "bedrock_guardrail_not_configured",
      });
    }
    try {
      const response = await this.runtime.applyGuardrail({
        guardrailIdentifier: policy.guardrailIdentifier,
        guardrailVersion: policy.guardrailVersion,
        source,
        outputScope: policy.outputScope ?? "INTERVENTIONS",
        content: [
          {
            text: {
              text,
              qualifiers: policy.qualifiers,
            },
          },
        ],
      });
      const action = response.action ?? "NONE";
      return this.decision({
        source,
        started,
        policy,
        action,
        reason: response.actionReason ?? (action === "GUARDRAIL_INTERVENED" ? "guardrail_intervened" : "ok"),
        sanitizedText: response.outputs?.map((output) => output.text ?? "").join("") || undefined,
        assessments: response.assessments ?? [],
        usage: response.usage ?? {},
      });
    } catch (error) {
      return this.decision({
        source,
        started,
        policy,
        action: "UNAVAILABLE",
        reason: error instanceof Error && error.message ? error.message : "bedrock_guardrail_unavailable",
      });
    }
  }

  enforcePrimaryControls(
    guardrail: GuardrailDecision,
    primaryControls: PrimaryControlDecision[],
  ): GuardrailEnforcementResult {
    const primaryBlocks = primaryControls.filter((decision) => !decision.allowed);
    const reasons = [
      ...primaryBlocks.map((decision) => `${decision.control}: ${decision.reason}`),
      ...(guardrail.allowed ? [] : [`Guardrail: ${guardrail.reason}`]),
    ];
    return {
      allowed: primaryBlocks.length === 0 && guardrail.allowed,
      reasons,
      guardrail,
      primary_controls: primaryControls,
    };
  }

  bypassCapabilities(): Record<PrimaryControlName, false> {
    return {
      ACL: false,
      RequiredEvidencePolicy: false,
      GroundednessGate: false,
      RiskGate: false,
    };
  }

  bypassesPrimaryControls(): false {
    return false;
  }

  private decision(args: {
    source: GuardrailSource;
    started: number;
    policy: BedrockGuardrailsPolicy;
    action: GuardrailAction;
    reason: string;
    sanitizedText?: string;
    assessments?: unknown[];
    usage?: Record<string, number>;
  }): GuardrailDecision {
    return {
      allowed: args.action !== "GUARDRAIL_INTERVENED",
      action: args.action,
      reason: args.reason,
      sanitized_text: args.sanitizedText,
      assessments: args.assessments ?? [],
      usage: args.usage ?? {},
      trace: {
        provider: BEDROCK_GUARDRAILS_PROVIDER,
        source: args.source,
        latency_ms: Math.max(0, Date.now() - args.started),
        guardrail_identifier: args.policy.guardrailIdentifier,
        guardrail_version: args.policy.guardrailVersion,
      },
    };
  }
}
