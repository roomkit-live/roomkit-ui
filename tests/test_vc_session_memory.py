"""A voice-channel session starts a new conversation over the one durable room.

Every session writes the same room.  The AIChannel read the last session's
turns as the conversation going on: at the user's "hello" it took up what
was left open (an apology for ending the session), and each such answer,
stored, fed the next session.
"""

from datetime import UTC, datetime, timedelta

from vc_harness import StreamingInputTTS, open_session, until

from roomkit_ui.memory import session_window

_LEFT_OPEN = "I ended the session by mistake, and I cannot undo it."


async def _model_reads(ai_options: dict) -> list[str]:
    """What the model is given at a new session's first "Hello"."""
    vc = await open_session(
        tts=StreamingInputTTS(),
        reply=["Hi!"],
        transcripts=["Hello"],
        ai_options=ai_options,
        history=[_LEFT_OPEN],
    )
    try:
        await vc.speak()
        await until(lambda: vc.ai.contexts)
        return [str(message.content) for message in vc.ai.contexts[0].messages]
    finally:
        await vc.kit.close()


async def test_the_last_sessions_turns_reach_roomkits_default_window(qapp):
    # The seeded turn is one the model would read: the test sees the leak.
    assert await _model_reads({}) == [_LEFT_OPEN, "Hello"]


async def test_the_session_window_gives_the_model_this_session_only(qapp):
    started = datetime.now(UTC) - timedelta(seconds=1)

    reads = await _model_reads({"memory": session_window(started)})

    assert reads == ["Hello"]
