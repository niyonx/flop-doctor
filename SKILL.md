---
name: flop-doctor
description: Find out why a reel, TikTok or YouTube Short flopped and fix it. Pulls every post's views against the account's usual (median) views from PostOnce analytics, puts a flop's first 3 seconds next to the account's winners, writes a specific fix (new hook, trim, caption), recuts the video with ffmpeg and retests it as an Instagram Trial Reel shown to non-followers. Use when someone asks why a reel or short flopped, why views dropped, what their best posts have in common, or how to test a new hook before reposting.
---

# Flop doctor

Diagnose with evidence, change one thing, retest. The helper is `doctor.py` in this folder (Python standard library + ffmpeg). It needs `POSTONCE_API_KEY` with the analytics, media and posts scopes; never ask for the key in chat.

## 1. Find the flops

`python3 doctor.py scan --days 30` lists flops (0.5× the account's median views or less) and winners (2× or more) for TikTok, Instagram, YouTube and Facebook, including posts made outside PostOnce. Posts younger than 48 hours are skipped: they haven't finished being distributed. Use `--days 90` when an account posts rarely.

`python3 doctor.py patterns --days 90` compares winners and flops: caption length, hashtags, words in the first caption line, hour and day posted. Treat it as a list of things to test, not proof.

## 2. Inspect one flop

`python3 doctor.py inspect <id>` writes `inspect-<id>/report.json` and frame sheets of the first 3 seconds (0, 0.5, 1, 1.5, 2, 3 s) for the flop and the account's top two winners. Posts made outside PostOnce (ids starting `n:`) need the file: `--video path.mp4`.

Look at the frame sheets yourself and answer, for the flop and the winners side by side:

1. **Frame 0:** is there motion, a face, or readable text in the first frame, or a slow fade/logo/intro?
2. **Hook:** what does the viewer learn by second 1.5? Is there a reason to keep watching (a question, a surprising claim, a visible result)?
3. **Text:** is on-screen text big enough to read on a phone and clear of the bottom 20% (where captions and buttons sit)?
4. **Length** against the winners (`report.json` → `video.seconds`).
5. **Caption:** first line under 10 words? Does it repeat the hook or add to it?
6. **Topic:** is it the same kind of topic as the winners, or something the audience didn't come for?

Platforms don't share retention curves through the API, so never claim to know where people dropped off. Say what the frames and numbers show and what you would test.

## 3. Write the fix

Pick **one** main change (the hook first, unless something else is clearly worse) and write:

- the new on-screen hook text (under 8 words),
- how many seconds to trim from the start, if the first second is dead,
- a new caption whose first line is under 10 words.

Show the user the diagnosis and the fix before touching the video.

## 4. Recut and retest

```
python3 doctor.py recut video.mp4 --trim-start 1.2 --hook "Your rice is still dirty" -o fixed.mp4
python3 doctor.py retest fixed.mp4 --caption "Your rice is still dirty. Here's why" --from <original id>
```

`recut` cuts the slow start and burns the hook into the first 3 seconds (`--font` for your brand font, `--max-seconds` to shorten). `retest` posts it to the connected Instagram account as a Trial Reel: Instagram shows it to non-followers first and keeps it off the grid. `--auto-share` lets Instagram share it with followers if it does well; `--ai-generated` for AI-made video. Confirm with the user before posting.

After 24–72 hours: `python3 doctor.py results` puts the retest's views next to the original's. Keep the change that won and apply it to the next post.
