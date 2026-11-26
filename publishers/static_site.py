"""Publisher: one static HTML page (GitLab Pages, any web server, or a file share). Stdlib only.

Contract for every publisher: `publish(records, out) -> list of written paths`, where
`records` are already gated (approved and verify-clean) by gate.py. A publisher never
decides what is publishable; it only renders. Left out here on purpose: approver names,
notes, memory_ref, and links to internal hosts.
"""
import html, os, re
from pathlib import Path
from urllib.parse import urlparse

def _internal():
    """Hosts never linked from the page: private ranges, .local, localhost,
    plus your own internal domains from MCSOC_INTERNAL_DOMAINS (comma-separated)."""
    extra = [re.escape(d.strip().lstrip(".")) for d in os.environ.get("MCSOC_INTERNAL_DOMAINS", "").split(",") if d.strip()]
    parts = [r"(^|\.)local$", r"^localhost$", r"^10\.", r"^192\.168\.", r"^172\.(1[6-9]|2\d|3[01])\."]
    parts += [rf"(^|\.){d}$" for d in extra]
    return re.compile("|".join(parts))

def ref_html(ref):
    u = urlparse(ref)
    if u.scheme in ("http", "https") and u.hostname and not _internal().search(u.hostname):
        return f'<a href="{html.escape(ref, quote=True)}" rel="noopener noreferrer">{html.escape(u.hostname)}</a>'
    return "<em>internal reference</em>"

def card(r):
    e = html.escape
    ev = "".join(f"<li>{e(x['claim'])} <span class=ref>({ref_html(x['ref'])})</span></li>" for x in r["evidence"])
    src = r["source"]
    tags = " ".join(f"<span class=tag>{e(t)}</span>" for t in r.get("tags", []))
    when = r["signoff"].get("at", "")[:10]
    return (f'<article id="{e(r["id"])}"><h2>{e(r["id"].replace("-", " "))}</h2>'
            f'<p class=meta>{e(src["kind"])} · {ref_html(src["ref"])} · approved {e(when)}</p>'
            f'<h3>What happened</h3><p>{e(r["what_happened"])}</p>'
            f'<h3>Lesson</h3><p class=lesson>{e(r["lesson"])}</p>'
            f'<h3>Evidence</h3><ul>{ev}</ul><p>{tags}</p></article>')

PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>MC SOC lessons</title>
<style>
:root{{--bg:#fff;--fg:#1b1b1f;--mute:#5b5b66;--line:#d9d9e0;--acc:#7a3cff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e0e12;--fg:#ececf1;--mute:#9a9aa8;--line:#2a2a33;--acc:#a58bff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif;padding:1rem}}
main{{max-width:46rem;margin:0 auto}} h1{{margin:1.5rem 0 .25rem}} h2{{margin:0;text-transform:capitalize}}
h3{{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:1rem 0 .25rem}}
article{{border-top:1px solid var(--line);padding:1.25rem 0}} .meta,.ref{{color:var(--mute);font-size:.85rem}}
.lesson{{border-left:3px solid var(--acc);padding-left:.75rem}} a{{color:var(--acc)}}
.tag{{border:1px solid var(--line);border-radius:.6rem;padding:.05rem .5rem;font-size:.8rem;margin-right:.25rem}}
.lyrics{{white-space:pre-wrap;font:inherit;border-left:3px solid var(--acc);padding-left:.75rem}}
</style></head><body><main><h1>MC SOC lessons</h1>
<p class=meta>{n} approved lesson(s). Restated in our own words; each links back to where it can be checked.</p>
{cards}</main></body></html>
"""


def work_card(w):
    """A derived work: its text, the lessons it came from, and when it was approved (no approver name, no references)."""
    e = html.escape
    when = w["signoff"].get("at", "")[:10]
    lessons = ", ".join(e(x) for x in w.get("lesson_ids", []))
    return (f'<article id="{e(w["id"])}"><h2>{e(w["id"].replace("-", " "))}</h2>'
            f'<p class=meta>derived work · form {e(w.get("form", ""))} · from lessons: {lessons} · approved {e(when)}</p>'
            f'<pre class=lyrics>{e(w["content"])}</pre></article>')


def publish(records, out, works=()):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    page = out / "index.html"
    cards = "\n".join(card(r) for r in records)
    if works:
        cards += "\n<h1>Derived works</h1>\n" + "\n".join(work_card(w) for w in works)
    page.write_text(PAGE.format(n=len(records), cards=cards))
    return [str(page)]
