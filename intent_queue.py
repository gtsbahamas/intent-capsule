#!/usr/bin/env python3
"""
intent-queue — capture high-context intent capsules and queue them for cold replay.

Workflow this serves:
  btw (at peak context) authors a v-intent capsule -> you copy it (C) ->
  `intent-queue add` validates + queues it -> a FRESH session drains it cold via `next`.

The point (proven empirically in this folder): the v-intent grammar's labeled fields
prevent the omissions terse prose makes (it drops WHERE and ACCEPTANCE). So this queue
treats the grammar as a CONTRACT — capsules missing required fields are rejected at
capture, when context is fresh and the gap is cheap to fix.

Grammar:
  @<id>     do: <build>   in: <files/layer>   on: <deps>
  !: <hard constraint>  ~: <soft pref>  ?: <gate>  =: <acceptance>  why: <nuance>

Usage:
  intent-queue add [--source S] [--file F]      # F, else stdin, else clipboard (pbpaste)
  intent-queue validate [--file F] [--strict [--plan P]]   # completeness; --strict adds the deterministic plan-ops gate
  intent-queue list [--status pending|active|all]
  intent-queue next [--strict [--plan P]]       # oldest pending -> in_progress, prints capsule; --strict refuses a malformed one
  intent-queue done <id> --proof "..." [--proof "..."]   # one --proof per acceptance criterion, in order
  intent-queue drop <id> --yes
  intent-queue reap [--older-than MIN] [--yes]  # resurface orphaned in_progress -> pending
  intent-queue pickup                           # fresh-session startup view (pending + orphans)
Env: INTENT_QUEUE=/path/to/queue.jsonl  (default ~/.claude/intent-queue.jsonl)
"""
import os, sys, re, json, argparse, subprocess
from collections import namedtuple
from datetime import datetime, timezone

QUEUE = os.environ.get("INTENT_QUEUE", os.path.expanduser("~/.claude/intent-queue.jsonl"))
SINGLE = {"do","in","on","why","?"}          # at most one
REPEAT = {"!","~","="}                          # zero or more -> list
REQUIRED = ["id","do","="]                      # the anti-omission contract
RECOMMENDED = ["in","why"]
TAG_RE = re.compile(r"^(do|in|on|why|[!~?=]):\s*(.*)$")
ORPHAN_MIN = 120                                 # in_progress older than this (min) is reap-eligible

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _age_min(iso):
    """Age in minutes of an ISO timestamp; +inf if missing/unparseable (=> treat as stale)."""
    if not iso:
        return float("inf")
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 60.0
    except Exception:
        return float("inf")

def _dep_tokens(on_str):
    """Tokenize an `on:` string into candidate dependency tokens.

    Splits on commas and whitespace. Ids are case-sensitive (no lowercasing),
    so hyphenated capsule ids survive intact. Embedded prose is harmless: only
    tokens that later match a queued id gate anything (see _classify)."""
    if not on_str:
        return []
    return [t for t in re.split(r"[,\s]+", on_str.strip()) if t]

def _status_map(items):
    """id -> status over the entire queue. If an id appears more than once
    (a finished row plus a re-queued active one), prefer the ACTIVE status so a
    dependency is not treated as satisfied by a stale `done` row."""
    m = {}
    for it in items:
        id_, st = it.get("id"), it.get("status")
        if id_ is None or st is None:
            continue
        # Two active rows for one id: first-encountered wins (FIFO matches cmd_add insertion order).
        if id_ not in m or (m[id_] in ("done", "dropped") and st in ("pending", "in_progress")):
            m[id_] = st
    return m

