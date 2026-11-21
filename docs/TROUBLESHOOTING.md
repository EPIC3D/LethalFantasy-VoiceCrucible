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
| `render`: "profile … is not installed" | Install the profile pack (`crucible.cmd profile install <zip>`) or check `[render] profile`. |
| `render`: "no reference voice for …" | The profile has no voice file for that character – install a newer profile pack, or add a clip and set it in `characters.json`. |
| `render`: "new character … found" | A new game version added a speaker; give it a reference voice in `characters.json`. |
| `qwen_vc`: "Seed-VC … not found" | Install the Seed-VC component (`setup.cmd`, answer yes) or use another engine. |
| Many lines fail a check | See `output\report.tsv` for the reasons. Strong emotions sometimes fail the voice match – retries usually fix it. |
| Watcher page shows 404 | The watcher is http://127.0.0.1:5132 on the coordinator computer (`watcher.cmd`), not port 5130 and not on a worker. |
| Update: "no signed program zip" / HTTP 404 | No signed release available yet; update by hand from GitHub. |

Still stuck? Open an issue on GitHub and paste `logs\diagnose.txt` (see the README, "Reporting bugs").
