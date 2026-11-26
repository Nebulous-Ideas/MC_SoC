#!/usr/bin/env python3
"""Rap voice: an OpenAI-style speech endpoint that rhymes on a beat for chosen voice names and passes everything else through.

Put it between a bot (OpenClaw or anything that calls /v1/audio/speech) and your speech server. A request whose `voice` is
listed in the config is treated as lines to rap: they are checked, fitted to the beat as sing.py does, mixed and returned as
one clip. Any other request, and any rap request that fails a check or a render, is forwarded unchanged (rap failures fall back
to the plain fallback voice), so the bot never goes silent.

Config (JSON file named by RAP_VOICE_CONFIG; nothing is built in):
  {"talkie-rap": {"voice": "bm_george:robot", "beat": "/path/beat.wav", "bpm": 98, "slot_beats": 4,
                  "fallback_voice": "bm_george"}}
Environment: SPEECH_URL (upstream speech server), SPEECH_KEY is forwarded from the caller's Authorization header and never stored.
Needs: stdlib for this file; rendering runs sing.py (numpy, ffmpeg, your speech server). Fake-tested only; not run for real.

Rules kept here:
- The text is data. Lines that look like sheet directives (@voice, (slot ...), [section]) are refused, not executed.
- Length caps on characters, lines and syllables; one render at a time; a cooldown between rap requests.
- Stock voices only: this file never picks a voice that is not in your config.
"""
import json, os, re, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_CHARS, MAX_LINES, MAX_SYL_PER_BEAT = 800, 16, 3.5   # the same LONG limit lint_lyrics.py applies
DIRECTIVE = re.compile(r"^\s*(@|\[|\(\s*(slot|break|sing|\+)|#)", re.I)
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def plan(text, cfg):
    """Return (lines, None) when the text can be rapped, else (None, reason). The text is data, never instructions."""
    if not isinstance(text, str) or not text.strip():
        return None, "empty"
    if len(text) > MAX_CHARS or CTRL.search(text):
        return None, "too long or has control characters"
    lines = [re.sub(r"\s+", " ", l).strip() for l in re.split(r"[\n]+|(?<=[.!?])\s+", text)]
    lines = [l for l in lines if l]
    if not lines or len(lines) > MAX_LINES:
        return None, "no lines or too many lines"
    cap = int(MAX_SYL_PER_BEAT * cfg.get("slot_beats", 4))
    for l in lines:
        if DIRECTIVE.match(l):
            return None, "looks like a sheet directive"
        if sum(syllables(w) for w in re.findall(r"[A-Za-z']+", l)) > cap:
            return None, f"a line is over {cap} syllables"
    return lines, None


def build_sheet(lines, cfg):
    out = [f"@voice {cfg['voice']}", f"(slot {cfg.get('slot_beats', 4)})"]
    for i, l in enumerate(lines):
        if i and i % 4 == 0:
            out += ["", f"@voice {cfg['voice']}", f"(slot {cfg.get('slot_beats', 4)})"]
        out.append(l)
    return "\n".join(out) + "\n"


def render_with_sing(sheet, cfg, fmt="wav"):
    """Real renderer: runs sing.py on the sheet over cfg['beat'] and returns audio bytes. Raises on any failure."""
    with tempfile.TemporaryDirectory(prefix="rap-") as d:
        path = os.path.join(d, "lyrics-rap.txt")
        open(path, "w").write(sheet)
        subprocess.run([sys.executable, os.path.join(HERE, "sing.py"), "--lyrics", path, "--beat", cfg["beat"], "--bpm", str(cfg["bpm"]),
                        "--voice", cfg["voice"].split(":")[0].split("+")[0], "--slot-beats", str(cfg.get("slot_beats", 4)), "--no-play"],
                       check=True, capture_output=True, timeout=cfg.get("timeout_s", 90), cwd=HERE)
        wav = os.path.join(d, "song-rap.wav")
        if fmt == "wav":
            return open(wav, "rb").read()
        return subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-f", {"mp3": "mp3", "opus": "ogg", "aac": "adts"}.get(fmt, "mp3"), "-"],
                              check=True, capture_output=True, timeout=30).stdout


def forward(method, path, headers, body, upstream):
    """Pass a request to the real speech server and return (status, content_type, bytes)."""
    req = urllib.request.Request(upstream.rstrip("/") + path, data=body or None, method=method,
                                 headers={k: v for k, v in headers.items() if k.lower() in ("authorization", "content-type")})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers.get("Content-Type", "application/octet-stream"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "application/json", e.read()


class RapService:
    def __init__(self, voices, upstream, render=render_with_sing, forward_fn=forward, cooldown_s=3.0, clock=time.monotonic):
        self.voices, self.upstream, self.render, self.forward_fn = voices, upstream, render, forward_fn
        self.cooldown_s, self.clock, self._last = cooldown_s, clock, -1e9
        self._lock = threading.Lock()

    def handle(self, method, path, headers, body):
        """Return (status, content_type, bytes). Rap voices are handled here; everything else is forwarded."""
        if method == "POST" and path.rstrip("/") == "/v1/audio/speech":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                return self.forward_fn(method, path, headers, body, self.upstream)
            cfg = self.voices.get(req.get("voice")) if isinstance(req, dict) else None
            if cfg:
                return self.rap(req, cfg, method, path, headers)
        return self.forward_fn(method, path, headers, body, self.upstream)

    def rap(self, req, cfg, method, path, headers):
        lines, why = plan(req.get("input"), cfg)
        fmt = req.get("response_format", "wav") if req.get("response_format", "wav") in ("wav", "mp3", "opus", "aac") else "wav"
        if lines and self._lock.acquire(blocking=False):
            try:
                now = self.clock()
                if now - self._last >= self.cooldown_s:
                    self._last = now
                    try:
                        audio = self.render(build_sheet(lines, cfg), cfg, fmt)
                        return 200, {"wav": "audio/wav", "mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac"}[fmt], audio
                    except Exception as e:   # any render failure falls back to plain speech
                        sys.stderr.write(f"rap render failed, using plain voice: {type(e).__name__}\n")
            finally:
                self._lock.release()
        plain = dict(req, voice=cfg.get("fallback_voice", "af_heart"))
        return self.forward_fn(method, path, headers, json.dumps(plain).encode(), self.upstream)


def make_handler(service):
    class H(BaseHTTPRequestHandler):
        def _go(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20000:
                self.send_error(413); return
            status, ctype, data = service.handle(self.command, self.path, dict(self.headers), self.rfile.read(n) if n else b"")
            self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        do_GET = do_POST = _go
        def log_message(self, *a): pass
    return H


def main(argv=None):
    cfg_path = os.environ.get("RAP_VOICE_CONFIG")
    if not cfg_path:
        sys.exit("set RAP_VOICE_CONFIG to a JSON file of rap voices (see the docstring) and SPEECH_URL to your speech server")
    voices = json.load(open(cfg_path))
    upstream = os.environ.get("SPEECH_URL", "http://localhost:8000")
    host, port = os.environ.get("RAP_HOST", "127.0.0.1"), int(os.environ.get("RAP_PORT", "8010"))
    print(f"rap voice on http://{host}:{port} -> {upstream}; rap voices: {', '.join(voices) or 'none'}")
    ThreadingHTTPServer((host, port), make_handler(RapService(voices, upstream))).serve_forever()


if __name__ == "__main__":
    main()
