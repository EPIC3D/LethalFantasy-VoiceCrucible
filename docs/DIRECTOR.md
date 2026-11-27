# Acting directions (the AI director)

Optional. Without a director every line is voiced from the game's expression (an emotion table) – that works. With a
director, a language model reads each scene and writes short acting notes per line: what happens, why the character
says it, how it should sound, what to avoid, an energy level (1–5) and a pace. The engines use these notes – e.g.
"Get away from me!" during a growth spurt becomes an urgent, caring warning instead of rejection.

- Directions are made **once** and stored in `work\directions.json`. Every engine and every later render reuses them;
  after a game update only the new lines are directed.
- `crucible direct --render` starts rendering the directed scenes while the director is still working on the rest.
- Random alternatives of a scene (the game plays only one of them) are sent as separate alternatives, so the model
  does not read them as one conversation.

Any OpenAI-compatible chat API works: a **local** model (free, private) or a **cloud** model (your own account).

## Local: Ollama (recommended)

1. Install Ollama from <https://ollama.com> on a PC with an NVIDIA GPU.
2. Download a model: `ollama pull qwen3:14b` (16 GB card) – or `qwen3:8b` on an 8 GB card (weaker directions).
3. In `voicecrucible.toml`:

   ```toml
   [director]
   mode = "api"
   api_base = "http://localhost:11434/v1"   # Ollama on another PC: http://<that-pc>:11434/v1
   model = "qwen3:14b"
   context_length = 6144                      # VRAM for the context; 4096-6144 is enough
   ```

4. Check that the model runs fully on the GPU: while directing, `ollama ps` must show **100% GPU**. If part of it
   spills into system RAM it gets many times slower – lower `context_length` or use a smaller model.
5. Run `crucible.cmd direct --lines <export folder>` (add `--render` to render while directing).

Ollama on another PC: set the environment variable `OLLAMA_HOST=0.0.0.0` there (and allow port 11434 in its firewall
for the private network). Measured: `qwen3:14b` on a 16 GB card directs the whole game in about 5 hours
([GPU.md](GPU.md)). The model is unloaded from the GPU when directing ends, so a worker on that PC can render.

LM Studio works the same way (`api_base = "http://localhost:1234/v1"`, its model name).

## Cloud API (untested)

> **Untested:** the code path is the same as for local servers and is covered by tests against a fake server, but it
> has not been tried with a real cloud account yet. Reports welcome.

Any service with an OpenAI-compatible chat endpoint. The **key is never written in a file**: put it in an
environment variable (default name `VOICECRUCIBLE_API_KEY`, or set `api_key_env`):

```bat
setx VOICECRUCIBLE_API_KEY "your-key"
```

(open a new window afterwards). Examples – check each provider's current model names:

| Provider | `api_base` | `model` (example) |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` |
| OpenRouter (many models with one key) | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4.5` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.5-flash` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Anthropic | `https://api.anthropic.com/v1` | `claude-sonnet-4-5` |

**Privacy:** with a cloud model the game's text leaves your PC. `crucible direct` says where it is going and asks
before anything is sent. A local model keeps everything on your network.

**Cost:** the whole game is about 6,300 lines, sent in batches of 8 with the scene as context – a few dollars on most
models, less on the cheap ones. Watch your provider's usage page during the first run.
