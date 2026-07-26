# Tone cues: why fixed thresholds don't work

A tone cue is the short phrase attached to what someone just said — *声音比平时轻*,
*停顿比平时多* — so the companion can react to **how** it was said, not only what
was said. It rides along with the transcript and the SenseVoice emotion tag.

The first version of this compared acoustic features against constants. It shipped,
it ran for months, and the person on the other end eventually said:

> it's not very good, it keeps telling me I'm speaking in fragments, or that I'm
> loud. there aren't any other words.

She was right, and literally so. This is what the measurements showed.

---

## What was measured

85 real recordings from one speaker (Mandarin, phone mic, 1.5–13s), run through
the old logic unchanged.

```
语调起伏大    38.8%  ███████████████
说得断断续续  28.2%  ███████████
嗓门大情绪冲  20.0%  ████████
声音低停顿多  17.6%  ███████
（no cue）    10.6%
声音很轻       3.5%  █
音调高很激动   2.4%
尾音上扬       2.4%
```

Seven phrases existed. **Four of them covered 90% of all output, and the most
frequent one was the fallback branch** — the phrase emitted when nothing else
matched. "There aren't any other words" was an accurate bug report.

### Why

**`pitch_var > 60` was true in 96.5% of clips.** Mandarin is a tonal language;
lexical tone dominates F0 variance. Her median was 94.3 and her 25th percentile
was 85.4 — the entire distribution sat above the threshold. The condition carried
no information, so every rule containing it silently degraded to its other half:
*嗓门大情绪冲* was really just `energy > 0.06`.

**The `pause` threshold sat on her median.** Cutoff 0.44, median 0.42. That isn't
a detector; it splits the recordings in half at random.

**Two phrases were dead code.** Both required `pitch > 250`. Her median pitch was
195.5 and her 75th percentile 216.8. In 85 recordings they fired twice, mostly on
a synthetic test tone.

**Energy thresholds were absolute.** `energy < 0.015` describes a microphone and a
distance to the mouth, not a person. Change the room and the whole classifier drifts.

*(One speaker, one language, one microphone. The specific percentages are hers.
The structural problems are not: tonal-language F0 inflation, thresholds landing
on a median, and gain-dependent energy will show up in any fixed-constant design.)*

---

## The fix: rank against the speaker, not against a number

There is no good constant, because the question "is this loud?" has no answer
without "compared to what?"

Keep a rolling baseline of this person's own recordings — the last 400 — and for
each clip compute where its features land in that distribution. Speak only when
something sits at one end.

```
                     old                      new
vocabulary           5 usable (1 = fallback)  17
most frequent cue    38.8%                    10.6%
no cue at all        10.6%                    34.1%
decided by           hardcoded constants      percentile within this speaker
```

Two properties worth having:

**The baseline follows them.** New microphone, different room, a cold, a quieter
flat — it drifts along instead of going wrong. No recalibration, no per-device
config.

**Silence is an answer, and a common one.** Around a third of clips produce no cue.
This is deliberate. A wrong tone cue is worse than no tone cue: the companion reads
it as evidence and misjudges the mood. A caption on every single sentence also
trains the reader to skip the line — an early draft used 20/80 cutoffs, labelled
94% of clips, and was worse than saying nothing.

Cutoffs are at the 12th/88th percentile, with a stronger tier at 4th/96th.

---

## Two features worth adding

**Speaking rate (字/秒).** Computed from the transcript you already have — no extra
model — and unlike energy it owes nothing to mic gain or distance to the mouth.
Fast reads as wound-up, slow reads as heavy or tired. One of the cleanest signals
available here, and it was simply missing.

**Tail energy.** Mean RMS of the last quarter over the middle half: running out of
breath, or leaning in.

Both are measured over the **voiced span**, not the whole file. This matters more
than it sounds:

> `tail` was first written with absolute cutoffs — precisely the mistake this
> document exists to correct — and it failed on the first test run. Recordings
> carry a second or two of trailing silence, so the last quarter of the file is
> silence, so the ratio pinned near zero, so *every* clip came back
> "说到后面声音散掉了". Same bug as before, freshly re-implemented.

Find the voiced span by thresholding RMS at 15% of its peak, then measure inside it.

---

## Practical notes

- **Don't rank a clip against a baseline that already contains it.** Call
  `describe()` before `remember()`, or every clip drifts toward its own median.
- **Changing the pitch extraction invalidates every stored baseline.** `yin`'s
  `frame_length` / `hop_length` shift the values, and every percentile with them.
  Version the baseline file if you expect to tune this.
- **Wait for samples before ranking.** 25 per feature, minimum. New features
  (rate, tail) accumulate on their own schedule and stay silent until they have
  enough — a percentile over four samples is a guess wearing a number.
- **The baseline is personal data.** It is a statistical fingerprint of one voice.
  It lives next to the service and it is not something to commit or share.

---

## What about sending the audio to a multimodal model?

You can. A model that actually listens will out-describe anything in this
document. Where this module says *声音比平时轻*, a multimodal model can name the
specific thing it heard — which word the hesitation came before, how the last
syllable was shaped, whether there was a smile in it. That is a different league
and we are not going to pretend otherwise; Gemini, GPT-4o audio and similar all
do it.

We have not implemented it here, for one reason:

> **Self-hosted. Your voice never leaves your server.**

That line is on the front page of this project. Sending the audio out is not a
feature toggle, it is the promise going away. If you add this path, do it
deliberately: make it opt-in, default it off, and say plainly in your own README
that the audio leaves the machine. Don't let it arrive quietly as an upgrade.

Also worth knowing before you reach for it: another API key, another dependency in
the latency path of a live call, and a per-utterance cost on something that fires
constantly. The local path here is free, private, and — once it is ranking against
the person instead of against a constant — good enough that the difference stopped
being the thing anyone noticed.

Start local. Add the model when local is genuinely the limit, not before.
