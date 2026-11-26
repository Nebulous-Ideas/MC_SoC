"""Case state for an agent working an incident: the "Orient" picture as a structured object, with an expansion gate.

An agent that enriches indicators live and hunts for them across backend systems keeps changing its own picture of the incident,
and can talk itself into a far larger incident than there is. This keeps that picture explicit and checkable:

- Every fact has sources, each with a trust level; untrusted or low-trust enrichment can never confirm anything on its own.
- Verdicts conflict visibly instead of being averaged away. Known-benign values (an allowlist) are refuted and never expand the case.
- Growth is gated: a small batch inside the declared scope is applied; a big batch, or any new system, waits for a named person.
  The approver's name comes from the caller (the platform), never from the model; the same refusals as review.decide apply.
- A query budget stops open-ended hunting; reorient() snapshots the picture and returns a diff for a person to read.
- Enrichment text is data. It is stored, shown, and masked by value on export; it is never run or fed back as an instruction.

Stdlib only; no network. A source adapter feeds it and an operator surface shows the diff. Fake-tested only.
"""
import ipaddress, time
from dataclasses import dataclass, field
import verify as V

TRUST = {"system": 3, "high": 3, "medium": 2, "low": 1, "untrusted": 0}
CAP_WITHOUT_TRUSTED = 0.4


class CaseError(Exception):
    pass


@dataclass
class Fact:
    id: str
    kind: str
    value: str
    status: str = "suspected"      # suspected | confirmed | refuted
    confidence: float = 0.2
    conflict: bool = False
    reason: str = ""
    sources: list = field(default_factory=list)   # {source, trust, verdict, note, at}


@dataclass
class Proposal:
    id: str
    items: list
    refused: list
    needs_approval: bool
    reasons: list
    applied: bool = False