def _classify(item, status_map):
    """Blocker analysis for one capsule against the queue's id->status map.

    Returns {ready, waiting, dead, unknown}:
      waiting - dep ids that exist but aren't done (pending/in_progress)
      dead    - dep ids whose capsule was dropped (unsatisfiable)
      unknown - tokens matching no queued id (non-gating; informational)
    ready == no waiting and no dead."""
    waiting, dead, unknown = [], [], []
    for tok in _dep_tokens(item.get("parsed", {}).get("on", "")):
        st = status_map.get(tok)
        if st is None:
            unknown.append(tok)
        elif st == "done":
            continue
        elif st == "dropped":
            dead.append(tok)
        else:                                    # pending / in_progress
            waiting.append(tok)
    return {"ready": not waiting and not dead,
            "waiting": waiting, "dead": dead, "unknown": unknown}

def _find_cycles(items):
    """Cycles in the `on:` graph restricted to UNFINISHED capsules
    (pending/in_progress). Only unfinished deps can deadlock — a `done` dep is a
    satisfied edge, not a wait. Returns a list of cycles, each a list of ids; a
    capsule depending on itself is a length-1 cycle. Each distinct cycle once.
    Assumes the dependency graph is well under Python's recursion limit (~1000); a
    pathological linear chain that long would need an iterative DFS."""
    active = {it["id"] for it in items if it["status"] in ("pending", "in_progress")}
    adj = {}
    for it in items:
        if it["status"] not in ("pending", "in_progress"):
            continue
        adj[it["id"]] = [t for t in _dep_tokens(it.get("parsed", {}).get("on", "")) if t in active]
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack, cycles, seen = [], [], set()

    def dfs(n):
        color[n] = GRAY
        stack.append(n)
        for m in adj.get(n, []):
            if m == n:
                key = (n,)
                if key not in seen:
                    seen.add(key); cycles.append([n])
            elif color.get(m, BLACK) == GRAY:
                cyc = stack[stack.index(m):]
                key = tuple(sorted(cyc))
                if key not in seen:
                    seen.add(key); cycles.append(cyc)
            elif color.get(m, BLACK) == WHITE:
                dfs(m)
        stack.pop()
        color[n] = BLACK

    for n in adj:
        if color[n] == WHITE:
            dfs(n)
    return cycles

