# Troubleshooting

First run `crucible.cmd diagnose` – it collects versions, GPU, settings and recent log lines (personal data
removed) into `logs\diagnose.txt`. Logs of every command are in `logs\`.

| Problem | What to do |
|---|---|
| Setup: "driver too old" | Install NVIDIA driver 570 or newer, run `setup.cmd` again. |
| Setup: "not enough free space" | Free space or move the folder to another drive; `runtime\uv-cache\` can be deleted after setup. |
| Setup: a step failed | The exact error is in `logs\setup_*.log`. Running `setup.cmd` again continues; finished downloads are not repeated. |
| `pair`: "no coordinator found" | Is `coordinator.cmd` running? Did Windows allow it on private networks? Try `crucible.cmd pair <code> --coordinator <IP>`. |
| `pair`: "code wrong or expired" | Codes last 10 minutes and work once – get a new one in the watcher. |
| Worker: "SECURITY: … unknown certificate" | The coordinator was reinstalled or its `work\coordinator` folder deleted: pair again. If not, someone else answers on the network – stop and check. |
| Worker: "not paired or pairing revoked" | Pair again (`pair.cmd`). |
| Worker: "too old for the coordinator" | Update the worker (`crucible.cmd update`). |
| Worker: "GPU out of memory" | Handled automatically (smaller batches). If it repeats, lower `[worker] max_batch` or close other GPU programs. |
| `render`: "profile … does not exist" | Check `[render] profile` in `voicecrucible.toml` (the bundled default is `lethalfantasy`), or create the profile ([PROFILES.md](PROFILES.md)). |
| `render`: "no reference voice for …" | Put a clip for that character into the profile's `voices\` folder, named as in `characters.json`. |
| `render`: "new character … found" | A new speaker in the game export was added to `characters.json`; check its `folder` and add a reference clip. |
| Rendered files land in a folder the plugin does not read | Set the character's `folder` in `characters.json` to the plugin's folder name (LethalFantasy: `AKIPO`, `RED`, `BLUE`; see `plugin_folders.json`). |
| `qwen_vc`: "Seed-VC … not found" | Install the Seed-VC component (`setup.cmd`, answer yes) or use another engine. |
| Many lines fail a check | See `output\report.tsv` for the reasons. Strong emotions sometimes fail the voice match – retries usually fix it. |
| Watcher page shows 404 | The watcher is http://127.0.0.1:5132 on the coordinator computer (`watcher.cmd`), not port 5130 and not on a worker. |
| Update: "no signed program zip" / HTTP 404 | No signed release available yet; update by hand from GitHub. |

Still stuck? Open an issue on GitHub and paste `logs\diagnose.txt` (see the README, "Reporting bugs").

## Watcher "not reachable", workers go offline at random, connections reset

Programs that filter network traffic on your PC – ad blockers such as AdGuard, antivirus "web protection",
VPN or firewall tools – can cut off connections to `http://127.0.0.1:5132` (watcher) or between workers and the
coordinator (ports 5130 TCP and 5131 UDP on the local network). Typical signs: the watcher page shows
"Coordinator not reachable" for a moment, a worker shows "no contact since …", or a log says
"connection reset" / "WinError 10054".

- Allow `127.0.0.1`, the Voice Crucible folder (its `runtime\venv\Scripts\python.exe`) and the local network
  ports in that program, or pause it briefly to check whether it is the cause.
- Windows Firewall asks once when the coordinator starts: allow it for **private** networks.
