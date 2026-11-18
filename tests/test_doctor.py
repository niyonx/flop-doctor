"""Tests for doctor.py against a local PostOnce stand-in. Run: python3 tests/test_doctor.py [analytics.json]

Without an argument it uses tests/fixture-analytics.json (made-up accounts and posts). Pass a real GET /v1/analytics
response saved to a file to check the scan and patterns output on your own data; nothing leaves your machine.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "fixture-analytics.json"
DATA = json.loads(FIXTURE.read_text())
DATA = DATA.get("data", DATA)
LOG = []
VIDEO = None


class H(BaseHTTPRequestHandler):
    def send(self, code, obj=None, raw=None, ctype="application/json"):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def handle_any(self, m):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        j = json.loads(raw) if raw[:1] == b"{" else None
        p, q = (self.path.split("?") + [""])[:2]
        LOG.append({"m": m, "p": p, "q": q, "auth": self.headers.get("Authorization"), "idem": self.headers.get("Idempotency-Key"), "j": j})
        if p.startswith("/media-files/"):
            return self.send(200, raw=VIDEO.read_bytes(), ctype="video/mp4")
        if p.startswith("/storage/"):
            return self.send(200 if m == "PUT" and not self.headers.get("Authorization") else 400, {})
        if self.headers.get("Authorization") != "Bearer test":
            return self.send(401, {"error": {"code": "unauthorized"}})
        r = p[len("/api/public/v1"):]
        if r == "/analytics":
            return self.send(200, {"data": DATA})
        if r == "/accounts":
            return self.send(200, {"data": [{"id": "ig-main", "platform": "instagram", "username": "maker", "status": "active"}]})
        if r == "/media/uploads":
            return self.send(201, {"data": {"media_id": "m1", "upload": {"signedUrl": f"http://127.0.0.1:{PORT}/storage/m1"}}})
        if r.startswith("/media/"):
            return self.send(200, {"data": {"public_url": "https://cdn.example.com/m1.mp4"}})
        if r == "/posts" and m == "POST":
            t = j["targets"][0]["platform_options"]
            ok = t.get("publish_as_trial_reel") is True and t.get("trial_graduation") in ("MANUAL", "SS_PERFORMANCE")
            return self.send(201 if ok else 400, {"data": {"id": "retest-1", "status": "queued"}})
        if r == "/posts/retest-1/analytics":
            return self.send(200, {"data": {"id": "retest-1", "targets": [{"platform": "instagram", "views": 4100}]}})
        return self.send(404, {"error": {"code": "no_route", "path": r}})

    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")
    def do_PUT(self): self.handle_any("PUT")
    def log_message(self, *a): pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def doc(*args, ok=True, cwd=None):
    env = {**os.environ, "POSTONCE_API_KEY": "test", "POSTONCE_API_URL": f"http://127.0.0.1:{PORT}/api/public/v1"}
    r = subprocess.run([sys.executable, str(ROOT / "doctor.py"), *map(str, args)], capture_output=True, text=True, env=env, cwd=cwd)
    if ok and r.returncode:
        sys.exit(f"FAILED doctor.py {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r


def main():
    global VIDEO
    work = Path(tempfile.mkdtemp())
    VIDEO = work / "src.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=6",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-shortest", VIDEO], check=True)
    if FIXTURE.name == "fixture-analytics.json":
        # shift the made-up dates so the newest post ("p-young") is 5 hours old today, and point media at the stand-in
        parse = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        newest = max(parse(p["published_at"]) for p in DATA["posts"])
        shift = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5) - newest
        for p in DATA["posts"]:
            for obj in [p, *p.get("destinations", [])]:
                obj["published_at"] = (parse(obj["published_at"]) + shift).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if p.get("media_url"):
                p["media_url"] = f"http://127.0.0.1:{PORT}/media-files/{p['id']}.mp4"
    scan = doc("scan", "--days", "90").stdout
    print(scan.strip()[:1500])
    assert "Flops:" in scan and "Winners:" in scan
    pat = doc("patterns", "--days", "90")
    print(pat.stdout.strip())
    if FIXTURE.name != "fixture-analytics.json":
        print("real-data run: scan and patterns OK")
        return
    assert "hook words" in pat.stdout
    young = [p for p in DATA["posts"] if p["id"] == "p-young"][0]
    assert young["title"] not in scan, "posts younger than 48h must not be judged"
    ins = doc("inspect", "p-flop", "--days", "90", "--out", work / "ins", cwd=work).stdout
    rep = json.loads((work / "ins" / "report.json").read_text())
    assert rep["video"]["seconds"] == 6.0 and Path(rep["frame_sheet"]).exists(), rep
    assert rep["account_winners"] and rep["account_winners"][0]["id"] == "p-win", rep["account_winners"]
    assert Path(rep["account_winners"][0]["frame_sheet"]).exists()
    doc("recut", VIDEO, "-o", work / "fixed.mp4", "--trim-start", "1.5", "--hook", "Your fridge is lying: here's proof")
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", work / "fixed.mp4"],
                          capture_output=True, text=True).stdout
    assert abs(float(info) - 4.5) < 0.2, info
    out = doc("retest", work / "fixed.mp4", "--caption", "New hook test", "--from", "p-flop", cwd=work).stdout
    print(out.strip())
    post = [x for x in LOG if x["p"].endswith("/posts") and x["m"] == "POST"][-1]
    assert post["idem"] and post["j"]["targets"][0]["platform_options"]["publish_as_trial_reel"] is True
    assert not any(x["auth"] for x in LOG if x["p"].startswith("/storage/")), "signed upload must not carry the API key"
    res = doc("results", cwd=work).stdout
    print(res.strip())
    assert "4100 views" in res and "0.2x usual" in res, res
    print("ALL OK")


if __name__ == "__main__":
    main()