def parse_capsule(text):
    """v-intent capsule -> {id, do, in, on, why, ?, !:[], ~:[], =:[], _dupes:[]}. Tolerant.

    Blank tag values are treated as ABSENT (a bare `=:` is not an acceptance criterion).
    A SINGLE field repeated is recorded in _dupes (it would silently overwrite)."""
    out: dict = {k: [] for k in REPEAT}
    out["_dupes"] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("@") and "id" not in out and not TAG_RE.match(line[1:].strip()):
            out["id"] = line[1:].strip().split()[0] if line[1:].strip() else ""
            continue
        m = TAG_RE.match(line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if not val:                              # blank value => not present (closes empty-=: hole)
            continue
        if tag in REPEAT:
            out[tag].append(val)
        else:
            if tag in out and tag != "id":       # SINGLE already set => silent-overwrite foot-gun
                out["_dupes"].append(tag)
            out[tag] = val
    return out

def check(parsed):
    """returns (errors, warnings) against the contract."""
    errs, warns = [], []
    for r in REQUIRED:
        v = parsed.get(r)
        if not v or (isinstance(v, list) and not v):
            errs.append(f"missing required field: {r!r}"
                        + (" (acceptance — what proves it's done?)" if r == "=" else ""))
    for r in RECOMMENDED:
        if not parsed.get(r):
            warns.append(f"missing recommended field: {r!r}")
    for tag in parsed.get("_dupes", []):
        warns.append(f"field {tag!r} set more than once — only the last value is kept")
    return errs, warns

# ─────────────────────────────────────────────────────────────────────────────
# Deterministic strict validator — the code-level safety layer the model isn't.
#
# RESULTS.md's load-bearing caveat: the MODEL executes ~31% of malformed plan-ops
# lines instead of refusing them (adversarial loud-fail stuck at ~69%). So any
# pipeline that APPLIES capsules unattended needs a deterministic gate FIRST. This
# is it: stdlib-only, no LLM, no network, identical behaviour offline.
#
# It validates the PLAN-OPS grammar (`OP id [deps] [@owner] [#status] [:note]`,
# legend in harness.py), NOT the v-intent capsule grammar. v-intent lines (do:/in:/
# !:/=:/@id …) are skipped, so a normal rich-intent capsule yields zero plan-ops
# lines and always passes — the bang/tilde/question collisions (`!:` vs `!id`,
# `~:` vs `~id`, `?:` vs `?id`) are disambiguated by the colon the tag carries.
#
# The four failure modes are exactly the adversarial-bucket cases (harness.py):
# self-dep, unknown-id, op-char-id, dup-id.
OP_CHARS    = set("+~vx>!?")                                  # single-char op tokens
PREFIX_OPS  = {"+":"new","~":"edit",">":"prefer","!":"must","?":"query"}  # OP attaches to id
BARE_OPS    = {"v":"done","x":"drop","rm":"drop"}            # OP is its own token (rm = v3 drop)
Rejection   = namedtuple("Rejection", ["reason", "line"])

def _strip_planops_note(s):
    """Drop a trailing note (`:"..."` quoted, or ` :bare`) so it can't skew tokenizing."""
    q = s.find(':"')
    if q != -1:
        return s[:q].rstrip()
    b = s.find(" :")                                          # bare note marker is space-colon
    if b != -1:
        return s[:b].rstrip()
    return s

def parse_planops_line(line):
    """A plan-ops op line -> {op,id,deps,first} or None if the line isn't a guarded op.

    Returns None for v-intent tag lines, @id headers, prose continuations, and bare
    existing-id references — anything that isn't an OP we guard."""
    s = line.strip()
    if not s:
        return None
    toks = _strip_planops_note(s).split()
    if not toks:
        return None
    first = toks[0]
    if first in BARE_OPS:                                     # `v id`, `x id`, `rm id`
        op, id_, rest = BARE_OPS[first], (toks[1] if len(toks) > 1 else ""), toks[2:]
    elif first[0] in PREFIX_OPS:                              # `+id`, `~id`, `?id`, `!id`, `>id`
        op, id_, rest = PREFIX_OPS[first[0]], first[1:], toks[1:]
    else:
        return None                                          # unrecognized first token — not ours
    deps = []
    for t in rest:                                           # `<a,b` blockedBy / `>a,b` blocks
        if t[:1] in ("<", ">"):
            deps += [d for d in t[1:].split(",") if d]
    return {"op": op, "id": id_, "deps": deps, "first": first}

def strict_validate(text, plan_ids=None):
    """Return a list of Rejection(reason, line) for plan-ops violations. Empty == clean.

    plan_ids: existing node ids. When supplied, edit/done/drop/query/prefer/must on an
    id that is neither in the plan nor created by a `+new` in this same capsule is an
    unknown-id rejection. `+new` ids are always exempt. Without a plan, the unknown-id
    check is skipped (you can't know what's unknown)."""
    plan = set(plan_ids) if plan_ids is not None else None
    ops = []                                                 # (parsed, original_line)
    new_ids = set()                                          # +new ids known within this capsule
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("@") and not TAG_RE.match(s[1:].strip()):
            continue                                         # @id header (v-intent)
        if TAG_RE.match(s):
            continue                                         # v-intent tag line (do:/!:/=: …)
        p = parse_planops_line(s)
        if p is None:
            continue
        ops.append((p, raw.rstrip()))
        if p["op"] == "new" and p["id"]:
            new_ids.add(p["id"])
    rej, target_counts = [], {}
    for p, line in ops:
        oid = p["id"]
        if not oid:
            rej.append(Rejection(f"op {p['first']!r} has no target id", line)); continue
        if p["op"] == "new" and (oid[0] in OP_CHARS or oid.startswith("rm")):
            rej.append(Rejection(
                f"new id {oid!r} starts with an op char {oid[0]!r} — ambiguous with the op grammar", line))
        if oid in p["deps"]:
            rej.append(Rejection(f"node {oid!r} depends on / blocks itself (self-dep)", line))
        if plan is not None and p["op"] != "new" and oid not in plan and oid not in new_ids:
            rej.append(Rejection(f"{p['op']} targets unknown id {oid!r} (not in the supplied plan)", line))
        target_counts[oid] = target_counts.get(oid, 0) + 1
    for oid, c in target_counts.items():
        if c > 1:
            rej.append(Rejection(f"id {oid!r} is a target {c}× in one capsule (duplicate id)", None))
    return rej

def load_plan(path):
    """Read a plan.json ({'nodes':[{'id':…}, …]}) -> list of ids, or None if no path."""
    if not path:
        return None
    with open(path) as f:
        d = json.load(f)
    return [n["id"] for n in d.get("nodes", []) if isinstance(n, dict) and "id" in n]

def _print_rejections(rej):
    print(f"\n  STRICT — {len(rej)} deterministic rejection(s):")
    for r in rej:
        print(f"  ✗ {r.reason}" + (f"\n      >> {r.line.strip()}" if r.line else ""))

def read_input(file):
    if file:
        return open(file).read()
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data
    try:  # the "C button" path
        return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    except Exception:
        return ""

def load():
    if not os.path.exists(QUEUE):
        return []
    with open(QUEUE) as f:
        return [json.loads(l) for l in f if l.strip()]

def save(items):
    with open(QUEUE, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")

def cmd_validate(text, strict=False, plan_ids=None):
    parsed = parse_capsule(text)
    errs, warns = check(parsed)
    print(f"id: {parsed.get('id','(none)')}   do: {parsed.get('do','(none)')[:60]}")
    print(f"  in:{'Y' if parsed.get('in') else '—'} on:{'Y' if parsed.get('on') else '—'} "
          f"why:{'Y' if parsed.get('why') else '—'} gate:{'Y' if parsed.get('?') else '—'} "
          f"constraints:{len(parsed.get('!',[]))} accept:{len(parsed.get('=',[]))}")
    for w in warns: print(f"  warn:  {w}")
    for e in errs:  print(f"  ERROR: {e}")
    rc = 1 if errs else 0
    if strict:
        rej = strict_validate(text, plan_ids)
        if rej:
            _print_rejections(rej); rc = 1
        else:
            print("  strict: no deterministic plan-ops violations.")
    return parsed, errs, warns, rc

def _store_parsed(parsed):
    """Strip transient keys before persisting the parsed capsule."""
    return {k: v for k, v in parsed.items() if not k.startswith("_")}

def cmd_add(text, source):
    parsed, errs, _, _ = cmd_validate(text)
    if errs:
        print("\nREJECTED — fix the capsule while context is fresh (this is the point).")
        return 1
    # reuse the deterministic gate (structural checks; no plan => unknown-id skipped) so a
    # malformed plan-ops batch can't be queued for an unattended executor to choke on later.
    rej = strict_validate(text)
    if rej:
        _print_rejections(rej)
        print("\nREJECTED — deterministic plan-ops violation (self-dep / op-char-id / dup-id).")
        return 1
    items = load()
    if any(it["id"] == parsed["id"] and it["status"] in ("pending","in_progress") for it in items):
        print(f"\nREJECTED — id {parsed['id']!r} already queued and unfinished.")
        return 1
    items.append({"id": parsed["id"], "status": "pending", "created": now(),
                  "source": source or current_project() or "unknown", "capsule": text.strip(),
                  "parsed": _store_parsed(parsed),
                  "started": None, "done": None, "proof": None})
    save(items)
    print(f"\nQUEUED {parsed['id']!r}  ({sum(1 for i in items if i['status']=='pending')} pending)")
    return 0

def cmd_list(status):
    items = load()
    if status == "pending":
        items = [it for it in items if it["status"] == "pending"]
    elif status == "active":
        items = [it for it in items if it["status"] in ("pending","in_progress")]
    elif status != "all":
        items = [it for it in items if it["status"] == status]
    if not items:
        print("(queue empty)"); return 0
    for it in items:
        flag = ""
        if it["status"] == "in_progress" and _age_min(it.get("started")) > ORPHAN_MIN:
            flag = "  ⚠ orphan-suspect"
        print(f"  [{it['status']:<11}] {it['id']:<22} {it['parsed'].get('do','')[:50]}  "
              f"(src={it['source']}, {it['created'][:16]}){flag}")
    return 0

def current_project():
    """Current project name (basename of CLAUDE_PROJECT_DIR or cwd). None if it
    resolves to $HOME (=> treat as no project / global). The queue is global on
    disk; project scope only filters which capsules surface."""
    cand = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    name = os.path.basename(cand.rstrip("/"))
    return None if (not name or name == os.path.basename(os.path.expanduser("~"))) else name

def _scope(pend, show_all, project):
    """(proj, mine, others) — proj is None when global (show_all or undetectable)."""
    proj = None if show_all else (project or current_project())
    if not proj:
        return None, pend, []
    mine = [it for it in pend if it.get("source") == proj]
    others = [it for it in pend if it.get("source") != proj]
    return proj, mine, others

def _print_scope_cycles(items, mine_ids):
    """Print on: dependency-cycle deadlocks, but only cycles that involve an
    in-scope capsule (so a multi-project queue doesn't surface other projects')."""
    for cyc in _find_cycles(items):
        if any(n in mine_ids for n in cyc):
            print(f"  ⚠ dependency cycle (deadlock): " + " -> ".join(cyc) + f" -> {cyc[0]}")

def _emit_capsule(nxt):
    print(f"# intent capsule {nxt['id']!r}  (queued {nxt['created'][:16]} from {nxt['source']})")
    naccept = len(nxt.get("parsed", {}).get("=", []))
    hint = " ".join(f'--proof "=[{i}] met by..."' for i in range(1, naccept+1)) if naccept else '--proof "..."'
    print(f"# execute this cold, then: intent-queue done {nxt['id']} {hint}\n")
    print(nxt["capsule"])

def _strict_gate(nxt, strict, plan_ids):
    """For unattended pipelines: refuse to hand out a capsule that fails the deterministic
    validator, WITHOUT flipping its status (so it isn't burned). Returns True if blocked."""
    if not strict:
        return False
    rej = strict_validate(nxt["capsule"], plan_ids)
    if rej:
        print(f"# ✗ STRICT-BLOCKED capsule {nxt['id']!r} — not handed out, left pending:")
        _print_rejections(rej)
        return True
    return False

def cmd_next(show_all=False, project=None, strict=False, plan_ids=None):
    items = load()
    pend = [it for it in items if it["status"] == "pending"]
    proj, mine, others = _scope(pend, show_all, project)
    # 1) Serve pending work in scope first — never preempt a live queue.
    if mine:
        smap = _status_map(items)
        ready = [it for it in mine if _classify(it, smap)["ready"]]
        if ready:
            nxt = sorted(ready, key=lambda x: x["created"])[0]
            if _strict_gate(nxt, strict, plan_ids):
                return 1                                     # blocked; status untouched (not saved)
            nxt["status"] = "in_progress"; nxt["started"] = now()
            save(items)
            _emit_capsule(nxt)
            return 0
        # pending exist in scope but none are ready: report what they wait on and
        # exit WITHOUT flipping status or preempting via orphan reclaim.
        # one classify pass over the blocked set
        classified = [_classify(it, smap) for it in mine]
        waiting = sorted({d for c in classified for d in c["waiting"]})
        dead = sorted({d for c in classified for d in c["dead"]})
        msg = f"({len(mine)} pending in scope, all blocked"
        if waiting:
            msg += f" — waiting on: {', '.join(waiting)}"
        if dead:
            msg += f"; dead deps (dropped): {', '.join(dead)}"
        print(msg + ")")
        _print_scope_cycles(items, {it["id"] for it in mine})
        return 0
    # 2) No pending in scope -> auto-reclaim the oldest eligible orphan IN SCOPE, so a crashed
    #    capsule resurfaces through ordinary `next` consumption (not a manual reap step).
    #    Eligibility is purely time-based (no heartbeat exists): an in_progress capsule idle
    #    >= ORPHAN_MIN is treated as abandoned. A genuinely slow (>ORPHAN_MIN) build is
    #    indistinguishable from a crash; re-stamping `started` means the reclaiming session
    #    now owns the clock. Only fires when there's no pending work, to avoid preemption.
    in_prog = [it for it in items if it["status"] == "in_progress"]
    _, orph_mine, orph_others = _scope(in_prog, show_all, project)
    eligible = [it for it in orph_mine if _age_min(it.get("started")) >= ORPHAN_MIN]
    if eligible:
        nxt = sorted(eligible, key=lambda x: x.get("started") or "")[0]
        if _strict_gate(nxt, strict, plan_ids):
            return 1                                         # blocked; orphan left as-is
        idle = _age_min(nxt.get("started"))
        idle_s = "unknown" if idle == float("inf") else f"{int(idle)}m"
        nxt["started"] = now()   # re-stamp: this session owns the clock now
        save(items)
        print(f"# ♻ RESURFACED orphaned capsule {nxt['id']!r} (idle {idle_s} — a prior session "
              f"drained it but never finished; you now own it)")
        _emit_capsule(nxt)
        return 0
    # 3) Nothing to hand out in scope — explain precisely what remains.
    if proj and others:
        print(f"(no pending capsules for {proj}; {len(others)} pending in other projects — "
              f"`next --all` or `next --project <name>`)")
        return 0
    fresh = [it for it in orph_mine if _age_min(it.get("started")) < ORPHAN_MIN]
    if fresh:
        print(f"(no pending capsules; {len(fresh)} in_progress still fresh (<{ORPHAN_MIN}m) — "
              f"left running, not reclaimed)")
    elif proj and orph_others:
        print(f"(no pending capsules for {proj}; {len(orph_others)} orphaned in other projects — "
              f"`next --all` to reclaim)")
    else:
        print("(no pending capsules)")
    return 0

def _select(items, id_):
    """Prefer an ACTIVE (pending/in_progress) capsule for this id over a finished one."""
    active = [it for it in items if it["id"] == id_ and it["status"] in ("pending","in_progress")]
    if active:
        return active[0]
    any_ = [it for it in items if it["id"] == id_]
    return any_[0] if any_ else None

def cmd_done(id_, proofs):
    items = load()
    target = _select(items, id_)
    if not target:
        print(f"(no capsule with id {id_!r})"); return 1
    criteria = target.get("parsed", {}).get("=", [])
    clean = [(p or "").strip() for p in (proofs or [])]
    if criteria:
        # one non-blank attestation per criterion, positionally mapped to the =[i] list
        if len(clean) != len(criteria) or any(not p for p in clean):
            print(f"REFUSED — {id_!r} has {len(criteria)} acceptance criteria. `done` attests "
                  f"EACH was met: one --proof per criterion, in order. It is not a rubber-stamp.\n")
            for i, c in enumerate(criteria, 1):
                supplied = clean[i-1] if (i-1 < len(clean) and clean[i-1]) else None
                print(f"  =[{i}] {c}")
                print(f"        {'proof: ' + supplied if supplied else '[MISSING]'}")
            if len(clean) > len(criteria):
                print(f"  (got {len(clean)} proofs for {len(criteria)} criteria — extras: "
                      f"{clean[len(criteria):]})")
            example = " ".join(f'--proof "how =[{i}] was met"' for i in range(1, len(criteria)+1))
            print(f"\nRe-run with one --proof per criterion, in order:\n  intent-queue done {id_} {example}")
            return 1
        target["proof"] = [{"criterion": c, "attestation": clean[i]} for i, c in enumerate(criteria)]
    else:
        # no criteria: a free-text note is optional
        target["proof"] = " | ".join(p for p in clean if p) or None
    target["status"] = "done"; target["done"] = now()
    save(items)
    n = len(criteria)
    tail = f"  ({n}/{n} criteria attested)" if n else ("  (note recorded)" if target["proof"] else "")
    print(f"{id_} -> done{tail}")
    return 0

def cmd_drop(id_):
    items = load()
    target = _select(items, id_)
    if not target:
        print(f"(no capsule with id {id_!r})"); return 1
    target["status"] = "dropped"; target["done"] = now()
    save(items)
    print(f"{id_} -> dropped")
    return 0

def cmd_reap(older_than, yes):
    items = load()
    stale = [it for it in items if it["status"] == "in_progress"
             and _age_min(it.get("started")) >= older_than]
    if not stale:
        print(f"(no in_progress capsules older than {older_than} min)"); return 0
    print(f"{'REAPING' if yes else 'WOULD REAP'} {len(stale)} orphaned capsule(s) "
          f"(in_progress >= {older_than} min):")
    for it in stale:
        age = _age_min(it.get("started"))
        age_s = "unknown" if age == float("inf") else f"{int(age)}m"
        print(f"  {it['id']:<22} started {it.get('started') or '(never)'}  age={age_s}  src={it['source']}")
    if not yes:
        print(f"\nDry run. Re-run with --yes to flip these back to pending.")
        return 0
    for it in stale:
        it["status"] = "pending"; it["started"] = None
    save(items)
    print(f"\nResurfaced {len(stale)} -> pending.")
    return 0

def cmd_pickup(show_all=False, project=None, strict=False, plan_ids=None):
    items = load()
    pend = [it for it in items if it["status"] == "pending"]
    orphans = [it for it in items if it["status"] == "in_progress"
               and _age_min(it.get("started")) > ORPHAN_MIN]
    if not pend and not orphans:
        return 0
    proj, mine, others = _scope(pend, show_all, project)
    # orphans are scoped the same way (only surface this project's, unless global)
    if proj:
        orph_mine = [it for it in orphans if it.get("source") == proj]
    else:
        orph_mine = orphans
    scope_label = f"for {proj}" if proj else "(all projects)"
    print(f"## Intent Queue {scope_label} — {len(mine)} pending"
          + (f", {len(orph_mine)} orphaned" if orph_mine else "") + " capsule(s)\n")
    if mine:
        smap = _status_map(items)
        ready, blocked, notes = [], [], []
        for it in sorted(mine, key=lambda x: x["created"]):
            c = _classify(it, smap)
            (ready if c["ready"] else blocked).append((it, c))
            # surface unknown-dep notes only when the capsule names at least one REAL
            # queued id (it intends id-gating). Pure free-text on: prose stays silent
            # instead of emitting one noise note per word.
            if c["unknown"] and any(t in smap for t in _dep_tokens(it.get("parsed", {}).get("on", ""))):
                notes += [(it["id"], u) for u in c["unknown"]]
        if ready:
            print("Ready now:")
            for it, _c in ready:
                print(f"- **{it['id']}** — {it['parsed'].get('do','')[:70]}  "
                      f"(accept: {len(it['parsed'].get('=',[]))} criteria)")
        if ready and blocked:
            print()
        if blocked:
            print("Blocked:")
            for it, c in blocked:
                bits = []
                if c["waiting"]:
                    bits.append("waiting on " + ", ".join(c["waiting"]))
                if c["dead"]:
                    bits.append("dead deps (dropped): " + ", ".join(c["dead"]))
                print(f"- **{it['id']}** — {it['parsed'].get('do','')[:70]}  ({'; '.join(bits)})")
        for cid, u in notes:
            print(f"  note: {cid}: on: references unknown id {u!r} (non-gating)")
        _print_scope_cycles(items, {it["id"] for it in mine})
        if ready:
            print(f"\nRun `intent-queue next` to drain the oldest ready capsule.")
    elif proj:
        print(f"(none pending for {proj})")
    if orph_mine:
        ids = ", ".join(o["id"] for o in orph_mine)
        print(f"\n⚠ {len(orph_mine)} orphaned in_progress (a prior session drained but never finished): "
              f"{ids}\n  `intent-queue reap --yes` to resurface, or `intent-queue done <id>` if actually done.")
    if proj and others:
        ids = ", ".join(o["id"] for o in others)
        print(f"\n→ {len(others)} capsule(s) queued FOR OTHER PROJECTS: {ids}\n"
              f"  These will not prompt you here. Run `intent-queue pickup --all` to act on them.")
    if strict:
        bad = [(it, strict_validate(it["capsule"], plan_ids)) for it in mine]
        bad = [(it, r) for it, r in bad if r]
        if bad:
            print(f"\n⚠ STRICT — {len(bad)} pending capsule(s) fail the deterministic validator "
                  f"(a `next --strict` pipeline would refuse them):")
            for it, r in bad:
                print(f"  {it['id']}: " + "; ".join(x.reason for x in r))
        else:
            print("\n✓ strict: all pending capsules pass the deterministic validator.")
    return 0

def main():
    ap = argparse.ArgumentParser(prog="intent-queue")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add");      a.add_argument("--source"); a.add_argument("--file")
    v = sub.add_parser("validate"); v.add_argument("--file")
    v.add_argument("--strict", action="store_true"); v.add_argument("--plan")
    l = sub.add_parser("list");     l.add_argument("--status", default="active")
    n = sub.add_parser("next");   n.add_argument("--all", action="store_true"); n.add_argument("--project")
    n.add_argument("--strict", action="store_true"); n.add_argument("--plan")
    p = sub.add_parser("pickup"); p.add_argument("--all", action="store_true"); p.add_argument("--project")
    p.add_argument("--strict", action="store_true"); p.add_argument("--plan")
    d = sub.add_parser("done");  d.add_argument("id"); d.add_argument("--proof", action="append")
    x = sub.add_parser("drop");  x.add_argument("id"); x.add_argument("--yes", action="store_true")
    r = sub.add_parser("reap"); r.add_argument("--older-than", type=int, default=ORPHAN_MIN)
    r.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if args.cmd == "add":      return cmd_add(read_input(args.file), args.source)
    if args.cmd == "validate":
        if args.strict:
            return cmd_validate(read_input(args.file), True, load_plan(args.plan))[3]
        cmd_validate(read_input(args.file)); return 0
    if args.cmd == "list":     return cmd_list(args.status)
    if args.cmd == "next":     return cmd_next(args.all, args.project, args.strict, load_plan(args.plan))
    if args.cmd == "pickup":   return cmd_pickup(args.all, args.project, args.strict, load_plan(args.plan))
    if args.cmd == "done":     return cmd_done(args.id, args.proof)
    if args.cmd == "reap":     return cmd_reap(args.older_than, args.yes)
    if args.cmd == "drop":
        if not args.yes:
            print(f"REFUSED — dropping {args.id!r} discards captured intent. If you don't recognize "
                  f"this capsule, read the project docs (CONCEPT.md / RESULTS.md) instead of "
                  f"dropping it. Re-run with --yes only if you're certain.")
            return 1
        return cmd_drop(args.id)

if __name__ == "__main__":
    sys.exit(main())
