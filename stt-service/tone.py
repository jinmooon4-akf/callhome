#!/usr/bin/env python3
"""Tone cues from a rolling personal baseline.

The previous version compared acoustic features against fixed constants. That
does not work, and we have the measurements to say so — see docs/TONE_CUES.md.
The short version, from 85 real recordings of one speaker:

  · `pitch_var > 60` was true in 96.5% of clips. Mandarin is tonal; lexical tone
    dominates F0 variance, so the condition carried no information at all
  · the `pause > 0.44` threshold sat on that speaker's median (0.42) — not a
    detector, a coin flip
  · two of the seven phrases required `pitch > 250`; her median was 195.5, so
    they were dead code
  · `energy` thresholds are absolute, and absolute energy is a property of the
    microphone and the distance to the mouth, not of the person

Four phrases covered 90% of all output, and one of those four was the "nothing
matched" fallback.

The fix is not better constants. **There are no good constants.** A tone cue is
only meaningful relative to how this person usually sounds, so we keep a rolling
baseline of their own recordings and describe where the current clip sits in it.

Two consequences worth keeping:

  · the baseline follows them. New microphone, different room, a cold — it drifts
    along instead of going wrong
  · saying nothing is a valid answer, and a common one. A wrong tone cue is worse
    than no tone cue: the companion reads it as evidence and misjudges the mood.
    Around a third of clips should produce no cue at all
"""
import json
import os
import threading

BASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")
MAX_KEEP = 400          # rolling window
MIN_SAMPLES = 25        # per-feature: don't rank against fewer than this
_LOCK = threading.Lock()

# feature -> percentile thresholds -> phrase.
# Cutoffs at 12/88 (and 4/96 for the strong tier): only speak when the clip
# really sits at one end of this person's own range. Earlier drafts used 20/80
# and 32/68, which labelled 94% of clips — a caption on every sentence trains
# the reader to skip the line.
VOCAB = {
    "energy": {
        "low":  [(4, "声音很轻，几乎气音"), (12, "声音比平时轻")],
        "high": [(96, "嗓门比平时大很多"), (88, "声音比平时响")],
    },
    "pause": {
        "low":  [(5, "一口气说完，中间没停"), (14, "说得比平时连贯")],
        "high": [(95, "停顿很多，话是断着说的"), (86, "停顿比平时多")],
    },
    "pitch": {
        "low":  [(5, "音调压得比平时低"), (14, "声音比平时沉")],
        "high": [(95, "音调比平时高不少"), (86, "音调偏高")],
    },
    "pitch_var": {
        # Relative only. Against a constant this is meaningless in a tonal
        # language — the four tones inflate it for everyone.
        "low":  [(5, "语调很平，没什么起伏"), (14, "语调比平时平")],
        "high": [(95, "语调起伏比平时大"), (86, "语调有起伏")],
    },
    "rate": {
        "low":  [(5, "说得很慢，字和字之间拖着"), (14, "语速比平时慢")],
        "high": [(95, "语速很快"), (86, "说得比平时快")],
    },
    "dur": {
        "low":  [],
        "high": [(93, "一口气说了很长一段")],
    },
    # `tail` was first written with absolute cutoffs — the same mistake this
    # module exists to fix, and it failed on the first test run: trailing
    # silence pinned the ratio near zero and every clip came back "trailed off".
    # It is measured over the voiced span now, and ranked like everything else.
    "tail": {
        "low":  [(5, "说到后面声音散掉了"), (14, "尾音往下沉")],
        "high": [(95, "越说越用力"), (86, "尾音扬起来")],
    },
}


def _load():
    try:
        with open(BASE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _save(rows):
    tmp = BASE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows[-MAX_KEEP:], f, ensure_ascii=False)
    os.replace(tmp, BASE_PATH)      # atomic; never leave a half-written baseline


def _pct_rank(values, x):
    n = len(values)
    below = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return (below + equal * 0.5) / n * 100.0


def _pick(feature, rank):
    v = VOCAB.get(feature)
    if not v:
        return None
    for thr, word in v["low"]:
        if rank <= thr:
            return word, abs(50.0 - rank)
    for thr, word in v["high"]:
        if rank >= thr:
            return word, abs(50.0 - rank)
    return None


def describe(feats, max_hints=2):
    """feats -> (cue string, debug dict).

    Returns "" when nothing about this clip is unusual for this speaker. That is
    the correct answer roughly a third of the time; resist the urge to fill it.
    """
    base = _load()
    dbg = {"baseline_n": len(base)}

    if len(base) < MIN_SAMPLES:
        # Still learning what "usual" means for this person. Collect, don't guess.
        dbg["reason"] = "baseline<%d" % MIN_SAMPLES
        return "", dbg

    cands = []
    for key in VOCAB:
        if feats.get(key) is None:
            continue
        vals = [r[key] for r in base if isinstance(r.get(key), (int, float))]
        if len(vals) < MIN_SAMPLES:
            continue        # this feature hasn't accumulated enough yet
        rank = _pct_rank(vals, float(feats[key]))
        got = _pick(key, rank)
        if got:
            cands.append((got[1], got[0], key, round(rank, 1)))

    cands.sort(key=lambda c: -c[0])     # most unusual first

    picked, seen = [], set()
    for score, word, key, rank in cands:
        if key in seen:
            continue
        seen.add(key)
        picked.append(word)
        dbg.setdefault("hits", []).append("%s@%s" % (key, rank))
        if len(picked) >= max_hints:
            break

    return "、".join(picked), dbg


def remember(feats):
    """Fold this clip into the baseline. Call *after* describe(), so a clip is
    never ranked against a distribution that already contains it."""
    if not feats:
        return
    keep = {k: feats[k] for k in VOCAB if isinstance(feats.get(k), (int, float))}
    if not keep:
        return
    with _LOCK:
        rows = _load()
        rows.append(keep)
        _save(rows)
