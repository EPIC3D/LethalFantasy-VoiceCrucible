# Changelog

## 0.1.0b2 – unreleased

- Update check: GitHub tags (`v0.1.0-beta.2`) are compared with the program version (`0.1.0b2`) correctly.
  In 0.1.0b1 `crucible update` offers the same version again and then refuses it (harmless).
- Workers asked to update while already on the latest version report "up to date" instead of an error.

## 0.1.0b1 – 2026-11-21 (first beta)

Tested on Windows 11 with NVIDIA RTX 40 and RTX 50 series cards, against LethalFantasy beta 1.0.3.

- Coordinator + any number of workers on the local network: pairing code, TLS with pinned certificate,
  discovery (DHCP-safe), leases (lines of a lost worker go back to the queue), watcher web page.
- Engines: Chatterbox (default packs), Qwen3-TTS, Qwen3-TTS + Seed-VC (acting packs; Seed-VC runs as a
  separate GPL program).
- Quality checks on every take: words (Whisper), voice match (resemblyzer), audio quality (UTMOS), pitch;
  failed lines are rendered again.
- LethalFantasy profile: reads the plugin's line export, he/she/they variants, never voices player choices or
  narration, new speakers added automatically, any pack language.
- Optional AI director (any OpenAI-compatible API, local or cloud) writing an editable `directions.json`.
- Setup: everything inside the install folder, download list with sources/licenses/sizes shown first, GPU and
  drive checks, `INSTALLED.txt`; `crucible diagnose` for bug reports; signed manual updates with rollback;
  optional update requests from the watcher (workers update themselves, coordinator last).
