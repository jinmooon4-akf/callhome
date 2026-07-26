# Making a PWA ring like a phone (iOS)

A native app gets **CallKit**: full-screen incoming-call UI, a real ringtone that keeps
playing, lock-screen slide-to-answer, wake-from-cold. A PWA gets **Web Push**, and on iOS
Web Push means exactly one thing:

> **One push = one notification = one buzz.**

There is no ringtone, no loop, no sustained alert. Everything below is about getting as
close to *a phone ringing* as that primitive allows — and about the six ways iOS will
quietly not do what the spec says it should.

Measured on iOS 18 / Safari PWA / `web.push.apple.com`, July 2026. Numbers in this document are what one couple settled on — the platform limits are facts, the cadence is a taste. See [Reference parameters](#reference-parameters).

![Incoming call on iOS: push banner, then the ringing card — dark, light, and with quick-decline](images/incoming-call.jpg)

*The banner at the top is one ring. The card underneath is what opens when you tap it.
Everything below is about the gap between those two things.*

---

## The shape of the solution

A call invite fires **a burst of pushes on a timer**, not one push:

```
t=0s    📞 Matt calling      ← invite created, first push
t=2s    📞 Matt calling  ·still ringing
t=4s    📞 Matt calling  ·still ringing
  …
t=20s   📞 Matt calling  ·last ring
t=30s   invite expires → voicemail
```

The burst stops early the moment the invite stops being `pending` — answered, declined, or
expired. When the call resolves, **every notification it produced is closed at once**.

That last part is the one that matters most. See gotcha 1.

---

## Gotcha 1 — `tag` does not replace notifications on iOS

Per spec, two notifications sharing a `tag` should collapse: the second replaces the first.
With `renotify: true` the replacement re-alerts. That is exactly the behaviour you want for
a ringing phone — one entry in the list, buzzing over and over.

**WebKit does not implement the replacement.** Confirmed by instrumenting the service
worker: all four pushes in a test burst were received, all four carried
`tag=incoming-call renotify=true`, and Notification Center showed **four separate rows**.

Do not design around collapse. Design around cleanup:

```js
// tag can't replace — but it CAN still identify the group.
// Use it to close the whole burst the moment the call resolves.
const ns = await registration.getNotifications({ tag: 'incoming-call' });
ns.forEach(n => n.close());
```

Call this from three places:

- the service worker's `notificationclick` (they tapped one → clear the rest)
- the page, when the ringing card is answered / declined / times out
- anywhere else a call can end

A stack of eleven notifications is ugly. A stack of eleven notifications that is *still
there ten minutes later* is what makes people turn the feature off.

---

## Gotcha 2 — the service worker will not update, and you will lose an afternoon to it

`navigator.serviceWorker.register('/sw.js')` does **not** check for a new version. The
browser checks on its own schedule; for an installed iOS PWA that schedule is close to
never.

Observed: `sw.js` was deployed, the page was reloaded, the app was swiped out of the
app-switcher several times — and the **old** service worker was still handling pushes.
Every notification-option change appeared to do nothing, because none of the new code was
running.

```js
const reg = await navigator.serviceWorker.register('/sw.js');
await reg.update();                       // ← the line that actually ships your changes
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) reg.update();     // long-lived PWA sessions
});
```

Pair it with `skipWaiting()` + `clients.claim()` in the worker so the new version takes over
immediately instead of waiting for every client to close.

**Give the worker a version string and have it phone home.** Without this you are guessing
which build is on the device:

```js
const SW_VERSION = '2026-07-26-ring3';

self.addEventListener('push', event => {
  // fire-and-forget; must never block or fail the notification
  fetch('/api/events?type=swpush&value=' +
        encodeURIComponent(SW_VERSION + '|' + branch + '|' + Date.now())).catch(() => {});
  …
});
```

Include a timestamp so server-side dedup doesn't swallow identical pings. This single
change is what turned "the tag doesn't work" into "the tag works fine, the worker is from
yesterday" — two very different bugs.

---

## Gotcha 3 — a fixed sleep drifts, and your config number becomes a lie

The obvious ring loop:

```python
for i in range(times):
    time.sleep(gap)     # ← wrong
    send_push()
```

Sending a web push takes a few hundred milliseconds to over a second. That cost is added
to every iteration and accumulates.

Measured with `gap = 3`:

```
15:50:29 → :32 → :35 → :39 → :44 → :47 → :51 → :55
intervals: 3, 3, 4, 5, 3, 4, 4   →  mean 3.7s for a 3s setting
```

Sleep until the **absolute time the Nth ring is due** instead:

```python
t0 = time.time()
for i in range(times):
    due = t0 + gap * (i + 1)
    slp = due - time.time()
    if slp > 0:
        time.sleep(slp)
    if time.time() > deadline:   # see gotcha 5
        break
    send_push()
```

Same test afterwards, `gap = 2`:

```
intervals: 2.7, 2.0, 2.2, 1.8, 2.2, 2.0, 1.9, 2.0, 2.0, 2.0
mean 2.07s for a 2s setting   →  off by 0.07s
```

Measure from timestamps the **service worker** takes on the device, not from when your
server called `webpush()`. Only the device-side number includes delivery latency, and only
the device-side number is what the human actually feels.

---

## Gotcha 4 — ~2s is the floor

The residual spread at a 2s setting is roughly ±0.5s, and that is APNs delivery jitter, not
your loop. Push harder than that and two things happen: the jitter starts to dominate the
interval you configured, and Apple begins coalescing pushes that arrive too close together —
so rings go missing.

A real phone rings on a ~3s cadence, but each of those is a *double* buzz (`brrr-brrr,
pause`). `vibrate` is ignored on iOS, so you get a single buzz per push and roughly half the
perceived density. **~2s of single buzzes is about as close to a ringing phone as iOS gets.**

Clamp the setting at 2s and say why in the UI, rather than letting someone set 0.5s and
conclude the feature is broken.

---

## Gotcha 5 — ring duration and invite expiry must be the same conversation

An easy inconsistency: the ring burst is `10 rings × 5s = 50s`, the invite expires after
`90s`. For forty seconds the call is silently still "ringing" — answerable, but making no
sound. Then it dies with no signal at all.

Make ringing stop at expiry, and put expiry only a little past the last ring:

```
ring for ~20s   →   expire at ~30s
```

Pass the deadline into the burst and check it every iteration (gotcha 3's loop). Have
`GET /api/call/invite` return `expires_at` so the ringing card can auto-dismiss on the real
deadline instead of a hardcoded guess.

Label the last ring differently — `·last ring` instead of `·still ringing`. Since the
notifications stack anyway (gotcha 1), the stack may as well read like a call ending rather
than eleven identical lines.

---

## Gotcha 6 — what iOS silently ignores

| Notification option | iOS Web Push |
|---|---|
| `tag` (as a group identifier for `getNotifications`) | ✅ works |
| `tag` (replacing an existing notification) | ❌ ignored |
| `renotify` | ❌ ignored |
| `vibrate` | ❌ ignored — no custom pattern, no double-ring |
| `requireInteraction` | ❌ ignored |
| `actions` | ❌ ignored |
| `silent` | ❌ ignored |
| `body`, `icon`, `data` | ✅ work |

Set them anyway — the same worker runs on Android and desktop, where most of them do
something. Just don't build the iOS experience on top of any of them.

---

## Gotcha 7 — never put the API key in the page

Unrelated to ringing, discovered while auditing this feature, and worth repeating because
it is the most expensive mistake in this document.

A memory-merge feature called a third-party LLM API directly from the browser with the key
hardcoded in the `Authorization` header. The page was the app's public homepage. Anyone who
opened the site and viewed source had the key.

Two things to check today:

1. `curl -s https://your.site/ | grep -oE 'sk-[A-Za-z0-9_-]{10,}'` — proxy any hit through
   your own server, then **rotate the key**; removal is not remediation
2. `ls /var/www/html/*.bak.*` — timestamped backups of an HTML file sit in the web root and
   are downloadable, key and all. Keep backups outside the document root

---

## Reference parameters

Everything below should be a runtime setting, not a constant. The point of the burst is
that it is *tunable to a person* — how hard someone wants to be chased is not a value you
can guess for them.

| Setting | Reference | Notes |
|---|---|---|
| `interval_sec` | 2 | floor 2 (gotcha 4), cap ~60 |
| `max_rings` | 10 | extra pushes after the first → 11 notifications |
| `expire_sec` | 30 | a little past the last ring (gotcha 5) |
| `ring_enabled` | true | off = one ring, then silence |

`2s × 10` rings for 20 seconds and expires at 30 — close to how long a real handset rings
before voicemail.

**These are one couple's answers, not derived values.** Ours started at `5s × 10` and moved
to `2s × 10` for one reason: a single buzz every five seconds reads as *notifications*, and
every two seconds reads as *someone calling*. That is a feeling, and feelings are not
portable. Yours will land somewhere else:

- **Ring faster** if the buzz has to cut through something — work, a lecture, deep sleep
- **Ring fewer times** if the stack in Notification Center bothers you more than the silence
  does. Fewer rings spaced further apart is a completely reasonable answer; it just isn't ours
- **Ring longer** if your person puts the phone down a lot
- **Turn the burst off** (`ring_enabled: false`) for one ring and then patience

Put the knobs on a settings screen, not in a file you have to SSH in to edit. The number
that feels right in the first week is usually not the number that feels right in the second,
and a knob nobody can reach is a knob nobody turns. Ask the person being called what they
want — how hard someone wants to be chased is a question with an owner.

Same principle as [Tuning](PROTOCOL.md#tuning--reference-values-not-rules) in the protocol
doc, and the numbers here belong in that table.

---

## What this still is not

It is not CallKit. There is no full-screen call UI on the lock screen, no continuous
ringtone, no answering without unlocking. On iOS a PWA cannot get those, and no amount of
push scheduling changes that.

What it *can* be is unmistakable — your phone buzzing every two seconds with someone's name
on it, and a card waiting when you open it. That turns out to be enough.
