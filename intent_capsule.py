#!/usr/bin/env python3
"""
NAIL INTENT: can the convention carry IMPLEMENTATION intent through a cold replay
as faithfully as rich prose — at fewer tokens?

Mirrors the real workflow:
  btw-at-peak-context  = author a detailed REFERENCE spec (Opus, full plan context)
  encode               = compress that spec two ways: (a) v-intent CONVENTION, (b) terse PROSE
                         (equal-ish token budget, else prose just = full spec and wins trivially)
  cold replay          = a FRESH/cold model reconstructs the implementation spec from each capsule
  judge                = score each reconstruction vs the reference (rubric, 5 dims, /10)

Headline = does CONVENTION match PROSE fidelity, and at what token cost.
"""
import os, json, time, statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
def pick(c):
    for m in c:
        try: client.messages.count_tokens(model=m,messages=[{"role":"user","content":"x"}]); return m
        except Exception: continue
EXEC = pick(["claude-opus-4-8","claude-opus-4-20250514"])
JUDGE = EXEC
print(f"author/encode/replay/judge model: {EXEC}\n")

def call(system, user, max_tokens=900):
    for a in range(4):
        try:
            kw=dict(model=EXEC,max_tokens=max_tokens,messages=[{"role":"user","content":user}])
            if system: kw["system"]=system
            r=client.messages.create(**kw); return r.content[0].text.strip()
        except Exception: time.sleep(1.5*(a+1))
    return ""
def toks(text):
    try: return client.messages.count_tokens(model=EXEC,messages=[{"role":"user","content":text}]).input_tokens-8
    except Exception: return len(text)//4

# ---- the EXTENDED intent grammar (v-intent) ----
LEGEND = """INTENT CAPSULE GRAMMAR — line-based, one capsule. tag then value; omit unused.
@<id>          target slug
do: <one-line imperative — the thing to build>
in: <files / components / layer it touches>
on: <ids or features it depends on / extends>
!: <hard constraint — must hold>           (repeatable, one rule per !)
~: <soft preference / fallback>            (repeatable)
?: <gate — when it applies or stays hidden>
=: <acceptance — observable proof it works>(repeatable)
why: <the nuance: the reason that changes HOW it's built>
Values are verbatim free text and may contain any character."""

# ---- 12 generic implementation intents (title + one-line brief) ----
SEEDS = [
 ("command-palette","cmd-k command palette that fuzzy-searches actions, shown only after the workspace finishes loading"),
 ("onboarding-tour","first-run guided tour, but gate it so it never fires for a returning user or on a low-bandwidth connection"),
 ("changelog-watch","daily watcher that polls a dependency's release feed for breaking changes and notifies, mirroring a cron-monitor pattern"),
 ("state-sync-hook","post-write hook that serializes editor state into a sidecar file so a live preview pane stays in sync"),
 ("editable-tree","editable TUI tree pane with j/k navigation, d to collapse a node, f to fork a branch"),
 ("account-delete","delete-account endpoint, OTP-gated, that soft-deletes and emits a metric"),
 ("tax-note","show a 'tax included, no fees' note on the cart subtotal for whole-dollar pricing locales"),
 ("pw-reset","password reset via emailed 6-digit OTP, same-tab flow, per-IP rate limited, no account-existence leak"),
 ("csv-export","export the currently-filtered data table to CSV, preserving the active filters and column order"),
 ("rate-limit","per-IP rate-limit middleware on an API route, sliding window, returns 429 with retry-after"),
 ("dark-mode","dark-mode toggle persisted to localStorage, respects prefers-color-scheme on first load"),
 ("file-upload","drag-and-drop file upload with progress bar, client-side size+type validation, graceful failure"),
]

AUTHOR_SYS = ("You are the engineer with FULL fresh context on this project. Write a tight but COMPLETE "
  "implementation spec for the feature. Cover: WHAT to build, WHERE (files/layer), hard CONSTRAINTS, "
  "soft PREFERENCES, any GATE/condition, ACCEPTANCE criteria, and the one NUANCE that changes how it's "
  "built. Be specific and decision-bearing. 150-220 words.")

def author_reference(title, brief):
    return call(AUTHOR_SYS, f"Feature: {title}\nBrief: {brief}", 700)

# EQUAL budget on both arms (was biased: prose was capped, convention wasn't). Fair per-token test.
BUDGET = "at most 80 words"
ENC_CONV_SYS = (LEGEND + f"\n\nCompress the spec below into ONE intent capsule using the grammar above, "
  f"{BUDGET}. Preserve every constraint, gate, acceptance item, and the nuance. Output ONLY the capsule.")
ENC_PROSE_SYS = (f"Compress the spec below into a TERSE prose capsule, {BUDGET}. Preserve every constraint, "
  f"gate, acceptance item, and the nuance. Output ONLY the capsule.")

def encode_conv(ref):  return call(ENC_CONV_SYS, ref, 500)
def encode_prose(ref): return call(ENC_PROSE_SYS, ref, 400)

REPLAY_CONV_SYS = (LEGEND + "\n\nYou are a fresh engineer with NO prior context. Read this intent capsule "
  "and reconstruct the FULL implementation spec it encodes: what to build, where, constraints, gate, "
  "acceptance, and the nuance. Write it out as you would brief yourself before coding. 150-220 words.")
REPLAY_PROSE_SYS = ("You are a fresh engineer with NO prior context. Read this capsule and reconstruct the "
  "FULL implementation spec it encodes: what to build, where, constraints, gate, acceptance, and the "
  "nuance. Write it out as you would brief yourself before coding. 150-220 words.")

