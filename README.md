# flop-doctor

Find out why a reel or short flopped, fix the hook, and test the fix on Instagram before you repost it. A Claude skill plus a small Python CLI.

```
analytics (views vs your usual) ─► flops and winners ─► first 3 seconds, side by side
      ─► one specific fix (hook, trim, caption) ─► recut ─► Instagram Trial Reel ─► did it beat the original?
```

Most "why did my reel flop" advice is generic. This compares a flop with **your own** winners: every post's views against the account's median, the first 3 seconds of each as a frame sheet, and the caption. Then it changes one thing and tests it on people who don't follow you yet.

## What you need

- Python 3.9+ and [ffmpeg](https://ffmpeg.org/download.html). No pip installs. `recut --hook` needs an ffmpeg with freetype: on a Mac, Homebrew's plain `ffmpeg` (9.x) leaves it out, so run `brew install ffmpeg-full` (found automatically) or point `FFMPEG` at a full build.
- A [PostOnce](https://postonce.to?utm_source=github&utm_campaign=flop-doctor) API key (`POSTONCE_API_KEY`, Preferences → API) with your TikTok, Instagram, YouTube or Facebook accounts connected. PostOnce reads views, likes, comments, shares and saves for each post, including ones you posted outside PostOnce, and compares each with the account's median. The key needs the `accounts:read`, `media:read`, `media:write`, `posts:read` and `posts:write` scopes.

## Use it as a Claude skill

```
git clone https://github.com/niyonx/flop-doctor ~/.claude/skills/flop-doctor
```

Then ask: *"Why did my last reel flop?"* Claude scans your posts, looks at the flop's first seconds next to your best posts, tells you what it would change and why, and retests the fix when you say so. See [SKILL.md](SKILL.md).

## Use it from the command line

```
export POSTONCE_API_KEY=...
python3 doctor.py scan --days 30          # flops (≤0.5x your usual views) and winners (≥2x)
python3 doctor.py patterns --days 90      # what winners share that flops don't
python3 doctor.py inspect <post id>       # frame sheets of the first 3 seconds + caption, next to your winners
python3 doctor.py recut in.mp4 --trim-start 1.2 --hook "Your rice is still dirty" -o fixed.mp4
python3 doctor.py retest fixed.mp4 --caption "Your rice is still dirty. Here's why" --from <post id>
python3 doctor.py results                 # 24-72 hours later: retest vs original
```

Notes:

- Posts younger than 48 hours are skipped; they are still being shown to people.
- Videos posted outside PostOnce have no downloadable file in the API, so `inspect` takes `--video path.mp4` for those.
- The API has no retention curves, so the skill never claims to know exactly where people swiped away. It shows what's on screen and what to test.
- Trial Reels are Instagram only: shown to non-followers first and kept off your grid.

## Tests

`python3 tests/test_doctor.py` runs every command against a local stand-in for PostOnce with made-up posts. `python3 tests/test_doctor.py my-analytics.json` runs `scan` and `patterns` on a real `GET /v1/analytics` response you saved; nothing leaves your machine.

## License

MIT
