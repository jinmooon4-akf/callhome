# Gateway reference

Extracted, annotated reference implementations of the marker-parsing layer (Node.js). These are the exact patterns running in production, with persona and keys removed. Full pluggable gateway lands with the first release — until then, these are meant to be read and transplanted into your own gateway.

- `markers.js` — dial / hangup / dnd parsing on the finalized reply text
- `escalation.js` — the silence→call decision block, with its guardrails
- `ring-burst.py` — the timed push sequence that makes a phone keep ringing, with drift-free scheduling and its stop conditions (see [`docs/IOS_PUSH_RINGING.md`](../docs/IOS_PUSH_RINGING.md))
