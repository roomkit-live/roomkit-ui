"""Session usage/cost accounting: pricing lookup, accumulation, display."""

from datetime import date

from roomkit.providers.ai.base import ModelPricing

from roomkit_ui.engine_vc import VoiceChannelMixin, _model_pricing, _usage_int
from roomkit_ui.widgets.session_info import _usage_summary

PRICING = ModelPricing(
    input_per_million=3.0,
    output_per_million=15.0,
    cache_read_per_million=0.3,
    verified=date(2026, 8, 5),
)


# -- _usage_int ---------------------------------------------------------------


def test_usage_int_tolerates_absent_none_and_garbage():
    assert _usage_int({}, "input_tokens") == 0
    assert _usage_int({"input_tokens": None}, "input_tokens") == 0
    assert _usage_int({"input_tokens": "abc"}, "input_tokens") == 0
    assert _usage_int({"input_tokens": "42"}, "input_tokens") == 42


# -- _model_pricing -----------------------------------------------------------


class _Entry:
    def __init__(self, pricing):
        self.pricing = pricing


class _Provider:
    def __init__(self, entry):
        self._entry = entry

    def catalog_entry(self):
        if isinstance(self._entry, Exception):
            raise self._entry
        return self._entry


def test_model_pricing_reads_the_catalog_entry():
    assert _model_pricing(_Provider(_Entry(PRICING))) is PRICING


def test_model_pricing_none_for_unknown_models():
    assert _model_pricing(_Provider(None)) is None


def test_model_pricing_never_raises():
    assert _model_pricing(_Provider(RuntimeError("boom"))) is None
    assert _model_pricing(object()) is None  # no catalog_entry() at all


# -- _accumulate_usage --------------------------------------------------------


class _FakeSignal:
    def __init__(self):
        self.payloads = []

    def emit(self, payload):
        self.payloads.append(payload)


class _FakeEngine:
    """Bare object carrying just what _accumulate_usage touches."""

    _accumulate_usage = VoiceChannelMixin._accumulate_usage

    def __init__(self, pricing):
        self._ai_pricing = pricing
        self._usage_cost = 0.0
        self._usage_in = 0
        self._usage_out = 0
        self.session_cost = _FakeSignal()


def test_accumulate_usage_totals_and_prices():
    engine = _FakeEngine(PRICING)
    engine._accumulate_usage({"input_tokens": 1000, "output_tokens": 2000})
    engine._accumulate_usage(
        {"input_tokens": 500, "output_tokens": 100, "cache_read_input_tokens": 200}
    )

    assert engine._usage_in == 1700  # cache reads count as input tokens
    assert engine._usage_out == 2100
    payload = engine.session_cost.payloads[-1]
    # 1500 uncached input + 200 cache reads + 2100 output
    expected = (1500 * 3.0 + 200 * 0.3 + 2100 * 15.0) / 1_000_000
    assert abs(payload["cost_usd"] - expected) < 1e-9
    assert payload["input_tokens"] == 1700
    assert payload["output_tokens"] == 2100


def test_accumulate_usage_without_pricing_reports_tokens_only():
    engine = _FakeEngine(None)
    engine._accumulate_usage({"input_tokens": 10, "output_tokens": 5})

    payload = engine.session_cost.payloads[-1]
    assert payload["cost_usd"] is None
    assert payload["input_tokens"] == 10


# -- _usage_summary -----------------------------------------------------------


def test_usage_summary_small_cost_uses_four_decimals():
    text = _usage_summary({"cost_usd": 0.0123, "input_tokens": 3000, "output_tokens": 1200})
    assert text == "$0.0123 · 4.2k tok"


def test_usage_summary_large_cost_uses_two_decimals():
    assert _usage_summary({"cost_usd": 1.5, "input_tokens": 0, "output_tokens": 0}) == "$1.50"


def test_usage_summary_without_pricing_shows_tokens_only():
    assert (
        _usage_summary({"cost_usd": None, "input_tokens": 900, "output_tokens": 50}) == "950 tok"
    )
