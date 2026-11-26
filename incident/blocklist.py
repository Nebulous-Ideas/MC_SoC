"""Block-list feeds -> lookup-table files for Graylog (the same pattern as the geoip files).

Fetches the feeds you list in a config, validates every entry by value, and writes three small files that a Graylog CSV file data adapter
(or a pipeline `cidr_match`) can read:

    blocklist_ip.csv       key,list,first_seen        exact addresses
    blocklist_domain.csv   key,list,first_seen        lower-cased domain names
    blocklist_cidr.txt     cidr,list                  ranges (for cidr_match; the CSV adapter matches exact keys only)

A pipeline rule then stamps a field (for example `listed_in`) on messages whose addresses are listed, so a hunt can read a field instead
of parsing message text. Feed content is untrusted data: it only ever becomes a validated row in a file, never query text or a command.

Safeguards against a bad or poisoned feed: https only, a size cap, a per-list entry cap, private/loopback/reserved addresses and ranges
broader than /16 (IPv4) or /32 (IPv6 prefix floor 32) are dropped, an allowlist of values that must never be listed, and a shrink guard that
keeps the previous list when a feed suddenly loses most of its entries (a truncated download or an emptied feed). `first_seen` is kept
across runs so entries can age out (`max_age_days`). Stdlib only; the opener is injectable, so tests use no network.

Config (JSON; no feed is built in, and none ships with this repo, because licences differ):
  {"out_dir": "/var/lib/graylog-lookups", "max_age_days": 90, "allowlist": ["203.0.113.0/24", "example.org"],
   "feeds": [{"name": "example-ips", "url": "https://feeds.example.org/ips.txt", "kind": "auto"}]}
`kind`: "auto" (one entry per line; `#`/`;` comments; hosts-file lines like `0.0.0.0 bad.example.org`; first token is used) or "csv:N" (column N, 0-based).
Not tried against a real feed or a real Graylog; fake-tested only.
"""
import csv, io, ipaddress, json, os, re, sys, tempfile, time, urllib.parse, urllib.request

MAX_BYTES, MAX_ENTRIES, SHRINK_KEEP = 8_000_000, 300_000, 0.5
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MIN_PREFIX = {4: 16, 6: 32}
FILES = {"ip": "blocklist_ip.csv", "domain": "blocklist_domain.csv", "cidr": "blocklist_cidr.txt"}


class BlocklistError(Exception):
    pass


# Documentation ranges are not "global" to Python; no real feed lists them, and accepting them lets tests and examples use placeholders.
DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]


def _public(a):
    return a.is_global or any(a.version == n.version and a in n for n in DOC_NETS)


def classify(token, allow=()):
    """(kind, normalised value) for a well-formed public address, range or domain; None otherwise (including anything allow-listed)."""
    t = (token or "").strip().strip("\"'").lower()
    if not t or len(t) > 253:
        return None
    entry = None
    try:
        if "/" in t:
            n = ipaddress.ip_network(t, strict=False)
            if n.prefixlen < MIN_PREFIX[n.version] or not _public_net(n):
                return None
            entry = ("ip", str(n.network_address)) if n.num_addresses == 1 else ("cidr", str(n))
        else:
            a = ipaddress.ip_address(t)
            if not _public(a):
                return None
            entry = ("ip", str(a))
    except ValueError:
        if DOMAIN.match(t) and not t.endswith((".local", ".internal", ".lan", ".arpa")):
            entry = ("domain", t)
    if entry and _allowed(entry, allow):
        return None
    return entry


def _public_net(n):
    return _public(n.network_address) and _public(n.broadcast_address)


def _allowed(entry, allow):
    kind, val = entry
    for a in allow:
        a = str(a).strip().lower()
        try:
            net = ipaddress.ip_network(a, strict=False)
            if kind in ("ip", "cidr"):
                other = ipaddress.ip_network(val, strict=False)
                if other.version == net.version and (other.subnet_of(net) or net.subnet_of(other)):
                    return True
            continue
        except ValueError:
            pass
        if kind == "domain" and (val == a or val.endswith("." + a)):
            return True
    return False


