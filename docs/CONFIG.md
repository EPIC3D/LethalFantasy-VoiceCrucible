# Settings

Settings live in **`voicecrucible.toml`** in the Voice Crucible folder. It does not exist at first – every
setting has a default. Copy `config\voicecrucible.example.toml` (every key commented) to
`voicecrucible.toml` and change only what you need. Check it with `crucible.cmd config`: unknown keys and
wrong values are reported with section and name.

| Section | What it is for |
|---|---|
| `[paths]` | work, output and log folders (relative to the Voice Crucible folder). They may not point into the game's `BepInEx` folder: Voice Crucible never writes into the game, so finished voices there are never overwritten – copy `output\voices` into the game yourself. |
| `[render]` | `language` (voice pack folder, e.g. `en`, `hu`, `ja`), `engine` (`chatterbox`, `qwen`, `qwen_vc`), `characters` (pack folders to render; empty = all), `profile` (installed profile name or a folder path) |
| `[checks]` | which quality checks run and their limits (`min_similarity`, `min_mos`, `max_f0`, …), `max_attempts` per line |
| `[director]` | acting directions: `mode` = `none` / `file` / `api`; for `api`: `api_base`, `model`, `api_key_env` (the key itself is read from that environment variable – never put keys in the file) |
| `[coordinator]` | ports (5130 API, 5131 discovery, 5132 watcher), `max_batch` |
| `[worker]` | `name`, `coordinator` (address if it is not found automatically), `max_batch`, `allow_update_requests`, `seedvc_dir` |

## Profiles

Characters, reference voices, acting notes, pronunciation and the director brief live in a **profile**
(`profiles\<name>\`, chosen with `[render] profile`, default `lethalfantasy`). You create it from the
template (`crucible.cmd profile new <name>`); program updates never change it – see [PROFILES.md](PROFILES.md).

## Other languages

Set `[render] language` to the plugin's folder name (`hu`, `ja`, `zh`, `es`, `fr`, `pt-BR`, `ru`, or a new
one) and pass the translated texts: `crucible.cmd render --lines <export> --texts <file.jsonl>` (one
`{"key": ..., "text": ...}` per line, e.g. from the game's Weblate). Chatterbox speaks English only; Qwen
speaks several languages.
