"""Strict external-model adapter for Phase 5b thesis and critic evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .agent import AgentProposal, AgentSchemaError, CriticVerdict
from .features.engine import FeatureSnapshot


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "direction": {"type": "string", "enum": ["bullish", "bearish", "pass"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string", "minLength": 1, "maxLength": 500},
        "evidence": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "maxItems": 8,
        },
        "counter_evidence": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "maxItems": 8,
        },
        "invalidation": {"type": "string", "minLength": 1, "maxLength": 500},
        "valid_for_minutes": {"type": "integer", "minimum": 1, "maximum": 120},
    },
    "required": [
        "direction",
        "confidence",
        "summary",
        "evidence",
        "counter_evidence",
        "invalidation",
        "valid_for_minutes",
    ],
}


CRITIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["approve", "downgrade", "reject"]},
        "reasons": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "maxItems": 8,
        },
        "confidence_cap": {
            "anyOf": [
                {"type": "number", "minimum": 0, "maximum": 1},
                {"type": "null"},
            ]
        },
    },
    "required": ["action", "reasons", "confidence_cap"],
}


class ModelProviderError(RuntimeError):
    """A sanitized external-model failure that must halt the model path."""


@dataclass(frozen=True)
class ModelCallEvidence:
    schema_name: str
    response_sha256: str
    input_tokens: int | None
    output_tokens: int | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "response_sha256": self.response_sha256,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True)
class StructuredAgentRun:
    proposal: AgentProposal
    critic: CriticVerdict
    provider: str
    model: str
    calls: tuple[ModelCallEvidence, ...]

    def public_metadata(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "call_count": len(self.calls),
            "calls": [call.as_mapping() for call in self.calls],
            "raw_response_committed": False,
        }


ResponseTransport = Callable[[dict[str, Any]], dict[str, Any]]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _feature_input(features: FeatureSnapshot, underlying_price: Decimal) -> dict[str, object]:
    return {
        "symbol": features.symbol,
        "feature_set_version": features.feature_set_version,
        "feature_as_of": features.as_of.isoformat(),
        "underlying_price": str(underlying_price),
        "regime": features.regime.value,
        "trend_fast": str(features.trend_fast),
        "trend_slow": str(features.trend_slow),
        "realized_vol": str(features.realized_vol),
        "relative_volume": str(features.relative_volume),
        "atr": str(features.atr),
        "relative_strength": str(features.relative_strength),
    }


def _output_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    output = response.get("output")
    if not isinstance(output, list):
        raise ModelProviderError("model response did not contain structured output")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "refusal":
                raise ModelProviderError("model refused the structured evaluation")
            if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                text = block["text"].strip()
                if text:
                    return text
    raise ModelProviderError("model response did not contain structured output text")


class OpenAIResponsesAgent:
    """Two-call proposal/critic agent using Responses Structured Outputs.

    Model selection is explicit. The adapter has no tools and receives no portfolio,
    credential, order, or account data.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: int = 30,
        maximum_attempts: int = 2,
        transport: ResponseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        if not model.strip():
            raise ValueError("OPENAI_MODEL must explicitly select a model")
        if timeout_seconds <= 0 or maximum_attempts <= 0 or maximum_attempts > 3:
            raise ValueError("invalid model timeout or retry bound")
        self.__api_key = api_key
        self.model = model.strip()
        self.__timeout_seconds = timeout_seconds
        self.__maximum_attempts = maximum_attempts
        self.__transport = transport or self.__post_response

    def __post_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        request = Request(
            OPENAI_RESPONSES_URL,
            method="POST",
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.__api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "conviction-spread-agent-model/0.1",
            },
        )
        for attempt in range(1, self.__maximum_attempts + 1):
            try:
                with urlopen(request, timeout=self.__timeout_seconds) as response:  # noqa: S310
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise ModelProviderError("OpenAI returned a non-object response")
                return result
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if not retryable or attempt == self.__maximum_attempts:
                    raise ModelProviderError(
                        f"OpenAI Responses API returned HTTP {exc.code}"
                    ) from exc
            except (URLError, TimeoutError) as exc:
                if attempt == self.__maximum_attempts:
                    raise ModelProviderError("OpenAI Responses API was unavailable") from exc
            time.sleep(0.25 * attempt)
        raise ModelProviderError("OpenAI Responses API retry bound was exhausted")

    def __structured_call(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        instructions: str,
        input_record: dict[str, object],
    ) -> tuple[dict[str, Any], ModelCallEvidence]:
        response = self.__transport(
            {
                "model": self.model,
                "instructions": instructions,
                "input": json.dumps(input_record, sort_keys=True, separators=(",", ":")),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                    "verbosity": "low",
                },
                "max_output_tokens": 900,
                "store": False,
                "prompt_cache_key": "conviction-spread-phase5b-v1",
            }
        )
        if response.get("status") != "completed":
            raise ModelProviderError("model response did not complete")
        text = _output_text(response)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ModelProviderError("model structured output was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ModelProviderError("model structured output was not a JSON object")
        usage = response.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        evidence = ModelCallEvidence(
            schema_name=schema_name,
            response_sha256=hashlib.sha256(text.encode()).hexdigest(),
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
        )
        return parsed, evidence

    def evaluate(
        self, features: FeatureSnapshot, *, underlying_price: Decimal
    ) -> StructuredAgentRun:
        trusted_input = _feature_input(features, underlying_price)
        proposal_payload, proposal_evidence = self.__structured_call(
            schema_name="conviction_spread_proposal",
            schema=PROPOSAL_SCHEMA,
            instructions=(
                "Act as a cautious directional options-thesis analyst. Use only the "
                "provided versioned features. You may propose bullish, bearish, or "
                "pass. Do not choose contracts, quantities, orders, accounts, or "
                "risk overrides. State contradicting evidence and a price-based or "
                "condition-based invalidation. Prefer pass when evidence is weak."
            ),
            input_record=trusted_input,
        )
        try:
            proposal = AgentProposal.from_mapping(proposal_payload)
        except AgentSchemaError as exc:
            raise ModelProviderError("model proposal failed local schema validation") from exc

        critic_payload, critic_evidence = self.__structured_call(
            schema_name="conviction_spread_critic",
            schema=CRITIC_SCHEMA,
            instructions=(
                "Act as an adversarial risk critic. Use only the supplied trusted "
                "features and proposal. Approve, downgrade, or reject the thesis. "
                "Never add a symbol, contract, quantity, order, or bypass instruction. "
                "Reject contradictions and cap confidence when uncertainty is material."
            ),
            input_record={"features": trusted_input, "proposal": proposal.as_mapping()},
        )
        try:
            critic = CriticVerdict.from_mapping(critic_payload)
        except AgentSchemaError as exc:
            raise ModelProviderError("model critic failed local schema validation") from exc
        return StructuredAgentRun(
            proposal=proposal,
            critic=critic,
            provider="openai-responses",
            model=self.model,
            calls=(proposal_evidence, critic_evidence),
        )
