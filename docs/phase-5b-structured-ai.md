# Phase 5b — structured external AI adapter

## Outcome

ConvictionSpread now has an opt-in external model path that can produce both the
directional thesis and an adversarial critic verdict. The ordinary shadow command
still defaults to the deterministic provider, so tests and unattended development
runs cannot create model charges accidentally.

The adapter uses OpenAI's Responses API with JSON Schema Structured Outputs. It sets
`store: false`, exposes no tools, and sends only the versioned market feature record
and underlying reference price. It does not send Alpaca credentials, account data,
equity, buying power, positions, option contracts, quantities, or order payloads.

Official API reference:

- [Create a model response](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)

## Local configuration

Add these values only to the ignored `.env` file:

```dotenv
OPENAI_API_KEY=your_openai_project_key
OPENAI_MODEL=an_explicit_structured_output_capable_model_id
```

The project deliberately has no model default. Model availability, cost, and account
access vary, so the operator must select the model explicitly.

Run the external model path:

```powershell
$env:PYTHONPATH = "src"
python scripts/shadow_scan.py --underlying SPY --ai-provider openai
```

This makes two model calls per scan: one proposal and one critic. Omit
`--ai-provider openai` to use the zero-cost deterministic path.

## Trust boundary

- Both responses use closed JSON schemas with every property required and additional
  properties forbidden.
- The response is parsed again by the local `AgentProposal` and `CriticVerdict`
  validators; Structured Outputs do not replace local validation.
- The model cannot select contracts or quantities. Deterministic code owns option
  normalization, spread construction, sizing, session gates, and final admission.
- A critic rejection forces PASS. A downgrade caps confidence. Confidence below the
  deterministic threshold also forces PASS.
- Incomplete responses, refusals, invalid JSON, local schema failures, HTTP errors,
  and exhausted bounded retries halt the external-model path safely.
- The final shadow portfolio still has execution disabled, dry-run active, and broker
  reconciliation false. Even a valid external proposal cannot approve an order.

## Evidence and current limitation

Six zero-cost tests verify request shape, `store: false`, lack of tools and account
data, exact schemas, explicit model selection, incomplete-response failure, hostile
extra fields, and the final broker-write block. The complete project now has 70
passing tests.

No paid external-model call was made while building this milestone because no OpenAI
project key, explicit model selection, or API budget was authorized. The adapter is
integration-ready, not live-provider-validated. After local configuration, save one
sanitized shadow result for judging; response bodies stay uncommitted and only hashes
and token counts appear in provider metadata.
