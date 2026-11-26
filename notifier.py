"""Optional hook to notify-hub (a separate tool). Off unless NOTIFY_HUB is set.

Never blocks or fails the caller: a review decision must not depend on Discord being up.
Sends only system/kind/severity/title (ids and statuses), never record text or names.
The webhook URLs live in notify-hub's own environment, not here."""
import json, os, subprocess, sys


def emit(kind, title, severity="info", link=None, env=None, run=subprocess.run):
    env = os.environ if env is None else env
    hub = env.get("NOTIFY_HUB")
    if not hub:
        return False
    ev = {"system": "mc-soc", "kind": kind, "severity": severity, "title": title}
    if link:
        ev["link"] = link
    cmd = [sys.executable, "-I", os.path.join(hub, "notify.py")]
    if env.get("NOTIFY_ROUTES"):
        cmd += ["--routes", env["NOTIFY_ROUTES"]]
    try:
        r = run(cmd, input=json.dumps(ev), capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False
