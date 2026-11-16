#!/usr/bin/env python3
"""flop-doctor: find out why a reel or short flopped, fix the hook, and retest it as an Instagram Trial Reel.

  python3 doctor.py scan --days 30                  # flops and winners per account, from PostOnce analytics
  python3 doctor.py inspect <post id>               # first-3-seconds frame sheet + caption, next to the account's winners
  python3 doctor.py patterns --days 90              # what winners share that flops don't (length, hashtags, hour, hook words)
  python3 doctor.py recut in.mp4 --trim-start 1.2 --hook "Your fridge is lying to you" -o fixed.mp4
  python3 doctor.py retest fixed.mp4 --caption "..." --from <post id>   # Trial Reel through PostOnce
  python3 doctor.py results                         # retest vs original

Needs POSTONCE_API_KEY (PostOnce -> Preferences -> API) for everything except recut, plus ffmpeg for inspect and recut.
Standard library only.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = os.environ.get("POSTONCE_API_URL", "https://postonce.to/api/public/v1")
UA = "flop-doctor/0.1"
STATE = Path(os.environ.get("FLOP_DOCTOR_STATE", "flop-doctor.json"))
VIDEO_PLATFORMS = {"tiktok", "instagram", "youtube", "facebook"}


def die(msg):
    sys.exit(f"error: {msg}")


def http(method, url, *, body=None, headers=None, raw=None, timeout=300):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"User-Agent": UA, **(headers or {})}
    if body is not None:
        h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=timeout) as r:
            t = r.read()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        die(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")


def api(method, path, body=None, extra=None):
    key = os.environ.get("POSTONCE_API_KEY", "").strip()
    if not key:
        die("POSTONCE_API_KEY is not set. Create one in PostOnce: Preferences -> API.")
    return http(method, API.rstrip("/") + path, body=body, headers={"Authorization": f"Bearer {key}", **(extra or {})})


def analytics(days, account=None):
    if days not in (7, 30, 90):
        die("--days must be 7, 30 or 90")
    q = {"days": days, **({"account_id": account} if account else {})}
    for _ in range(12):
        d = api("GET", "/analytics?" + urllib.parse.urlencode(q))["data"]
        if not d.get("refreshing") or d.get("posts"):
            return d
        import time
        time.sleep(10)  # first report for many accounts takes about a minute
    return d


def copies(data, min_age_hours):
    """One row per platform copy, old enough to judge."""
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for p in data.get("posts", []):
        for d in p.get("destinations", []):
            if d.get("platform") not in VIDEO_PLATFORMS or d.get("views") is None:
                continue
            pub = dt.datetime.fromisoformat((d.get("published_at") or p["published_at"]).replace("Z", "+00:00"))
            if (now - pub).total_seconds() < min_age_hours * 3600:
                continue
            rows.append({"post": p, "dest": d, "ratio": d.get("views_vs_account_median"), "published": pub})
    return rows


def label(r):
    d = r["dest"]
    return f"{d['platform']} @{d.get('username')}"


# ------------------------------------------------------------------ scan
def cmd_scan(a):
    data = analytics(a.days, a.account)
    rows = [r for r in copies(data, a.min_age) if r["ratio"] is not None]
    if not rows:
        print("no posts with views and a median yet (an account needs 3+ posts with views in the range)")
        return
    flops = sorted([r for r in rows if r["ratio"] <= a.flop], key=lambda r: r["ratio"])
    wins = sorted([r for r in rows if r["ratio"] >= a.win], key=lambda r: -r["ratio"])

    def show(title, rs):
        print(f"\n{title} ({len(rs)})")
        for r in rs[: a.limit]:
            p, d = r["post"], r["dest"]
            print(f"  {r['ratio']:>5.2f}x  {d.get('views') or 0:>8} views  {label(r):<28} {r['published']:%Y-%m-%d}  "
                  f"{(p.get('title') or '')[:50]:<50}  id={p.get('post_id') or p['id']}")
    show(f"Flops: {a.flop}x the account's usual views or less", flops)
    show(f"Winners: {a.win}x or more", wins)
    for acc in data.get("accounts", []):
        if acc.get("metrics_status") not in (None, "ok"):
            print(f"\nnote: {acc['platform']} @{acc.get('username')}: {acc['metrics_status']} (numbers may be missing)")
    print("\nNext: python3 doctor.py inspect <id>   (ids starting with n: were posted outside PostOnce; inspect needs the video file for those)")


# ------------------------------------------------------------------ inspect
def ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        die("ffmpeg failed: " + r.stderr.strip()[-600:])


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    j = json.loads(out or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"seconds": round(float(j.get("format", {}).get("duration", 0)), 1), "width": v.get("width"), "height": v.get("height"),
            "has_audio": any(s.get("codec_type") == "audio" for s in j.get("streams", []))}


def frame_sheet(video, out_jpg, times=(0.0, 0.5, 1.0, 1.5, 2.0, 3.0)):
    tmp = out_jpg.with_suffix("")
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, t in enumerate(times):
        f = tmp / f"{i}.jpg"
        ffmpeg("-ss", t, "-i", video, "-frames:v", "1", "-vf", "scale=240:-2", f)
        if f.exists():
            parts.append(f)
    inputs = sum((["-i", p] for p in parts), [])
    ffmpeg(*inputs, "-filter_complex", f"hstack={len(parts)}", out_jpg)
    shutil.rmtree(tmp, ignore_errors=True)


def find_post(data, pid):
    for p in data.get("posts", []):
        if pid in (p.get("post_id"), p.get("id")):
            return p
    return None


def hook_words(text):
    first = re.split(r"[\n.!?]", text or "", maxsplit=1)[0]
    return len(first.split())


def cmd_inspect(a):
    data = analytics(a.days, None)
    p = find_post(data, a.post)
    if not p:
        die(f"post {a.post} not in the last {a.days} days of analytics")
    out = Path(a.out or f"inspect-{re.sub(r'[^A-Za-z0-9]+', '-', a.post)[:40]}")
    out.mkdir(parents=True, exist_ok=True)
    video = Path(a.video) if a.video else None
    if not video and p.get("media_url"):
        video = out / "video.mp4"
        req = urllib.request.Request(p["media_url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r, open(video, "wb") as f:
            shutil.copyfileobj(r, f)
    report = {"post": {k: p.get(k) for k in ("post_id", "id", "title", "caption", "published_at", "media_url")},
              "copies": [{"platform": d["platform"], "username": d.get("username"), "views": d.get("views"),
                          "vs_median": d.get("views_vs_account_median"), "engagement_rate": d.get("engagement_rate"), "url": d.get("url")}
                         for d in p.get("destinations", [])],
              "caption_stats": {"chars": len(p.get("caption") or ""), "hashtags": len(re.findall(r"#\w+", p.get("caption") or "")),
                                "hook_words": hook_words(p.get("caption"))}}
    if video and video.exists():
        report["video"] = probe(video)
        frame_sheet(video, out / "first-3-seconds.jpg")
        report["frame_sheet"] = str(out / "first-3-seconds.jpg")
    else:
        report["video"] = "not available: posted outside PostOnce. Pass --video path/to/file.mp4"
    # the same account's winners, for comparison
    accounts = {d["account_id"] for d in p.get("destinations", [])}
    wins = [r for r in copies(data, 0) if r["dest"]["account_id"] in accounts and (r["ratio"] or 0) >= a.win]
    report["account_winners"] = [{"title": r["post"].get("title"), "vs_median": r["ratio"], "platform": r["dest"]["platform"],
                                  "hook_words": hook_words(r["post"].get("caption")), "id": r["post"].get("post_id") or r["post"]["id"],
                                  "media_url": r["post"].get("media_url")} for r in sorted(wins, key=lambda r: -r["ratio"])[:5]]
    for i, w in enumerate(report["account_winners"][:2], 1):
        if w["media_url"]:
            wv = out / f"winner-{i}.mp4"
            req = urllib.request.Request(w["media_url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r, open(wv, "wb") as f:
                shutil.copyfileobj(r, f)
            frame_sheet(wv, out / f"winner-{i}-first-3-seconds.jpg")
            w["frame_sheet"] = str(out / f"winner-{i}-first-3-seconds.jpg")
            w["video"] = probe(wv)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nwrote {out}/report.json" + (" and frame sheets" if report.get("frame_sheet") else ""))


# ------------------------------------------------------------------ patterns
def cmd_patterns(a):
    data = analytics(a.days, a.account)
    rows = [r for r in copies(data, a.min_age) if r["ratio"] is not None]
    groups = {"winners": [r for r in rows if r["ratio"] >= a.win], "flops": [r for r in rows if r["ratio"] <= a.flop]}
    if not groups["winners"] or not groups["flops"]:
        die(f"need at least one winner and one flop (found {len(groups['winners'])} and {len(groups['flops'])}); try --days 90")

    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 1) if xs else None
    print(f"{'':<22}{'winners':>10}{'flops':>10}")
    for name, fn in [("count", lambda rs: len(rs)),
                     ("caption characters", lambda rs: med([len(r["post"].get("caption") or "") for r in rs])),
                     ("hashtags", lambda rs: med([len(re.findall(r"#\w+", r["post"].get("caption") or "")) for r in rs])),
                     ("hook words (line 1)", lambda rs: med([hook_words(r["post"].get("caption")) for r in rs])),
                     ("hour posted (UTC)", lambda rs: med([r["published"].hour for r in rs])),
                     ("engagement rate %", lambda rs: med([(r["dest"].get("engagement_rate") or 0) * 100 for r in rs]))]:
        print(f"{name:<22}{str(fn(groups['winners'])):>10}{str(fn(groups['flops'])):>10}")
    days = {g: [r["published"].strftime("%a") for r in rs] for g, rs in groups.items()}
    for g in days:
        common = max(set(days[g]), key=days[g].count)
        print(f"most common day, {g}: {common}")
    print("\nThese are correlations in a small sample. Use them to pick what to test, then test it with retest.")


# ------------------------------------------------------------------ recut
def cmd_recut(a):
    src = Path(a.video)
    if not src.exists():
        die(f"{src} not found")
    info = probe(src)
    w, h = info["width"] or 1080, info["height"] or 1920
    vf = []
    if a.hook:
        text = a.hook.replace("\\", "\\\\").replace("'", "’").replace(":", "\\:")
        size = max(28, int(w * 0.065))
        font = f"fontfile='{a.font}':" if a.font else ""
        vf.append(f"drawtext={font}text='{text}':fontcolor=white:fontsize={size}:borderw={max(3, size // 9)}:bordercolor=black:"
                  f"x=(w-text_w)/2:y=h*0.16:enable='lt(t,{a.hook_seconds})'")
    args = []
    if a.trim_start:
        args += ["-ss", a.trim_start]
    args += ["-i", src]
    if a.max_seconds:
        args += ["-t", a.max_seconds]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", a.out]
    ffmpeg(*args)
    print(f"wrote {a.out} ({probe(a.out)['seconds']}s, was {info['seconds']}s)")


# ------------------------------------------------------------------ retest + results
def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"retests": []}


def cmd_retest(a):
    video = Path(a.video)
    if not video.exists():
        die(f"{video} not found")
    accounts = api("GET", "/accounts").get("data", [])
    ig = [x for x in accounts if x["platform"] == "instagram" and x.get("status") == "active"]
    if a.account:
        ig = [x for x in accounts if x["id"] == a.account]
    if not ig:
        die("no active Instagram account in PostOnce (Trial Reels are Instagram only). Pass --account if you have several.")
    if len(ig) > 1:
        die("several Instagram accounts: pass --account ID (python3 doctor.py accounts lists them)")
    acc = ig[0]
    up = api("POST", "/media/uploads", {"filename": video.name, "content_type": "video/mp4"})["data"]
    http("PUT", up["upload"]["signedUrl"], raw=video.read_bytes(), headers={"Content-Type": "video/mp4"})
    url = api("GET", "/media/" + urllib.parse.quote(up["media_id"], safe=""))["data"]["public_url"]
    opts = {"publish_as_trial_reel": True, "trial_graduation": "SS_PERFORMANCE" if a.auto_share else "MANUAL"}
    if a.ai_generated:
        opts["ai_generated"] = True
    body = {"content": a.caption, "media": [{"type": "video", "url": url}], "targets": [{"account_id": acc["id"], "platform_options": opts}]}
    if a.schedule:
        body["publish_at"] = a.schedule
    r = api("POST", "/posts", body, {"Idempotency-Key": f"flop-doctor-{video.stat().st_size}-{a.caption[:40]}"})["data"]
    state = load_state()
    state["retests"].append({"post_id": r["id"], "original": a.from_post, "video": str(video), "caption": a.caption,
                             "account": f"@{acc.get('username')}", "posted_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Trial Reel {r['id']} ({r.get('status')}) on instagram @{acc.get('username')}. Check back with: python3 doctor.py results")


def cmd_results(a):
    state = load_state()
    if not state["retests"]:
        die(f"no retests recorded in {STATE}")
    data = analytics(30, None)
    for t in state["retests"]:
        now = api("GET", f"/posts/{t['post_id']}/analytics").get("data", {})
        views = sum((x.get("views") or 0) for x in now.get("targets", []))
        orig = find_post(data, t["original"]) if t.get("original") else None
        ov = ", ".join(f"{d['platform']} {d.get('views')} views ({d.get('views_vs_account_median')}x usual)" for d in (orig or {}).get("destinations", []))
        print(f"retest {t['post_id']} {t['account']}: {views} views so far  |  original: {ov or 'not in the last 30 days'}")
        print(f"   caption: {t['caption'][:80]}")
    print("\nTrial Reels reach non-followers first, so compare against the original's views, not its likes. Give it 24-72 hours.")


def cmd_accounts(a):
    for acc in api("GET", "/accounts").get("data", []):
        print(f"{acc['id']}  {acc['platform']:<16} @{acc.get('username') or ''}  {acc.get('status')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--days", type=int, default=30, help="7, 30 or 90")
    common.add_argument("--account", help="one PostOnce account id")
    common.add_argument("--flop", type=float, default=0.5, help="a flop is this many times the account's median views or less")
    common.add_argument("--win", type=float, default=2.0, help="a winner is this many times the median or more")
    common.add_argument("--min-age", type=float, default=48, help="ignore posts younger than this many hours")
    p = sp.add_parser("scan", parents=[common], help="list flops and winners"); p.add_argument("--limit", type=int, default=15); p.set_defaults(fn=cmd_scan)
    p = sp.add_parser("inspect", parents=[common], help="frame sheet + caption for one post, next to the account's winners")
    p.add_argument("post"); p.add_argument("--video", help="the file, for posts made outside PostOnce"); p.add_argument("--out"); p.set_defaults(fn=cmd_inspect)
    p = sp.add_parser("patterns", parents=[common], help="what winners share that flops don't"); p.set_defaults(fn=cmd_patterns)
    p = sp.add_parser("recut", help="trim a slow start and burn a text hook into the first seconds")
    p.add_argument("video"); p.add_argument("-o", "--out", required=True)
    p.add_argument("--trim-start", type=float, default=0, help="seconds to cut from the start")
    p.add_argument("--hook", help="on-screen text for the first seconds"); p.add_argument("--hook-seconds", type=float, default=3)
    p.add_argument("--max-seconds", type=float, help="cut the end after this many seconds"); p.add_argument("--font", help="path to a .ttf/.otf")
    p.set_defaults(fn=cmd_recut)
    p = sp.add_parser("retest", help="post a fixed version as an Instagram Trial Reel")
    p.add_argument("video"); p.add_argument("--caption", required=True); p.add_argument("--from", dest="from_post", help="the original post id")
    p.add_argument("--account", help="Instagram account id in PostOnce"); p.add_argument("--auto-share", action="store_true")
    p.add_argument("--ai-generated", action="store_true"); p.add_argument("--schedule", help="ISO time to publish")
    p.set_defaults(fn=cmd_retest)
    p = sp.add_parser("results", help="retests vs originals"); p.set_defaults(fn=cmd_results)
    p = sp.add_parser("accounts", help="list PostOnce accounts"); p.set_defaults(fn=cmd_accounts)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
