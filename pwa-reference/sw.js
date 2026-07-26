// Callhome — service worker reference (push side)
//
// Extracted from production, persona and keys removed. The parts that matter for
// ringing are marked ①–④; see docs/IOS_PUSH_RINGING.md for why each exists.
//
// ① a version string that phones home, so you know which build is on the device
// ② call pushes take a different branch from ordinary ones
// ③ tag can't replace on iOS, but it can identify the group
// ④ tapping any notification in the burst closes all of them

// ① Bump this on every change to this file. Without it you are guessing which
//    build is on the phone — and iOS PWAs hold on to old workers for a long time.
const SW_VERSION = '2026-07-26-ring3';

// Fire-and-forget telemetry. Must never block or reject the notification:
// if the push handler fails to show something, iOS may drop the subscription.
// The trailing timestamp defeats server-side dedup of identical values.
function swPing(what) {
  try {
    return fetch('/api/events?type=swpush&value=' +
      encodeURIComponent(SW_VERSION + '|' + what + '|' + Date.now())).catch(function () {});
  } catch (e) {
    return Promise.resolve();
  }
}

self.addEventListener('push', function (event) {
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'Callhome';

  // ② The server tags call pushes with kind:'call'. The url check is a fallback
  //    for payloads emitted by older builds.
  const isCall = data.kind === 'call' ||
                 String(data.url || '').indexOf('incoming-call') > -1;

  const options = {
    body: data.body || '',
    icon: '/icon.png',
    badge: '/icon.png',
    data: { url: data.url || '/' },
    requireInteraction: isCall,   // ignored on iOS; works on Android/desktop
    silent: false
  };

  if (isCall) {
    // ③ On iOS this does NOT collapse the burst into one notification —
    //    WebKit doesn't implement tag replacement. Keep it anyway:
    //    it is what lets us find and close the whole group later, and on
    //    Android/desktop it does collapse the way the spec says.
    options.tag = 'incoming-call';
    options.renotify = true;                    // ignored on iOS
    options.vibrate = [400, 200, 400, 2000];    // ignored on iOS
  }

  event.waitUntil(Promise.all([
    swPing(isCall ? 'call' : 'normal'),
    self.registration.showNotification(title, options),
    // If a window is open — even in the background — tell it now instead of
    // letting it discover the invite on its next poll.
    isCall
      ? self.clients.matchAll({ type: 'window', includeUncontrolled: true })
          .then(function (cs) {
            cs.forEach(function (c) {
              try { c.postMessage({ type: 'incoming-call' }); } catch (e) {}
            });
          })
          .catch(function () {})
      : Promise.resolve()
  ]));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  const url = event.notification.data.url || '/';

  // ④ A call leaves a stack of notifications on iOS. Tapping any one of them
  //    should clear the whole stack — otherwise the burst is still sitting in
  //    Notification Center long after the call ended, which is what actually
  //    makes people disable the feature.
  if (String(url).indexOf('incoming-call') > -1 && self.registration.getNotifications) {
    event.waitUntil(
      self.registration.getNotifications({ tag: 'incoming-call' })
        .then(function (ns) {
          ns.forEach(function (n) { try { n.close(); } catch (e) {} });
        })
        .catch(function () {})
    );
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      for (const client of list) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.postMessage({ type: 'navigate', url: url });
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});

// Take over immediately rather than waiting for every tab to close.
// Without these, reg.update() installs the new worker but the old one keeps
// handling pushes.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());