def replay(capsule, kind):
    return call(REPLAY_CONV_SYS if kind=="conv" else REPLAY_PROSE_SYS, capsule, 700)

JUDGE_SYS = ("You grade how faithfully a RECONSTRUCTION preserved an engineer's original intent. Score 5 "
  "dimensions 0-2 each (0=lost,1=partial,2=intact): WHAT (the feature), WHERE (files/layer), CONSTRAINTS "
  "(hard rules), ACCEPTANCE (proof-of-done), NUANCE (the reason that changes HOW). Output ONLY JSON: "
  '{"what":n,"where":n,"constraints":n,"acceptance":n,"nuance":n}. Grade against the REFERENCE only.')

def judge(ref, recon):
    t=call(JUDGE_SYS, f"REFERENCE:\n{ref}\n\nRECONSTRUCTION:\n{recon}", 200)
    try:
        if t.startswith("```"): t=t.split("```")[1]; t=t[4:] if t.lower().startswith("json") else t
        d=json.loads(t); return d, sum(d.values())
    except Exception: return {"raw":t[:80]}, None

def process(seed):
    sid,(title,brief)=seed[0],(seed[0],seed[1])
    ref=author_reference(seed[0],seed[1])
    cap_c, cap_p = encode_conv(ref), encode_prose(ref)
    tc, tp = toks(cap_c), toks(cap_p)
    rec_c, rec_p = replay(cap_c,"conv"), replay(cap_p,"prose")
    jc, sc = judge(ref, rec_c)
    jp, sp = judge(ref, rec_p)
    return {"id":seed[0],"ref":ref,"cap_conv":cap_c,"cap_prose":cap_p,"tok_conv":tc,"tok_prose":tp,
            "score_conv":sc,"score_prose":sp,"dims_conv":jc,"dims_prose":jp,
            "recon_conv":rec_c,"recon_prose":rec_p}

print(f"processing {len(SEEDS)} implementation intents (author->encode->cold-replay->judge)...")
rows=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs=[ex.submit(process,s) for s in SEEDS]
    for fu in as_completed(futs):
        r=fu.result(); rows.append(r); print(f"  done: {r['id']:<20} conv={r['score_conv']}/10 prose={r['score_prose']}/10")

ok=[r for r in rows if r["score_conv"] is not None and r["score_prose"] is not None]
sc=[r["score_conv"] for r in ok]; sp=[r["score_prose"] for r in ok]
tcv=[r["tok_conv"] for r in ok]; tpv=[r["tok_prose"] for r in ok]
conv_wins=sum(1 for r in ok if r["score_conv"]>r["score_prose"])
prose_wins=sum(1 for r in ok if r["score_prose"]>r["score_conv"])
ties=sum(1 for r in ok if r["score_conv"]==r["score_prose"])

R=["="*60,"  NAIL INTENT — convention vs prose, cold-replay fidelity","="*60,
   f"model={EXEC}   n={len(ok)} implementation intents","",
   f"MEAN FIDELITY (/10):  convention {statistics.mean(sc):.2f}   prose {statistics.mean(sp):.2f}   "
   f"delta {statistics.mean(sc)-statistics.mean(sp):+.2f}",
   f"MEDIAN:               convention {statistics.median(sc):.1f}   prose {statistics.median(sp):.1f}",
   f"HEAD-TO-HEAD:         conv wins {conv_wins}   prose wins {prose_wins}   ties {ties}","",
   f"CAPSULE TOKENS (mean): convention {statistics.mean(tcv):.0f}   prose {statistics.mean(tpv):.0f}   "
   f"(conv uses {statistics.mean(tcv)/statistics.mean(tpv):.0%} of prose tokens)",
   f"FIDELITY PER TOKEN:    convention {statistics.mean(sc)/statistics.mean(tcv)*100:.2f}   "
   f"prose {statistics.mean(sp)/statistics.mean(tpv)*100:.2f}  (score per 100 capsule tokens)","",
   "PER-INTENT (score conv/prose, tokens conv/prose):"]
for r in sorted(ok,key=lambda x:x["id"]):
    R.append(f"  {r['id']:<20} {r['score_conv']:>2}/{r['score_prose']:<2}  tok {r['tok_conv']:>3}/{r['tok_prose']:<3}")
# dimension-level: where does each lose?
def dimavg(rows,arm,dim):
    vs=[r[f'dims_{arm}'].get(dim) for r in rows if isinstance(r[f'dims_{arm}'],dict) and dim in r[f'dims_{arm}']]
    return statistics.mean(vs) if vs else 0
R.append("")
R.append("DIMENSION MEANS (/2)  what  where  constr  accept  nuance")
R.append(f"  convention          {dimavg(ok,'conv','what'):.2f}  {dimavg(ok,'conv','where'):.2f}   "
         f"{dimavg(ok,'conv','constraints'):.2f}    {dimavg(ok,'conv','acceptance'):.2f}    {dimavg(ok,'conv','nuance'):.2f}")
R.append(f"  prose               {dimavg(ok,'prose','what'):.2f}  {dimavg(ok,'prose','where'):.2f}   "
         f"{dimavg(ok,'prose','constraints'):.2f}    {dimavg(ok,'prose','acceptance'):.2f}    {dimavg(ok,'prose','nuance'):.2f}")
R.append("="*60)
report="\n".join(R); print("\n"+report)
out=os.environ.get("INTENT_OUT", os.path.dirname(os.path.abspath(__file__)))
open(out+"/report_intent.txt","w").write(report+"\n")
json.dump(rows,open(out+"/results_intent.json","w"),indent=2,default=str)
print(f"\nartifacts: report_intent.txt  results_intent.json")