class CaseState:
    def __init__(self, scope_systems, allowlist=(), max_new_per_step=5, max_entities=50, max_queries=100,
                 reorient_growth=0.25, reorient_every_s=900, clock=time.time):
        self.scope = set(scope_systems)
        self.allowlist = list(allowlist)
        self.max_new, self.max_entities, self.queries_left = max_new_per_step, max_entities, max_queries
        self.reorient_growth, self.reorient_every_s, self.clock = reorient_growth, reorient_every_s, clock
        self.facts, self.proposals, self.approvals, self.snapshots = {}, {}, [], []
        self._n = 0

    # --- facts ---
    def _fid(self, kind, value):
        return f"{kind}:{value}"

    def _benign(self, value):
        for a in self.allowlist:
            try:
                if "/" in a and ipaddress.ip_address(value) in ipaddress.ip_network(a, strict=False):
                    return True
            except ValueError:
                pass
            if value == a or value.endswith("." + a):
                return True
        return False

    def observe(self, kind, value, source, trust="system", note=""):
        """Record something our own telemetry saw. It starts suspected; seeing a value in a log is not a verdict on it."""
        f = self.facts.get(self._fid(kind, value)) or self.facts.setdefault(self._fid(kind, value), Fact(self._fid(kind, value), kind, value))
        f.sources.append({"source": source, "trust": trust, "verdict": "seen", "note": note, "at": self.clock()})
        if self._benign(value):
            f.status, f.confidence, f.reason = "refuted", 0.0, "known-benign"
        else:
            self._rescore(f)
        return f

    def enrich(self, fact_id, source, trust, verdict, note=""):
        if verdict not in ("malicious", "benign", "unknown"):
            raise CaseError("verdict must be malicious, benign or unknown")
        f = self.facts[fact_id]
        f.sources.append({"source": source, "trust": trust, "verdict": verdict, "note": note, "at": self.clock()})
        self._rescore(f)
        return f

    def _rescore(self, f):
        if f.reason == "known-benign":
            return
        good = [s for s in f.sources if TRUST.get(s["trust"], 0) >= 2]
        bad_v = [s for s in good if s["verdict"] == "malicious"]
        ben_v = [s for s in good if s["verdict"] == "benign"]
        any_mal = any(s["verdict"] == "malicious" for s in f.sources)
        f.conflict = bool(bad_v and ben_v)
        seen_by_system = any(s["trust"] == "system" and s["verdict"] == "seen" for s in f.sources)
        if f.conflict:
            f.status, f.confidence = "suspected", 0.3
        elif ben_v and not bad_v:
            f.status, f.confidence = "refuted", 0.0
        elif bad_v and (len(bad_v) >= 2 or seen_by_system):
            f.status, f.confidence = "confirmed", min(0.95, 0.6 + 0.15 * len(bad_v))
        else:
            f.status = "suspected"
            f.confidence = min(CAP_WITHOUT_TRUSTED, 0.2 + 0.1 * sum(1 for s in f.sources if s["verdict"] == "malicious")) if any_mal else 0.2

    # --- growth gate ---
    def propose(self, items):
        """Candidate new facts from a hunt. Returns a Proposal; small in-scope batches are applied at once."""
        refused, keep = [], []
        for it in items:
            if self._benign(it["value"]):
                refused.append({**it, "reason": "known-benign"})
            else:
                keep.append(it)
        new = [it for it in keep if self._fid(it["kind"], it["value"]) not in self.facts]
        reasons = []
        if len(new) > self.max_new:
            reasons.append(f"{len(new)} new entities in one step (limit {self.max_new})")
        if len(self.facts) + len(new) > self.max_entities:
            reasons.append(f"total would pass {self.max_entities} entities")
        out = sorted({it["system"] for it in keep if it.get("system") and it["system"] not in self.scope})
        if out:
            reasons.append("new system(s) outside scope: " + ", ".join(out))
        self._n += 1
        p = Proposal(f"p{self._n}", keep, refused, bool(reasons), reasons)
        self.proposals[p.id] = p
        if not p.needs_approval:
            self._apply(p)
        return p

    def _apply(self, p):
        for it in p.items:
            self.observe(it["kind"], it["value"], it["source"], it.get("trust", "system"))
            if it.get("system"):
                self.scope.add(it["system"])
        p.applied = True

    def approve(self, pid, by, confirm):
        """A named person applies a held proposal. `confirm` is answered by the person, not the model."""
        name = (by or "").strip()
        if not name or name.lower() in V.NON_HUMAN:
            raise CaseError("no named human; refusing")
        p = self.proposals.get(pid)
        if not p or p.applied:
            raise CaseError("no such pending proposal")
        if not confirm(f"APPLY {pid}: {len(p.items)} item(s); " + "; ".join(p.reasons)):
            raise CaseError("not confirmed; nothing changed")
        self._apply(p)
        self.approvals.append({"proposal": pid, "by": name, "at": self.clock()})
        return p

    def spend_query(self, n=1):
        if self.queries_left < n:
            return False
        self.queries_left -= n
        return True

    # --- picture ---
    def snapshot(self):
        return {"at": self.clock(), "scope": sorted(self.scope),
                "facts": {k: {"status": f.status, "confidence": round(f.confidence, 2), "conflict": f.conflict} for k, f in self.facts.items()}}

    def reorient(self):
        """Take a new snapshot and return what changed since the last one."""
        new, old = self.snapshot(), (self.snapshots[-1] if self.snapshots else {"facts": {}, "scope": []})
        diff = {"added": sorted(set(new["facts"]) - set(old["facts"])),
                "status_changed": [{"id": k, "from": old["facts"][k]["status"], "to": v["status"]}
                                   for k, v in new["facts"].items() if k in old["facts"] and old["facts"][k]["status"] != v["status"]],
                "scope_added": sorted(set(new["scope"]) - set(old["scope"]))}
        self.snapshots.append(new)
        return diff

    def should_reorient(self):
        if not self.snapshots:
            return ["no picture taken yet"]
        last, why = self.snapshots[-1], []
        base = max(1, len(last["facts"]))
        if (len(self.facts) - len(last["facts"])) / base >= self.reorient_growth:
            why.append(f"scope grew {len(self.facts) - len(last['facts'])} of {base} since the last picture")
        if self.clock() - last["at"] >= self.reorient_every_s:
            why.append("time since the last picture")
        return why

    def export(self):
        """Plain data for a person or a log; any secret-shaped string is masked by value."""
        def mask(v):
            if isinstance(v, str):
                return "[masked]" if V.scan_value(v) else v
            if isinstance(v, dict):
                return {k: mask(x) for k, x in v.items()}
            if isinstance(v, list):
                return [mask(x) for x in v]
            return v
        return mask({"scope": sorted(self.scope), "queries_left": self.queries_left,
                     "facts": {k: {"kind": f.kind, "value": f.value, "status": f.status, "confidence": round(f.confidence, 2),
                                   "conflict": f.conflict, "reason": f.reason, "sources": f.sources} for k, f in self.facts.items()}})