def parse_feed(text, kind="auto", allow=()):
    """Entries [(kind, value)] from a feed body. Lines that do not yield a valid entry are skipped and counted by the caller."""
    out, skipped = [], 0
    col = int(kind.split(":", 1)[1]) if kind.startswith("csv:") else None
    for raw in text.splitlines():
        line = re.split(r"[#;]", raw, maxsplit=1)[0].strip() if col is None else raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if col is None:
            parts = line.replace(",", " ").split()
            cands = parts[:2] if parts and parts[0] in ("0.0.0.0", "127.0.0.1") and len(parts) > 1 else parts[:1]
            tok = cands[-1] if cands else ""
        else:
            row = next(csv.reader([line]), [])
            tok = row[col] if len(row) > col else ""
        e = classify(tok, allow)
        if e:
            out.append(e)
        else:
            skipped += 1
    return out, skipped


def fetch(url, opener=urllib.request.urlopen, timeout=30):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise BlocklistError("feeds must be https URLs")
    req = urllib.request.Request(url, headers={"User-Agent": "mc-soc-blocklist"})
    with opener(req, timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise BlocklistError("feed larger than the size cap")
    return data.decode("utf-8", "replace")


def _read_previous(out_dir):
    """{(kind, value): (list, first_seen)} from the files written last time (so first_seen survives and shrink can be judged)."""
    prev = {}
    for kind in ("ip", "domain"):
        p = os.path.join(out_dir, FILES[kind])
        if os.path.exists(p):
            with open(p, newline="") as f:
                for row in csv.DictReader(f):
                    prev[(kind, row["key"])] = (row["list"], row["first_seen"])
    p = os.path.join(out_dir, FILES["cidr"])
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                c = line.rstrip("\n").split(",")
                if len(c) >= 2:
                    prev[("cidr", c[0])] = (c[1], c[2] if len(c) > 2 else "")
    return prev


def _atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".bl-")
    with os.fdopen(fd, "w", newline="") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def build(config, opener=urllib.request.urlopen, now=None):
    """Fetch, validate and write the lookup files. Returns {list name: {entries, skipped, kept_previous, error}}; never raises for one bad feed."""
    out_dir, allow = config["out_dir"], config.get("allowlist", [])
    max_age = int(config.get("max_age_days", 90)) * 86400
    now = time.time() if now is None else now
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    os.makedirs(out_dir, exist_ok=True)
    prev = _read_previous(out_dir)
    result, merged = {}, {}
    for feed in config["feeds"]:
        name = feed.get("name", "")
        if not NAME.match(name):
            raise BlocklistError("feed names must be letters, digits, - or _")
        info = result[name] = {"entries": 0, "skipped": 0, "kept_previous": False, "error": None}
        before = {k: v for k, v in prev.items() if v[0] == name}
        try:
            entries, skipped = parse_feed(fetch(feed["url"], opener), feed.get("kind", "auto"), allow)
            entries = list(dict.fromkeys(entries))
            if len(entries) > MAX_ENTRIES:
                raise BlocklistError("feed has more entries than the cap")
            if before and len(entries) < SHRINK_KEEP * len(before):
                raise BlocklistError("feed shrank by more than half; previous list kept")
            info.update(entries=len(entries), skipped=skipped)
            for e in entries:
                first = before.get(e, (name, today))[1] or today
                merged[e] = (name, first)
        except Exception as ex:
            info["error"] = f"{type(ex).__name__}: {str(ex)[:80]}"
            info["kept_previous"] = bool(before)
            for k, v in before.items():
                merged[k] = v
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(now - max_age))
    merged = {k: v for k, v in merged.items() if v[1] >= cutoff}
    for kind in ("ip", "domain"):
        rows = sorted((k[1], v[0], v[1]) for k, v in merged.items() if k[0] == kind)
        buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n"); w.writerow(["key", "list", "first_seen"]); w.writerows(rows)
        _atomic_write(os.path.join(out_dir, FILES[kind]), buf.getvalue())
    _atomic_write(os.path.join(out_dir, FILES["cidr"]),
                  "".join(f"{k[1]},{v[0]},{v[1]}\n" for k, v in sorted(merged.items()) if k[0] == "cidr"))
    return result


def main(argv=None):
    path = (argv or sys.argv[1:] or [os.environ.get("BLOCKLIST_CONFIG", "")])[0]
    if not path:
        sys.exit("usage: blocklist.py CONFIG.json  (or set BLOCKLIST_CONFIG)")
    with open(path) as f:
        res = build(json.load(f))
    for name, i in res.items():   # counts and the error type only; never feed content
        print(f"{name}: {i['entries']} entries, {i['skipped']} skipped" + (f", {i['error']}" if i["error"] else ""))
    sys.exit(1 if any(i["error"] for i in res.values()) else 0)


if __name__ == "__main__":
    main()
