import {
  BedrockGuardrailsAdapter,
  type ApplyGuardrailRequest,
  type ApplyGuardrailResponse,
  type BedrockGuardrailsRuntime,
  type GuardrailDecision,
  type PrimaryControlDecision,
  type PrimaryControlName,
} from "../src/guardrails/bedrock-guardrails.adapter";

class FakeGuardrailsRuntime implements BedrockGuardrailsRuntime {
  readonly calls: ApplyGuardrailRequest[] = [];

  constructor(private readonly responses: ApplyGuardrailResponse[]) {}

  async applyGuardrail(request: ApplyGuardrailRequest): Promise<ApplyGuardrailResponse> {
    this.calls.push(request);
    return this.responses[Math.min(this.calls.length - 1, this.responses.length - 1)] ?? { action: "NONE" };
  }
}

function primary(control: PrimaryControlName, allowed: boolean): PrimaryControlDecision {
  return {
    control,
    allowed,
    reason: allowed ? "ok" : `${control} blocked`,
  };
}

function allowedGuardrail(): GuardrailDecision {
  return {
    allowed: true,
    action: "NONE",
    reason: "ok",
    assessments: [],
    usage: {},
    trace: { provider: "bedrock", source: "INPUT", latency_ms: 0 },
  };
}

function blockedGuardrail(): GuardrailDecision {
  return {
    allowed: false,
    action: "GUARDRAIL_INTERVENED",
    reason: "denied topic",
    assessments: [],
    usage: {},
    trace: { provider: "bedrock", source: "OUTPUT", latency_ms: 0 },
  };
}

describe("Bedrock Guardrails adapter", () => {
  it("calls ApplyGuardrail for input and output text", async () => {
    const runtime = new FakeGuardrailsRuntime([{ action: "NONE", usage: { topicPolicyUnits: 1 } }]);
    const adapter = new BedrockGuardrailsAdapter(runtime);

    const decision = await adapter.checkInput("reset alarm E-152", {
      guardrailIdentifier: "gr_123",
      guardrailVersion: "1",
      outputScope: "FULL",
      qualifiers: ["query"],
    });

    expect(decision.allowed).toBe(true);
    expect(decision.action).toBe("NONE");
    expect(decision.usage).toEqual({ topicPolicyUnits: 1 });
    expect(runtime.calls).toEqual([
      {
        guardrailIdentifier: "gr_123",
        guardrailVersion: "1",
        source: "INPUT",
        outputScope: "FULL",
        content: [{ text: { text: "reset alarm E-152", qualifiers: ["query"] } }],
      },
    ]);
  });

  it("blocks when Bedrock Guardrails intervenes and preserves sanitized output", async () => {
    const runtime = new FakeGuardrailsRuntime([
      {
        action: "GUARDRAIL_INTERVENED",
        actionReason: "denied topic",
        outputs: [{ text: "[blocked]" }],
        assessments: [{ topicPolicy: { topics: [] } }],
      },
    ]);
    const adapter = new BedrockGuardrailsAdapter(runtime);

    const decision = await adapter.checkOutput("unsafe output", {
      guardrailIdentifier: "gr_123",
      guardrailVersion: "DRAFT",
    });

    expect(runtime.calls[0].source).toBe("OUTPUT");
    expect(decision.allowed).toBe(false);
    expect(decision.action).toBe("GUARDRAIL_INTERVENED");
    expect(decision.reason).toBe("denied topic");
    expect(decision.sanitized_text).toBe("[blocked]");
  });

  it("cannot bypass ACL, RequiredEvidencePolicy, GroundednessGate, or RiskGate", () => {
    const adapter = new BedrockGuardrailsAdapter();
    const capabilities = adapter.bypassCapabilities();

    expect(capabilities).toEqual({
      ACL: false,
      RequiredEvidencePolicy: false,
      GroundednessGate: false,
      RiskGate: false,
    });
    expect(adapter.bypassesPrimaryControls()).toBe(false);

    for (const control of Object.keys(capabilities) as PrimaryControlName[]) {
      const result = adapter.enforcePrimaryControls(allowedGuardrail(), [
        primary(control, false),
        primary("ACL", true),
      ]);
      expect(result.allowed).toBe(false);
      expect(result.reasons).toContain(`${control}: ${control} blocked`);
    }

    const guardrailOnlyBlock = adapter.enforcePrimaryControls(blockedGuardrail(), [
      primary("ACL", true),
      primary("RequiredEvidencePolicy", true),
      primary("GroundednessGate", true),
      primary("RiskGate", true),
    ]);
    expect(guardrailOnlyBlock.allowed).toBe(false);
    expect(guardrailOnlyBlock.reasons).toContain("Guardrail: denied topic");
  });

  it("treats missing Bedrock Guardrails as unavailable without widening primary controls", async () => {
    const adapter = new BedrockGuardrailsAdapter();
    const decision = await adapter.checkInput("hello", {});

    expect(decision.allowed).toBe(true);
    expect(decision.action).toBe("UNAVAILABLE");
    expect(decision.reason).toBe("bedrock_guardrail_not_configured");

    const result = adapter.enforcePrimaryControls(decision, [primary("RequiredEvidencePolicy", false)]);
    expect(result.allowed).toBe(false);
    expect(result.reasons).toContain("RequiredEvidencePolicy: RequiredEvidencePolicy blocked");
  });
});
