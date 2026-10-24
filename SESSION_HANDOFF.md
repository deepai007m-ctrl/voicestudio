# Session handoff: HI Pro Hindi voices (2026-10-24)

## Done
- 38 QC'd Hindi voice-design profiles saved in the running VoiceStudio as
  `HI Pro · <Category> · <Name>` (Narrator, News Anchor, Ad Voice, Motivational,
  Devotional, Kids, Funny, Love, Emotional, Angry, Calm, Conversational, Job,
  Accent, Family). User listened and approved all of them.
- Builder: `scripts/build_hindi_pro_voices.py` (stdlib only). Per voice it tries
  up to 5 VoxCPM2 seeds, scores pause noise floor, head/tail cuts, length and ASR
  match, gates/trims/normalises the best take into a clone profile, then QCs a
  `/v1/speak` sample.
- Samples, per-category joined WAVs and `report.json`: `E:\coding\VoiceStudio-HIPro\`.

## How to run / extend
```
py -3 scripts/build_hindi_pro_voices.py --out "E:/coding/VoiceStudio-HIPro" --seeds 5
```
Add a tuple to `VOICES` and re-run; existing names are skipped, rejected ones retried.
Needs VoiceStudio up on 127.0.0.1:3900 (`/health` 200).

## Left
- Nothing pending. This branch is a personal tool, not meant for an upstream PR.
