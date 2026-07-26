# PWA reference

The client half of ringing. Extracted from production, keys and persona removed —
meant to be read and transplanted, not dropped in as a dependency.

- `sw.js` — service worker: call pushes take their own branch, the burst is closed
  as a group when the call ends, and the worker reports its own version so you can
  tell which build is actually on the phone
- `register-and-clear.js` — the page side: `registration.update()` (without it your
  service worker changes never ship on iOS), notification cleanup on every path that
  ends a call, and auto-dismiss driven by the server's `expires_at`

Both files assume the burst described in
[`docs/IOS_PUSH_RINGING.md`](../docs/IOS_PUSH_RINGING.md) — read that first. The short
version: on iOS a push is a single buzz, `tag` does not replace notifications, and
`renotify` / `vibrate` / `requireInteraction` are ignored. Ringing is therefore a timed
sequence of pushes plus disciplined cleanup, and the parts of the spec you would reach
for first are the parts that do nothing.

Server side lives in [`gateway-reference/ring-burst.py`](../gateway-reference/ring-burst.py).
