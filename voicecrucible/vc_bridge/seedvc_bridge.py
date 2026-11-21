# SPDX-License-Identifier: GPL-3.0-or-later
# This file is licensed under the GNU GPL v3 (or later), NOT under the MIT license of the rest of
# Voice Crucible, because it imports Seed-VC (GPL-3.0, https://github.com/Plachtaa/seed-vc).
# It runs as a separate process inside the separately installed Seed-VC folder and environment;
# Voice Crucible only talks to it through stdin/stdout (JSON lines with file paths).
"""Seed-VC bridge: convert audio files to a target voice on request.

Started as:  <seed-vc python> seedvc_bridge.py   (working directory = the Seed-VC folder)
Protocol (one JSON object per line):
  -> {"src": "in.wav", "ref": "voice.wav", "out": "out.wav", "steps": 50}
  <- {"ok": true}  or  {"error": "..."}
The first line written is {"ready": true} once the model is loaded.
"""

import json
import os
import sys
import traceback

PROTOCOL_OUT = sys.stdout
sys.stdout = sys.stderr  # Seed-VC prints progress; keep the protocol channel clean


def send(obj):
    """Write one protocol message."""
    PROTOCOL_OUT.write(json.dumps(obj) + "\n")
    PROTOCOL_OUT.flush()


def main():
    sys.path.insert(0, os.getcwd())
    import numpy as np
    import soundfile as sf
    from seed_vc_wrapper import SeedVCWrapper

    vc = SeedVCWrapper()
    send({"ready": True})
    for raw in sys.stdin:
        try:
            req = json.loads(raw)
            gen = vc.convert_voice(req["src"], req["ref"], diffusion_steps=int(req.get("steps", 50)),
                                   f0_condition=True, auto_f0_adjust=True, stream_output=False)
            try:
                while True:
                    next(gen)
            except StopIteration as stop:
                y = np.asarray(stop.value, np.float32)
            sf.write(req["out"], y, 44100)
            send({"ok": True})
        except Exception as e:  # report and keep serving
            traceback.print_exc()
            send({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
