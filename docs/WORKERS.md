# Several machines (workers)

One machine runs the **coordinator** (queue, results, watcher). Any number of machines run a **worker**
(they render). The coordinator machine can be a worker too.

## Pair a new worker (once per machine)

1. Coordinator machine: `coordinator.cmd` is running. The pairing code is shown in its window and in the
   watcher (**New pairing code**). A code is valid for 10 minutes, works once and is burnt after 5 wrong tries.
2. New machine: install (`setup.cmd`), then **`pair.cmd`** and type the code. The coordinator is found on the
   local network automatically. If not (firewall, separate network segment):
   `crucible.cmd pair <code> --coordinator <coordinator's IP or name>`.
3. Start **`worker.cmd`**. From now on just start `worker.cmd`; the pairing stays, also when IP addresses change.

To remove a worker: watcher → **Remove**. It has to pair again to work for this coordinator.

## How it stays safe

- The worker opens **no network port**; it only connects out to the coordinator it is paired with.
- The connection is encrypted (TLS). The worker remembers the coordinator's certificate at pairing and
  refuses any other ("SECURITY: … unknown certificate" – e.g. after reinstalling the coordinator: pair again).
- The coordinator only accepts computers on the local network, and only paired workers.
- Workers render and send audio back – they run no commands and write nothing outside their folder.
- Details: [SECURITY.md](SECURITY.md).

## Firewall

Windows asks once when the coordinator starts: allow **private networks** only. Needed on the coordinator:
TCP 5130 (worker API) and UDP 5131 (finding the coordinator). Workers need nothing incoming.

## Dropping out is fine

If a worker is stopped (Ctrl+C) it hands its unfinished lines back. If it crashes or loses the network, its
lines go back to the queue after 10 minutes. A restarted worker picks up where it left off.

## Updating several machines

Optional, per worker: in that worker's `voicecrucible.toml` set

```toml
[worker]
allow_update_requests = true
```

Then the watcher's **Update workers** button asks those workers to update themselves from GitHub. Each worker
downloads the release itself and checks its signature – the coordinator sends no code. A worker updates
between two jobs and restarts on its own. Update the **coordinator last** (`crucible.cmd update` warns if a
worker is still on an older version).
