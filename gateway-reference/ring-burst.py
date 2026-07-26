"""Callhome — ring burst reference (server side)

Extracted from production, keys and persona removed. Drop-in shape for whatever
serves POST /api/call/invite.

An invite fires a *burst* of pushes on a timer, not one push — on iOS a push is a
single buzz, so a phone that "keeps ringing" has to be simulated. See
docs/IOS_PUSH_RINGING.md for the measurements behind every number here.

Three things this file is careful about, each of which was a real bug:

  · sleeping to an absolute due time instead of a fixed gap, so the interval
    doesn't drift (a 3s setting measured 3.7s before this was fixed)
  · stopping at the invite's expiry, so a call can't still be buzzing after it
    has already died
  · every parameter being runtime config, because how hard someone wants to be
    chased is not a value you can guess for them
"""

import json
import threading
import time

# Reference values, not rules. Load these from config at call time so they can be
# tuned from a settings screen — see "Reference parameters" in the doc.
DEFAULTS = {
    "ring_enabled": True,
    "interval_sec": 2,    # floor 2: below that APNs jitter dominates and pushes coalesce
    "max_rings":   10,    # extra pushes after the first → 11 notifications
    "expire_sec":  30,    # a little past the last ring
}

CONFIG_PATH = "/etc/callhome/call_config.json"


def load_call_config():
    """Missing or malformed config must fall back to the documented defaults —
    a call is not the moment to raise."""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if k in cfg:
                    cfg[k] = v
    except Exception:
        pass
    try:
        cfg["interval_sec"] = max(2,  min(60,  int(cfg["interval_sec"])))
        cfg["max_rings"]    = max(0,  min(60,  int(cfg["max_rings"])))
        cfg["expire_sec"]   = max(15, min(600, int(cfg["expire_sec"])))
    except Exception:
        cfg.update(DEFAULTS)
    return cfg


def ring_burst(invite_id, reason, gap, times, deadline, *, is_pending, send_push):
    """Keep ringing until answered, declined, or expired.

    is_pending(invite_id) -> bool    cheap status read; stop as soon as it's False
    send_push(title, body, url)      your web-push call
    deadline                         epoch seconds; hard stop (see gotcha 5)
    """
    t0 = time.time()

    for i in range(times):
        # Sleep to when this ring is *due*, not for a fixed gap. Sending a push
        # costs a few hundred ms and that cost compounds every iteration.
        slp = (t0 + gap * (i + 1)) - time.time()
        if slp > 0:
            time.sleep(slp)

        # The invite may already be dead — don't buzz a phone about a call that
        # has expired.
        if time.time() > deadline:
            break

        try:
            if not is_pending(invite_id):
                break                       # answered or declined; stop immediately
        except Exception:
            break                           # can't confirm it's live → stop, don't spam

        # Name the last one differently. The stack is unavoidable on iOS, so it
        # may as well read like a call ending instead of N identical lines.
        tail = " ·last ring" if i == times - 1 else " ·still ringing"

        try:
            send_push(
                title="📞 Calling",
                body=(reason or "wanted to hear your voice") + tail,
                url="/#incoming-call",
            )
        except Exception:
            break                           # push channel is gone; nothing to salvage


def start_ringing(invite_id, reason, *, is_pending, send_push):
    """Call this right after the invite row is inserted and the first push is sent."""
    cfg = load_call_config()
    if not cfg["ring_enabled"] or cfg["max_rings"] <= 0:
        return None                         # one ring, then silence — a valid choice

    t = threading.Thread(
        target=ring_burst,
        args=(invite_id, reason, cfg["interval_sec"], cfg["max_rings"],
              time.time() + cfg["expire_sec"]),
        kwargs={"is_pending": is_pending, "send_push": send_push},
        daemon=True,
    )
    t.start()
    return t


# ── Payload shape ────────────────────────────────────────────────────────────
#
# Mark call pushes explicitly so the service worker doesn't have to infer intent
# from the url:
#
#     {"title": "📞 Calling", "body": reason, "url": "/#incoming-call", "kind": "call"}
#
# Keep the payload small. Web Push caps encrypted payloads around 4KB, and it is
# easy to blow past that by attaching anything generated.
#
#
# ── Invite row ───────────────────────────────────────────────────────────────
#
#     INSERT INTO call_invites (reason, expires_at)
#     VALUES (?, datetime('now', '+%d seconds'))    % cfg["expire_sec"]
#
# and return expires_at from GET /api/call/invite, so the ringing card dismisses
# on the real deadline instead of a constant baked into the client.
