import json
import unittest

from conviction_spread_agent.agent import AgentProposal, CriticVerdict
from conviction_spread_agent.model_provider import (
    CRITIC_SCHEMA,
    PROPOSAL_SCHEMA,
    ModelProviderError,
    OpenAIResponsesAgent,
)
from conviction_spread_agent.shadow import build_shadow_decision
from tests.test_phase5_shadow import (
    NOW,
    broker_context,
    candidates,
    feature_snapshot,
)


def response(payload: dict[str, object], *, input_tokens: int = 100) -> dict[str, object]:
    return {
        "status": "completed",
        "output_text": json.dumps(payload),
        "usage": {"input_tokens": input_tokens, "output_tokens": 50},
    }


def proposal_payload() -> dict[str, object]:
    return {
        "direction": "bullish",
        "confidence": 0.84,
        "summary": "The aligned regime supports a cautious bullish thesis.",
        "evidence": ["fast and slow trends are positive"],
        "counter_evidence": ["short-horizon volatility remains non-zero"],
        "invalidation": "Pass if the aligned trend breaks.",
        "valid_for_minutes": 30,
    }


def critic_payload() -> dict[str, object]:
    return {
        "action": "approve",
        "reasons": ["the proposal matches the supplied regime and volume"],
        "confidence_cap": None,
    }


class StructuredModelAdapterTests(unittest.TestCase):
    def test_schema_is_closed_and_requires_every_contract_field(self) -> None:
        self.assertFalse(PROPOSAL_SCHEMA["additionalProperties"])
        self.assertFalse(CRITIC_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(PROPOSAL_SCHEMA["required"]), set(PROPOSAL_SCHEMA["properties"])
        )
        self.assertEqual(
            set(CRITIC_SCHEMA["required"]), set(CRITIC_SCHEMA["properties"])
        )

    def test_two_structured_calls_expose_no_tools_or_account_data(self) -> None:
        requests: list[dict[str, object]] = []

        def fake_transport(request: dict[str, object]) -> dict[str, object]:
            requests.append(request)
            schema_name = request["text"]["format"]["name"]
            if schema_name == "conviction_spread_proposal":
                return response(proposal_payload())
            return response(critic_payload(), input_tokens=120)

        run = OpenAIResponsesAgent(
            "test-key", "explicit-test-model", transport=fake_transport
        ).evaluate(feature_snapshot(), underlying_price=602)

        self.assertEqual(len(requests), 2)
        self.assertEqual(run.proposal.direction.value, "bullish")
        self.assertEqual(run.critic.action.value, "approve")
        for request in requests:
            self.assertFalse(request["store"])
            self.assertNotIn("tools", request)
            self.assertTrue(request["text"]["format"]["strict"])
            supplied_input = request["input"].lower()
            self.assertNotIn("account", supplied_input)
            self.assertNotIn("equity", supplied_input)
            self.assertNotIn("buying_power", supplied_input)
        self.assertFalse(run.public_metadata()["raw_response_committed"])
        self.assertEqual(run.public_metadata()["call_count"], 2)

    def test_local_contract_rejects_extra_model_fields(self) -> None:
        calls = 0

        def fake_transport(_: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            invalid = proposal_payload()
            invalid["quantity"] = 100
            return response(invalid)

        agent = OpenAIResponsesAgent("test-key", "model", transport=fake_transport)
        with self.assertRaisesRegex(ModelProviderError, "local schema"):
            agent.evaluate(feature_snapshot(), underlying_price=602)
        self.assertEqual(calls, 1)

    def test_incomplete_response_fails_closed(self) -> None:
        agent = OpenAIResponsesAgent(
            "test-key",
            "model",
            transport=lambda _: {"status": "incomplete", "output": []},
        )
        with self.assertRaisesRegex(ModelProviderError, "did not complete"):
            agent.evaluate(feature_snapshot(), underlying_price=602)

    def test_model_selection_is_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENAI_MODEL"):
            OpenAIResponsesAgent("test-key", "")


class ExternalProviderShadowTests(unittest.TestCase):
    def test_external_provider_still_cannot_approve_execution(self) -> None:
        proposal = AgentProposal.from_mapping(proposal_payload())
        critic = CriticVerdict.from_mapping(critic_payload())
        result = build_shadow_decision(
            feature_snapshot(),
            underlying_price=602,
            candidates=candidates(),
            broker=broker_context(),
            generated_at=NOW,
            stock_feed="iex",
            option_feed="indicative",
            proposal=proposal,
            critic=critic,
            provider_name="openai-responses:explicit-test-model",
            provider_role="external structured thesis and critic",
            provider_metadata={"call_count": 2},
        )
        self.assertEqual(result["schema_version"], "phase-5b.shadow.v1")
        self.assertEqual(result["outcome"], "candidate_blocked")
        self.assertFalse(result["risk"]["approved"])
        self.assertFalse(result["safety"]["broker_writes_possible"])
        self.assertEqual(result["agent"]["provider_metadata"]["call_count"], 2)


if __name__ == "__main__":
    unittest.main()
