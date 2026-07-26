// Callhome — page-side reference (service worker registration + notification cleanup)
//
// Two small things the page must do, both of which are easy to leave out and
// each of which quietly breaks ringing. See docs/IOS_PUSH_RINGING.md.

// ─────────────────────────────────────────────────────────────────────────────
// 1. Registration — register() does NOT check for a new sw.js
// ─────────────────────────────────────────────────────────────────────────────
// The browser decides when to look for a new worker, and an installed iOS PWA
// decides "almost never". Symptom: you deploy sw.js, reload, force-quit the app
// several times, and pushes are still handled by last week's code — so every
// change you make appears to do nothing.

async function initServiceWorker() {
  if (!('serviceWorker' in navigator)) return null;

  const reg = await navigator.serviceWorker.register('/sw.js');

  // The line that actually ships your changes.
  try { await reg.update(); } catch (e) {}

  // A PWA can stay "open" for days. Re-check whenever it comes back to the front.
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { try { reg.update(); } catch (e) {} }
  });

  await navigator.serviceWorker.ready;
  return reg;
}

// The worker shouts when a call push arrives, so an open page shows the ringing
// card immediately instead of waiting out its polling interval.
navigator.serviceWorker && navigator.serviceWorker.addEventListener('message', function (e) {
  if (e.data && e.data.type === 'incoming-call') { showRingingCardSoon(); return; }
  if (e.data && e.data.type === 'navigate' && e.data.url) { navigateTo(e.data.url); }
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. Cleanup — close the whole burst when the call resolves
// ─────────────────────────────────────────────────────────────────────────────
// iOS does not collapse notifications by tag, so one call leaves a stack of
// them. Leaving that stack behind after the call ended is the thing people
// actually complain about.

function clearCallNotifications() {
  try {
    if (!navigator.serviceWorker) return;
    navigator.serviceWorker.ready.then(function (reg) {
      if (!reg.getNotifications) return;
      reg.getNotifications({ tag: 'incoming-call' }).then(function (ns) {
        ns.forEach(function (n) { try { n.close(); } catch (e) {} });
      }).catch(function () {});
    }).catch(function () {});
  } catch (e) {}
}

// Call it from every path that ends a call: answered, declined, timed out.
// Putting it inside whatever "stop the ringing UI" function you already have
// covers all three at once.
function stopRinging() {
  clearInterval(ringToneTimer);
  clearInterval(vibrateTimer);
  clearTimeout(autoDismissTimer);
  clearCallNotifications();          // ← here
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. Auto-dismiss on the real deadline, not a hardcoded one
// ─────────────────────────────────────────────────────────────────────────────
// Have GET /api/call/invite return expires_at, then trust it. A constant here
// drifts out of sync with the server the first time anyone tunes the timings.

function showRingingCard(invite) {
  renderCard(invite);
  startRinging();

  let ms = 30000;                                   // fallback only
  try {
    if (invite.expires_at) {
      // server stores UTC as "YYYY-MM-DD HH:MM:SS"
      const t = Date.parse(String(invite.expires_at).replace(' ', 'T') + 'Z');
      if (t) ms = Math.max(5000, t - Date.now());
    }
  } catch (e) {}

  autoDismissTimer = setTimeout(hideRingingCard, ms);
}
