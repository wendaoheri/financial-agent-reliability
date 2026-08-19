## Purpose

Inference configuration v2 separates user intent, model capability, provider
adaptation, and wire protocol. It is additive: v1 configuration and trace
v0.1–v0.3 remain readable and are not rewritten.

## Resolution contract

Generation values resolve in this order:

`candidate override > named profile > model default > provider default > built-in default`

`stream` and `reasoning.mode` use `auto`, `on`, or `off`. Model capabilities
declare stream as `required`, `supported`, or `unsupported`, and reasoning as
`required`, `optional`, or `unsupported`. `auto` becomes `on` for required
capabilities and `off` for optional/unsupported capabilities unless an earlier
layer selected an explicit value.

Every live request records:

- the merged requested policy;
- the concrete resolved policy;
- effective provider parameters;
- the source of every resolved leaf;
- provider adapter, protocol, and model capability declaration.

Unsupported combinations fail before transport construction. Adapters do not
silently change a model, disable reasoning, or switch streaming modes.

## Provider boundaries

Provider adaptation and protocol encoding are separate. OpenAI-compatible
transport does not imply OpenAI parameter semantics.

| Adapter | Reasoning controls | Protocol-specific response |
| --- | --- | --- |
| Bailian/DashScope | `enable_thinking`, `reasoning_effort`, or `thinking_budget`, selected by model capability | OpenAI SSE `reasoning_content`, `content`, and usage |
| OpenAI | reasoning effort | Chat Completions or Responses events |
| Anthropic | `thinking.type` and `budget_tokens`; thinking budget is added to the provider max-token envelope | native thinking/text content-block deltas |
| Gemini | `thinkingConfig.thinkingBudget`; zero is emitted only for models whose capability contract allows reasoning off | native thought/text parts and usage metadata |
| BigModel/GLM | `thinking.type=enabled|disabled` | OpenAI-compatible event envelope with provider semantics |

`financial_agent_reliability.providers.protocols` contains pure payload and
event codecs for offline golden testing. Only an explicitly configured live
adapter may perform network I/O.

## Streaming and observability

Bailian streaming is consumed incrementally. Reasoning and final-content TTFT
are measured separately. Trace v0.4 stores reasoning character count and
SHA-256 only; hidden reasoning text is not persisted. It also records the
sanitized HTTP status, provider error code, request ID, and error origin so a
429 response is distinguishable from a client socket timeout.

The current standard-library HTTP transport enforces the configured socket
deadline and classifies `provider_http`, `client_socket`, and `network`
origins. Independent connect/first-byte/idle deadlines require a future
transport implementation and are not claimed by v0.2 of the live adapter.

## Matrix stop behavior

Live matrices run task-major, rotating across models before advancing to the
next task. Provider error-rate stopping is evaluated only after ten live
attempts; identity mismatch and safety hard-gate failures still stop
immediately. This removes the prior small-sample `1/5 > 10%` bias without
adding retries or paid calls.

## Cost and execution boundary

Schema validation, resolution, payload encoding, event parsing, trace
validation, and all golden tests are offline. A capability preflight and any
pilot remain separately authorized paid work. Credentials remain environment
references and all persisted values continue through the secret-scan gate.
