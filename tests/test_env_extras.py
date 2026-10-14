"""Which of the app's extras an environment carries, read from its distributions.

A small, made-up metadata world stands in for importlib.metadata: each
distribution installed, with the requirements its METADATA lists.
"""

import pytest

from roomkit_ui.env_extras import installed_extras, kept_extras, normalize_name

APP = (
    # the core
    "roomkit[local-audio]>=0.101",
    "httpx>=0.27",
    # extras, as hatchling writes them (self-references flattened, but for dictation)
    "roomkit[anthropic]>=0.101; extra == 'anthropic'",
    "roomkit[meta-stt]>=0.101; extra == 'meta-stt'",
    "roomkit[sherpa-onnx]>=0.101; extra == 'local-voice'",
    "sherpa-onnx-core>=1.13; extra == 'local-voice'",
    "roomkit-ui[local-voice]; extra == 'dictation'",
    "pynput>=1.7; extra == 'dictation'",
    "pyobjc>=10; sys_platform == 'darwin' and extra == 'dictation'",
    "roomkit[neutts]>=0.101; extra == 'neutts'",
    "roomkit[smart-turn]>=0.101; extra == 'smart-turn'",
    "roomkit[anthropic]>=0.101; extra == 'all'",
    "roomkit[sherpa-onnx]>=0.101; extra == 'all'",
    "sherpa-onnx-core>=1.13; extra == 'all'",
    "pynput>=1.7; extra == 'all'",
)
ROOMKIT = (
    "numpy>=1.26; extra == 'local-audio'",
    "anthropic<2,>=1.8; extra == 'anthropic'",
    "httpx>=0.27; extra == 'meta-stt'",
    "websockets>=14; extra == 'meta-stt'",
    "sherpa-onnx>=1.12; extra == 'sherpa-onnx'",
    "neutts>=0.1; extra == 'neutts'",
    "numpy>=1.26; extra == 'smart-turn'",
    "onnxruntime>=1.20; extra == 'smart-turn'",
    "transformers>=5.5; extra == 'smart-turn'",
)


def _world(*installed: str, **requires: tuple[str, ...]):
    """importlib.metadata's answers: *installed* distributions without
    requirements, plus the app, roomkit and the core's own (httpx pulls in
    websockets, so meta-stt brings nothing the core does not)."""
    metadata = {
        "roomkit-ui": APP,
        "roomkit": ROOMKIT,
        "httpx": ("websockets",),
        "websockets": (),
        "numpy": (),
        **{name: () for name in installed},
        **{normalize_name(name): value for name, value in requires.items()},
    }
    return lambda name: metadata.get(normalize_name(name))


def test_an_extra_counts_once_every_distribution_it_names_is_installed():
    assert installed_extras(_world("anthropic")) == ("anthropic",)
    assert installed_extras(_world()) == ()


def test_an_extra_the_core_already_brings_tells_nothing():
    # httpx and websockets are the core's: meta-stt cannot be told apart from it.
    assert "meta-stt" not in installed_extras(_world("anthropic"))


def test_an_extra_naming_another_one_of_the_app_follows_it():
    world = _world("sherpa-onnx", "sherpa-onnx-core", "pynput")

    assert installed_extras(world) == ("local-voice", "dictation")
    # A platform-bound requirement is not evaluated: it is left out, not required.
    assert "dictation" not in installed_extras(_world("sherpa-onnx", "sherpa-onnx-core"))


def test_smart_turn_is_not_read_into_what_a_voice_cloning_tts_installed():
    # NeuTTS pulls transformers and onnxruntime, numpy is the core's: all Smart Turn names.
    world = _world(
        "transformers", "onnxruntime", neutts=("transformers==5.1", "onnxruntime>=1.17")
    )

    assert installed_extras(world) == ("neutts",)


def test_smart_turn_alone_counts():
    assert installed_extras(_world("transformers", "onnxruntime")) == ("smart-turn",)


@pytest.mark.parametrize(
    ("recorded", "installed", "kept"),
    [
        (("all",), ("anthropic", "sherpa-onnx", "sherpa-onnx-core", "pynput"), ("all",)),
        (("anthropic",), ("anthropic", "sherpa-onnx", "sherpa-onnx-core"), None),
        ((), ("anthropic",), ("anthropic",)),
    ],
    ids=["all records them", "a component uv pip added", "a legacy install"],
)
def test_kept_extras_add_what_the_receipt_does_not_record(recorded, installed, kept):
    world = _world(*installed)

    expected = kept or (*recorded, "local-voice")
    assert kept_extras(recorded, world) == expected


def test_the_receipts_exclusive_extra_wins_over_one_found():
    world = _world("transformers", "onnxruntime", neutts=("transformers",))

    assert kept_extras(("smart-turn",), world) == ("smart-turn",)
