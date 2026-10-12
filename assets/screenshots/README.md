# Interface gallery

Real PySide6 widgets captured from the current source, with fictional demo conversations
and credentials. These illustrate the upcoming release, not necessarily the latest binary.

| View | Dark | Light |
| --- | --- | --- |
| Home | [Open](home-dark.png) | [Open](home-light.png) |
| Text and image conversation | [Open](conversation-dark.png) | [Open](conversation-light.png) |
| Live voice and tool activity | [Open](live-dark.png) | [Open](live-light.png) |
| Conversation history | [Open](history-dark.png) | [Open](history-light.png) |
| Conversation settings | [Open](settings-dark.png) | [Open](settings-light.png) |
| MCP HTTP authentication | [Open](authentication-dark.png) | [Open](authentication-light.png) |

Regenerate from the repository root using the existing development environment:

```sh
.venv/bin/python scripts/capture_screenshots.py
```

The script isolates settings, the secret store and the app data directory. It opens no
microphone, camera, provider connection or MCP server. Text, waveform levels, tool results
and the original trail sketch are demonstration content, not a live session or benchmark.
Screenshots are captured at 2× resolution. They can also be written elsewhere with `--output`.

The website gallery lives in `roomkit-live/roomkit-website`, under `roomkit-ui/`.
Copy these PNGs into its `roomkit-ui/screenshots/` directory after regenerating, and
review both themes and mobile layouts before publishing.
