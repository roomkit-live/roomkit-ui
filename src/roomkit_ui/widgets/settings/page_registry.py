"""Stable settings page identities shared by navigation and the page stack."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from roomkit_ui.components import components
from roomkit_ui.widgets.settings.about_page import _AboutPage
from roomkit_ui.widgets.settings.audio_page import AudioPage
from roomkit_ui.widgets.settings.conversation_page import ConversationPage
from roomkit_ui.widgets.settings.diagnostics_page import DiagnosticsPage
from roomkit_ui.widgets.settings.dictation_page import _DictationPage
from roomkit_ui.widgets.settings.general_page import _GeneralPage
from roomkit_ui.widgets.settings.integrations_page import IntegrationsPage
from roomkit_ui.widgets.settings.library_page import LibraryPage
from roomkit_ui.widgets.settings.model_library import model_groups
from roomkit_ui.widgets.settings.privacy_page import PrivacyPage
from roomkit_ui.widgets.settings.providers_page import PROVIDERS, ProvidersPage
from roomkit_ui.widgets.settings.search import SearchTarget
from roomkit_ui.widgets.settings.wakeword_page import _WakeWordPage


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    group: str
    icon: str
    create: Callable[[dict], QWidget]
    refresh: str = ""
    search: tuple[SearchTarget, ...] = ()


PAGE_SPECS = (
    PageSpec(
        "general",
        "General",
        "Workspace",
        "squares-2x2",
        _GeneralPage,
        search=(
            SearchTarget(
                "Appearance & theme", "light dark clair sombre apparence", "theme_picker"
            ),
            SearchTarget(
                "Assistant shortcut",
                "hotkey keyboard raccourci clavier",
                "assistant_hotkey",
                fallback="assistant_hotkey_enabled",
                unavailable="Enable the assistant shortcut to change its keys.",
            ),
            SearchTarget(
                "Enable assistant shortcut", "hotkey activer raccourci", "assistant_hotkey_enabled"
            ),
        ),
    ),
    PageSpec(
        "conversation",
        "Conversation",
        "Workspace",
        "chat-bubble",
        ConversationPage,
        "refresh",
        search=(
            SearchTarget(
                "Conversation mode",
                "AI provider realtime voice channel intelligence",
                "voice.mode_picker",
                (("tabs", 0),),
            ),
            SearchTarget(
                "System instructions",
                "system prompt instructions système",
                "prompt",
                (("tabs", 1),),
            ),
            SearchTarget(
                "Default personality",
                "attitudes persona personnalité ton",
                "attitude_combo",
                (("tabs", 1),),
            ),
            SearchTarget(
                "Personality presets",
                "attitudes custom personnalités",
                "attitudes",
                (("tabs", 1),),
            ),
            SearchTarget(
                "Listen · STT",
                "transcription speech recognition reconnaissance vocale",
                "voice.vc_stt_provider",
                (("tabs", 0), ("voice.pipeline_tabs", 0)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode to configure transcription.",
            ),
            SearchTarget(
                "Think · LLM",
                "language model intelligence modèle langage",
                "voice.vc_provider",
                (("tabs", 0), ("voice.pipeline_tabs", 1)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode to configure reasoning.",
            ),
            SearchTarget(
                "Thinking & effort",
                "reasoning effort thinking réflexion raisonnement claude gemini",
                "voice._cloud.vc_reasoning",
                (("tabs", 0), ("voice.pipeline_tabs", 1)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode with Claude or Gemini to set "
                "thinking and effort.",
            ),
            SearchTarget(
                "Speak · TTS",
                "speech synthesis voix synthèse",
                "voice.vc_tts_provider",
                (("tabs", 0), ("voice.pipeline_tabs", 2)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode to configure speech synthesis.",
            ),
            SearchTarget(
                "Audio tags",
                "expressive voice whisper laugh sigh tags delivery elevenlabs gemini",
                "voice._cloud.vc_tts_audio_tags",
                (("tabs", 0), ("voice.pipeline_tabs", 2)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode to let the assistant direct its voice.",
            ),
            SearchTarget(
                "Agent behavior",
                "turn taking jev thinker background speaking decision",
                "voice._agent.speak_policy",
                (("tabs", 0), ("voice.pipeline_tabs", 3)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode to configure agent behavior.",
            ),
            SearchTarget(
                "Barge-in",
                "interruption interrompre semantic",
                "voice.vc_interruption_mode",
                (("tabs", 0), ("voice.pipeline_tabs", 0)),
                fallback="voice.mode_picker",
                unavailable="Select Voice Channel mode to configure barge-in here.",
            ),
        ),
    ),
    PageSpec(
        "audio",
        "Audio & voice",
        "Workspace",
        "waveform",
        AudioPage,
        "refresh",
        search=(
            SearchTarget(
                "Microphone",
                "input device entrée micro périphérique",
                "processing.input_combo",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Audio output",
                "speaker output device haut parleur sortie",
                "processing.output_combo",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Echo cancellation", "AEC écho webrtc speex", "processing.aec", (("tabs", 0),)
            ),
            SearchTarget(
                "Noise reduction",
                "denoise rnnoise gtcrn bruit",
                "processing.denoise",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Voice detection",
                "VAD détection parole silero",
                "processing.vad_model",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Voice detection threshold",
                "VAD threshold seuil sensibilité advanced",
                "processing.vad_threshold",
                (("tabs", 0),),
                "processing.vad_advanced",
                "processing.vad_model",
                "Select a voice detection model to tune its threshold.",
            ),
            SearchTarget(
                "Turn detector",
                "smart turn fin parole",
                "processing.turn_detector",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Inference device",
                "CPU GPU CUDA CoreML",
                "processing.inference_device",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Speaker recognition",
                "speakers identification diarization enrollment locuteurs voix",
                "speakers._enable_cb",
                (("tabs", 1),),
            ),
            SearchTarget(
                "Speaker model",
                "speaker local identification modèle locuteur",
                "speakers._model_combo",
                (("tabs", 1),),
            ),
            SearchTarget(
                "Recognition threshold",
                "speaker sensitivity seuil reconnaissance locuteur",
                "speakers._threshold_slider",
                (("tabs", 1),),
                "speakers.threshold_advanced",
            ),
            SearchTarget(
                "Primary speaker",
                "listen only primary speaker principal locuteur",
                "speakers._primary_cb",
                (("tabs", 1),),
            ),
            SearchTarget(
                "Your name with Meta Muse",
                "muse speaker first voice nom première voix",
                "speakers._muse.user_name",
                (("tabs", 1),),
            ),
        ),
    ),
    PageSpec(
        "dictation",
        "Dictation",
        "Workspace",
        "microphone",
        _DictationPage,
        "refresh_model_combo",
        search=(
            SearchTarget("Enable dictation", "dictée activer activation", "enabled"),
            SearchTarget("Dictation provider", "dictée transcription STT local", "stt_provider"),
            SearchTarget(
                "Dictation shortcut",
                "dictée hotkey raccourci clavier",
                "hotkey",
                fallback="enabled",
                unavailable="Enable dictation to change its shortcut.",
            ),
            SearchTarget(
                "Dictation local model",
                "dictée modèle téléchargé whisper parakeet",
                "_model_combo",
                fallback="stt_provider",
                unavailable="Select Local to choose a dictation model.",
            ),
            SearchTarget("Dictation language", "dictée langue français english", "language"),
            SearchTarget(
                "Translate dictation to English",
                "dictée traduction anglais whisper",
                "translate",
                fallback="stt_provider",
                unavailable="Translation requires Local dictation with a Whisper model.",
            ),
        ),
    ),
    PageSpec(
        "wakeword",
        "Wake Word",
        "Workspace",
        "bolt",
        _WakeWordPage,
        "refresh",
        search=(
            SearchTarget(
                "Record a wake phrase",
                "mot réveil enregistrer phrase enrollment",
                "_setup_button",
                disclosure="requirements",
                fallback="requirements.button",
                unavailable="Install the required components and files before recording a phrase.",
            ),
            SearchTarget(
                "Wake word local files",
                "mot réveil encoder ten vad fichiers prérequis",
                "_encoder_row",
                disclosure="requirements",
            ),
            SearchTarget("Wake word sensitivity", "mot réveil sensibilité phrase", "_sensitivity"),
            SearchTarget(
                "Automatic hangup", "idle session timeout raccrocher silence", "_hangup_enabled"
            ),
            SearchTarget(
                "Quiet period",
                "idle timeout délai silence raccrocher",
                "_hangup_seconds",
                fallback="_hangup_enabled",
                unavailable="Enable automatic hangup to change its delay.",
            ),
        ),
    ),
    PageSpec(
        "providers",
        "Providers & keys",
        "Capabilities",
        "plug",
        ProvidersPage,
        "refresh",
        search=tuple(
            SearchTarget(
                f"{name} API key",
                f"{uses} clé clef credentials secret fournisseur",
                f"fields.{key}",
            )
            for key, name, uses in PROVIDERS
        ),
    ),
    PageSpec(
        "models",
        "Models & components",
        "Capabilities",
        "layers",
        LibraryPage,
        "refresh",
        search=(
            SearchTarget(
                "Download local models",
                "AI Models modèles télécharger whisper piper VAD TTS STT smart turn",
                "models.search",
                (("tabs", 0),),
            ),
            SearchTarget(
                "Install components",
                "backends extras installer composants dependencies dépendances",
                "components.search",
                (("tabs", 1),),
            ),
            *(
                SearchTarget(
                    model.name,
                    f"local model modèles télécharger {group.title} {model.detail}",
                    f"models.rows.{model.id}",
                    (("tabs", 0),),
                )
                for group in model_groups()
                for model in group.models
            ),
            *(
                SearchTarget(
                    f"{component.title} component",
                    f"install backend extra composant {component.description}",
                    f"components.rows.{component.extra}",
                    (("tabs", 1),),
                )
                for component in components()
            ),
        ),
    ),
    PageSpec(
        "integrations",
        "Integrations",
        "Capabilities",
        "sparkles",
        IntegrationsPage,
        "refresh",
        search=(
            SearchTarget(
                "Installed skills",
                "compétences activation instructions activer skills",
                "skills._my_skills_tab.search",
                (("tabs", 2),),
                fallback="skills._my_skills_tab.empty.button",
            ),
            SearchTarget(
                "Online skills · skills.sh",
                "compétences skills marketplace recherche installer en ligne",
                "skills._marketplace_tab._search_input",
                (("tabs", 2),),
            ),
            SearchTarget(
                "Skill sources",
                "sources compétences repository dépôt git local folder dossier",
                "skills.sources.search",
                (("tabs", 2),),
                fallback="skills.sources.empty.button",
            ),
            SearchTarget(
                "MCP servers",
                "serveurs outils integrations OAuth autorisation",
                "mcp.catalog.search",
                (("tabs", 0),),
                fallback="mcp.catalog.empty.button",
            ),
            SearchTarget(
                "CLI tools",
                "command line outils commandes integrations environment variables",
                "cli.catalog.search",
                (("tabs", 1),),
                fallback="cli.catalog.empty.button",
            ),
        ),
    ),
    PageSpec(
        "privacy",
        "Privacy & memory",
        "System",
        "user-group",
        PrivacyPage,
        search=(
            SearchTarget(
                "Conversation memory",
                "history conversations mémoire historique confidentialité",
                "conversation_memory",
            ),
            SearchTarget(
                "Session recording",
                "record audio enregistrement wav confidentialité",
                "recording_enabled",
            ),
            SearchTarget(
                "Recording folder",
                "output dossier destination enregistrement wav",
                "output_dir",
                fallback="recording_enabled",
                unavailable="Enable session recording to edit its output folder.",
            ),
        ),
    ),
    PageSpec(
        "diagnostics",
        "Diagnostics",
        "System",
        "waveform",
        DiagnosticsPage,
        "refresh",
        search=(
            SearchTarget(
                "Recorded audio",
                "recordings fichiers enregistrements WAV audio debug",
                "recordings.search",
                tabs=(("tabs", 0),),
            ),
            SearchTarget(
                "Pipeline capture",
                "diagnostics debug taps capture audio débogage stages",
                "capture.stages",
                tabs=(("tabs", 1),),
            ),
            SearchTarget(
                "Capture folder",
                "debug dossier output WAV",
                "capture.directory",
                tabs=(("tabs", 1),),
            ),
            SearchTarget(
                "Telemetry & tracing",
                "diagnostics traces métriques observabilité",
                "telemetry.provider",
                tabs=(("tabs", 2),),
            ),
            SearchTarget(
                "Collector endpoint",
                "OTLP OpenTelemetry export protocol service",
                "telemetry.otlp_endpoint",
                tabs=(("tabs", 2),),
                fallback="telemetry.provider",
                unavailable="Choose OpenTelemetry to configure the collector connection.",
            ),
        ),
    ),
    PageSpec(
        "about",
        "About",
        "System",
        "information-circle",
        lambda _: _AboutPage(),
        search=(
            SearchTarget("About RoomKit", "credits à propos version", "copy_info"),
            SearchTarget(
                "MIT license", "licence copyright", "license.button", disclosure="license"
            ),
        ),
    ),
)
