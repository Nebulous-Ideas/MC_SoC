"""Read-only telemetry sources for the incident case state: Graylog (log search) and InfluxDB (Flux), plus the hunt loop.

`hunt()` searches your own telemetry for indicators and feeds what it finds into a CaseState. It spends the case's query budget, refuses
anything that is not a well-formed indicator (indicators can come from untrusted enrichment, so they are never pasted into a query as
free text), keeps only validated field values from the rows (never message bodies), and sends new entities through the case's expansion
gate, so anything outside scope or over the limits waits for a person.

Credentials come from the caller (read them from environment variables yourself); nothing here reads or stores them, and they are only
placed in the request headers. The transports are plain urllib, stdlib only. Fake-tested only: the Graylog transport posts to the views
search API (`/api/views/search/sync`), because the legacy `/api/search/universal/...` endpoints are gone in current versions; its body
and response shapes come from community examples and must be checked against your server's REST API browser. The InfluxDB transport posts
Flux to `/api/v2/query`. Neither has been run against a real server.
"""
import base64, csv, io, ipaddress, json, re, urllib.parse, urllib.request

DOMAIN = re.compile(r"^(?=.{4,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
HASH = re.compile(r"^(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


# Field names seen on a firewall/DNS/proxy stream of a Graylog 7.2 server (read through its MCP field listing; names only, no values).
# They are a starting point, not a standard: field names depend on how your inputs and pipelines parse each stream, so list yours first
# (`check_graylog.py`) and edit this map. A row field maps to a fact kind: "host" (a system name) or "ioc" (an address, domain or hash).
EXAMPLE_GRAYLOG_FIELD_MAP = {"source": "host", "src_ip": "ioc", "dest_ip": "ioc", "dns_qname": "ioc"}


def valid_ioc(value):
    """True only for an IP address, a domain name or a hex hash. Everything else (quotes, spaces, wildcards, URLs) is refused."""
    if not isinstance(value, str) or not value or len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    return bool(DOMAIN.match(value) or HASH.match(value))


def graylog_search_body(query, since_s, limit):
    """The views-search body for a relative time range and one message table. Built from community examples of POST /api/views/search/sync;
    check it against your server's REST API browser (System > REST API Browser) before trusting it, since field names have moved between versions."""
    return {"queries": [{"id": "q1", "query": {"type": "elasticsearch", "query_string": query},
                         "timerange": {"type": "relative", "range": int(since_s)},
                         "search_types": [{"id": "st1", "type": "messages", "limit": int(limit), "offset": 0,
                                           "timerange": None, "query": None, "streams": []}]}]}


def graylog_rows(response):
    """Message field dicts from a views-search response: results -> query -> search_types -> message table -> messages."""
    rows = []
    for q in (response.get("results") or {}).values():
        for st in (q.get("search_types") or {}).values():
            rows += [m.get("message", {}) for m in st.get("messages", [])]
    return rows


def graylog_transport(base_url, token, opener=urllib.request.urlopen, timeout=60):
    """search(query, since_s, limit) -> list of message field dicts, through the views search API (Graylog 5 to 7). One POST that only
    reads; the token goes only in the Authorization header (HTTP basic with the token as the user name), never in the URL or a log."""
    auth = "Basic " + base64.b64encode(f"{token}:token".encode()).decode()

    def search(query, since_s, limit):
        body = json.dumps(graylog_search_body(query, since_s, limit)).encode()
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/views/search/sync?timeout={int(timeout) * 1000}", data=body, method="POST",
                                     headers={"Authorization": auth, "Accept": "application/json", "Content-Type": "application/json",
                                              "X-Requested-By": "mc-soc-hunt"})
        with opener(req, timeout=timeout) as r:
            return graylog_rows(json.loads(r.read()))[:limit]
    return search


def influx_transport(base_url, token, org, flux_template, opener=urllib.request.urlopen, timeout=30):
    """search(value, since_s, limit) -> list of row dicts. The Flux comes from your template with {value}, {since_s} and {limit}
    filled in; the value must be a well-formed indicator or the call raises ValueError before anything is sent."""
    def search(value, since_s, limit):
        if not valid_ioc(value):
            raise ValueError("not a well-formed indicator")
        flux = flux_template.format(value=value, since_s=int(since_s), limit=int(limit))
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/v2/query?org={urllib.parse.quote(org)}", data=flux.encode(), method="POST",
                                     headers={"Authorization": f"Token {token}", "Content-Type": "application/vnd.flux", "Accept": "application/csv"})
        with opener(req, timeout=timeout) as r:
            text = r.read().decode()
        lines = [l for l in text.splitlines() if l and not l.startswith("#")]
        return list(csv.DictReader(io.StringIO("\n".join(lines))))[:limit]
    return search


def hunt(case, search, indicators, field_map, since_s=3600, limit=50, source_name="telemetry", query=lambda v: f'"{v}"'):
    """Search `indicators` ([{kind, value}]) and feed the case. field_map maps a row field to a fact kind: {"source": "host", "src_ip": "ioc"}.
    `query` turns a validated value into what the transport expects (a quoted phrase for Graylog; pass `lambda v: v` for the InfluxDB transport). Returns a summary; held expansions are in out["pending"] for a person to approve with case.approve()."""
    out = {"hits": {}, "refused": [], "pending": [], "budget_exhausted": False}
    for ind in indicators:
        v = ind.get("value")
        if not valid_ioc(v):
            out["refused"].append({"value": str(v)[:40], "reason": "not a well-formed indicator"}); continue
        if not case.spend_query():
            out["budget_exhausted"] = True; break
        rows = search(query(v), since_s, limit)
        out["hits"][v] = len(rows)
        if not rows:
            continue
        case.observe(ind.get("kind", "ioc"), v, source_name, "system")
        items, seen = [], set()
        for row in rows:
            system = next((str(row[f]) for f, k in field_map.items() if k == "host" and HOST.match(str(row.get(f, "")))), None)
            for f, k in field_map.items():
                val = str(row.get(f, ""))
                ok = HOST.match(val) if k == "host" else valid_ioc(val)
                if ok and val != v and (k, val) not in seen:
                    seen.add((k, val))
                    items.append({"kind": k, "value": val, "system": system if k != "host" else val, "source": source_name, "trust": "system"})
        if items:
            p = case.propose(items)
            if p.needs_approval:
                out["pending"].append({"id": p.id, "reasons": p.reasons, "items": len(p.items)})
    out["queries_left"] = case.queries_left
    return out
