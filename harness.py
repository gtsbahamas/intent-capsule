#!/usr/bin/env python3
"""
Extrapolatable fidelity test for the cached intent-convention. v1 vs v2 grammar.

Back-translation oracle: ground truth is a randomly generated mutation that exists
BEFORE the model runs. Render it -> convention line AND -> English, send both through
the model, compare output to the original mutation. Paired arms (McNemar). Wilson CIs.
k runs/case for flake. Adversarial bucket for loud-fail. Real ids + collision-prone
notes from plan.json.

Grammar:
  v1 — batches joined by ' ; ', notes bare (`:note`). Has 2 known bugs.
  v2 — batches NEWLINE-separated (no ';'), notes QUOTED+last (`:"note"`), and +new
       ids are exempt from the unknown-id guard.

--save-dataset / --load-dataset pin the EXACT mutations+english across runs so the
v1->v2 comparison isolates the grammar change (English arm becomes literally identical).
"""
import os, json, random, math, time, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=120)
ap.add_argument("--k", type=int, default=3)
ap.add_argument("--workers", type=int, default=10)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--grammar", choices=["v1","v2","v3"], default="v1")
ap.add_argument("--save-dataset", default=None)
ap.add_argument("--load-dataset", default=None)
ap.add_argument("--tag", default=None, help="label for output files")
args = ap.parse_args()
random.seed(args.seed)
TAG = args.tag or args.grammar
OUT = os.environ.get("INTENT_OUT", os.path.dirname(os.path.abspath(__file__)))

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
def pick_model(c):
    for m in c:
        try:
            client.messages.count_tokens(model=m, messages=[{"role":"user","content":"x"}]); return m
        except Exception: continue
    raise RuntimeError("no model")
EXEC_MODEL = pick_model(["claude-opus-4-8","claude-opus-4-20250514"])
PARA_MODEL = pick_model(["claude-haiku-4-5-20251001","claude-3-5-haiku-20241022"])
print(f"grammar={args.grammar}  executor={EXEC_MODEL}  paraphraser={PARA_MODEL}\n")

# ---------- legends ----------
LEGEND_V1 = """INTENT GRAMMAR — one intent per line:
  OP id [deps] [:note] [@owner] [#status]
OP:  +new  ~edit  v done  x drop  >prefer  !must  ?ask
deps: <a,b = blockedBy a,b   >a,b = blocks a,b
status: pend | wip | done | block
owner: m=model  u=user
A bare id refers to an existing node. Omit unchanged fields."""

LEGEND_V2 = """INTENT GRAMMAR — one intent PER LINE (newline-separated; ';' is NOT special):
  OP id [deps] [@owner] [#status] [:"note"]
OP:  +new  ~edit  v done  x drop  >prefer  !must  ?ask
deps: <a,b = blockedBy a,b   >a,b = blocks a,b
status: pend | wip | done | block
owner: m=model  u=user
note: ALWAYS quoted and LAST. Text between the quotes is verbatim and MAY contain ; @ < > #
ids: a bare id refers to an EXISTING node. For +new the id is NEW — never an error.
Omit unchanged fields."""

# Plan context for the test. Defaults to the shipped synthetic example_plan.json;
# point PLAN_PATH at your own plan.json (same shape: {"nodes":[{"id": ...}, ...]}) to
# run the fidelity test against your real node ids.
_PLAN_PATH = os.environ.get("PLAN_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_plan.json"))
with open(_PLAN_PATH) as f:
    PLAN = json.load(f)
EXISTING_IDS = [n["id"] for n in PLAN["nodes"]]
NAMED_IDS = [i for i in EXISTING_IDS if not i.startswith("task-")] or EXISTING_IDS[:6]
_task_ids = [i for i in EXISTING_IDS if i.startswith("task-")]
_task_hint = f", ... ({_task_ids[0]}..{_task_ids[-1]})" if _task_ids else ""
PLAN_CTX = "Current plan node ids: " + ", ".join(EXISTING_IDS[:12]) + _task_hint

SYS_TAIL_V1 = (
  "\n\nYou are a plan mutation engine. Read each intent line and output ONLY a JSON array "
  "of operations. Each op: {\"op\":\"new|edit|done|drop|query\",\"id\":\"...\", plus changed "
  "fields: \"note\",\"owner\",\"status\",\"blockedBy\":[],\"blocks\":[]}. Multiple ops "
  "separated by ';'. If an intent line is malformed, references an unknown id, or is missing "
  "a required id, output [{\"op\":\"error\",\"reason\":\"...\"}] instead of guessing. JSON only.")

SYS_TAIL_V2 = (
  "\n\nYou are a plan mutation engine. Each LINE is one operation (split on newlines, NOT on "
  "';'). Output ONLY a JSON array of operations. Each op: {\"op\":\"new|edit|done|drop|query\","
  "\"id\":\"...\", plus changed fields: \"note\",\"owner\",\"status\",\"blockedBy\":[],"
  "\"blocks\":[]}. A quoted :\"...\" note is verbatim — copy everything between the quotes "
  "exactly, including any ; @ < > # characters. RULES: op 'new' takes a NEW id — never emit an "
  "unknown-id error for 'new'. Only edit/done/drop/query require an existing id. If a line is "
  "truly malformed or an edit/done/drop/query targets an unknown id, output "
  "[{\"op\":\"error\",\"reason\":\"...\"}] instead of guessing. JSON only.")

# v3 = v2 grammar but the drop op is 'rm' (single-letter 'x' was mis-grounded as 'done')
LEGEND_V3 = LEGEND_V2.replace("v done  x drop", "v done  rm drop")
LEGEND = {"v1":LEGEND_V1,"v2":LEGEND_V2,"v3":LEGEND_V3}[args.grammar]
SYSTEM = LEGEND + "\n\n" + PLAN_CTX + (SYS_TAIL_V1 if args.grammar=="v1" else SYS_TAIL_V2)

# ---------- generator (seed-deterministic) ----------
# Note pool for generated mutations. Several notes deliberately contain the
# delimiter characters (; @ < > #) — verbatim preservation THROUGH those
# delimiters is exactly what the v2 "quoted note" grammar fix is tested against.
NOTE_POOL = ["short essay from the spec","daily poll of the changelog","mirror the monitor pattern",
    "two short emails, brief attached","TUI editor with j/k nav","hook serializes state on write",
    "poll changelog; mirror monitor","ping @lead when done","blocks > everything downstream",
    "ratio < 0.5 target","v0 read-only"]
COLLISION_NOTES = {"poll changelog; mirror monitor","ping @lead when done",
                   "blocks > everything downstream","ratio < 0.5 target"}
OPS_W = ["done"]*3+["edit"]*3+["new"]*3+["drop"]*2+["query"]*2

def rand_fields():
    f={}
    if random.random()<0.7: f["note"]=random.choice(NOTE_POOL)
    if random.random()<0.4: f["owner"]=random.choice(["m","u"])
    if random.random()<0.4: f["status"]=random.choice(["pend","wip","done","block"])
    if random.random()<0.45: f["blockedBy"]=random.sample(NAMED_IDS, random.randint(1,2))
    if random.random()<0.3: f["blocks"]=random.sample(NAMED_IDS,1)
    return f
def gen_single():
    op=random.choice(OPS_W)
    if op in ("done","drop","query"): return {"op":op,"id":random.choice(NAMED_IDS)}
    if op=="edit":
        m={"op":"edit","id":random.choice(NAMED_IDS)}; m.update(rand_fields())
        if len(m)==2: m["status"]=random.choice(["pend","wip","done","block"])
        return m
    # new-id prefix must NOT start with an op char (+ ~ v x > ! ?); real ids are kebab words.
    m={"op":"new","id":f"n-{random.randint(100,999)}"}; m.update(rand_fields()); return m
def gen_mutation():
    if random.random()<0.18: return [gen_single() for _ in range(random.randint(2,3))]
    return [gen_single()]

# ---------- renderers (grammar-aware) ----------
def render_conv_op(m, g):
    op=m["op"]; i=m["id"]
    if op=="done": return f"v {i}"
    if op=="drop": return (f"rm {i}" if g=="v3" else f"x {i}")
    if op=="query": return f"?{i}"
    parts=[("+" if op=="new" else "~")+i]
    if m.get("blockedBy"): parts.append("<"+",".join(m["blockedBy"]))
    if m.get("blocks"):    parts.append(">"+",".join(m["blocks"]))
    if g=="v1":
        if m.get("note"):   parts.append(":"+m["note"])
        if m.get("owner"):  parts.append("@"+m["owner"])
        if m.get("status"): parts.append("#"+m["status"])
    else:  # v2: owner, status, then QUOTED note last
        if m.get("owner"):  parts.append("@"+m["owner"])
        if m.get("status"): parts.append("#"+m["status"])
        if m.get("note"):   parts.append(':"'+m["note"]+'"')
    return " ".join(parts)
def render_conv(mut, g):
    sep = " ; " if g=="v1" else "\n"
    return sep.join(render_conv_op(o,g) for o in mut)

def canon_english_op(m):
    op=m["op"]; i=m["id"]
    if op=="done": return f"mark {i} as done"
    if op=="drop": return f"drop {i}"
    if op=="query": return f"what's the status of {i}"
    bits=[f"create a new node with id {i}"] if op=="new" else [f"update {i}"]
    if m.get("blockedBy"): bits.append("blocked by "+" and ".join(m["blockedBy"]))
    if m.get("blocks"):    bits.append("which blocks "+" and ".join(m["blocks"]))
    if m.get("note"):      bits.append(f'with the note "{m["note"]}"')
    if m.get("owner"):     bits.append("owned by the "+("model" if m["owner"]=="m" else "user"))
    if m.get("status"):    bits.append("status "+m["status"])
    return ", ".join(bits)
def canon_english(mut): return "; ".join(canon_english_op(o) for o in mut)

def paraphrase(text):
    p=(f'Rewrite this as ONE natural instruction a person would type. Keep every id, status '
       f'word, owner, and any quoted note EXACTLY (verbatim). Do not add or drop facts. Output '
       f'only the sentence.\n\n{text}')
    for a in range(3):
        try:
            r=client.messages.create(model=PARA_MODEL,max_tokens=200,temperature=0.8,
                messages=[{"role":"user","content":p}]); return r.content[0].text.strip()
        except Exception: time.sleep(1.5*(a+1))
    return text

def execute(line):  # Opus 4.8 deprecated temperature; native sampling.
    t=""
    for a in range(3):
        try:
            r=client.messages.create(model=EXEC_MODEL,max_tokens=500,system=SYSTEM,
                messages=[{"role":"user","content":line}])
            t=r.content[0].text.strip()
            if t.startswith("```"):
                t=t.split("```")[1]; t=t[4:].strip() if t.lower().startswith("json") else t.strip()
            return json.loads(t)
        except json.JSONDecodeError: return [{"op":"PARSE_FAIL","raw":t[:120]}]
        except Exception: time.sleep(1.5*(a+1))
    return [{"op":"API_FAIL"}]

# ---------- grader ----------
OWN={"m":"m","model":"m","u":"u","user":"u"}
STAT={"pend":"pend","pending":"pend","wip":"wip","in progress":"wip","in_progress":"wip",
      "done":"done","completed":"done","complete":"done","block":"block","blocked":"block"}
def no(x): return OWN.get(str(x).lower().strip(),str(x).lower().strip()) if x else None
def ns(x): return STAT.get(str(x).lower().strip(),str(x).lower().strip()) if x else None
def op_eq(t,g):
    if not isinstance(g,dict): return False
    if g.get("op")!=t["op"] or g.get("id")!=t["id"]: return False
    if t["op"] in ("new","edit"):
        if "owner" in t and no(g.get("owner"))!=no(t["owner"]): return False
        if "status" in t and ns(g.get("status"))!=ns(t["status"]): return False
        if set(t.get("blockedBy",[]))!=set(g.get("blockedBy",[]) or []): return False
        if set(t.get("blocks",[]))!=set(g.get("blocks",[]) or []): return False
    return True
def mut_eq(t,g):
    if not isinstance(g,list) or len(g)!=len(t): return False
    gi={(o.get("id"),o.get("op")):o for o in g if isinstance(o,dict)}
    return all((gi.get((x["id"],x["op"])) is not None and op_eq(x,gi[(x["id"],x["op"])])) for x in t)
def note_exact(t,g):
    tn=[(x["id"],x.get("note")) for x in t if x.get("note")]
    if not tn: return None
    gi={o.get("id"):o for o in g if isinstance(o,dict)}
    return all(gi.get(i) and str(gi[i].get("note","")).strip()==n.strip() for i,n in tn)
def categorize(t,out):
    has_coll=any(o.get("note") in COLLISION_NOTES for o in t)
    if has_coll: return "collision"
    is_err=isinstance(out,list) and any(isinstance(o,dict) and o.get("op") in ("error","PARSE_FAIL","API_FAIL") for o in out)
    if is_err and any(o["op"]=="new" for o in t): return "new_id_guard"
    if is_err: return "other_refusal"
    return "genuine_misparse"

ADVERSARIAL=["v","~","v nonexistent-xyz","+ :note with no id","~dark-mode #frozen","qqq dark-mode",
    "?","+dup <dup","~dark-mode >","v task-7 task-8",":just a note","#wip","+x-1 <ghost-99","x",
    "~search-index @z","+ ; ; ;"]
def loud(g): return isinstance(g,list) and len(g)>=1 and isinstance(g[0],dict) and g[0].get("op") in ("error","PARSE_FAIL")

def wilson(k,n,z=1.96):
    if n==0: return (0,0,0)
    p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return (p,max(0,c-h),min(1,c+h))
def mcnemar(pairs):
    b=sum(1 for e,c in pairs if e and not c); cc=sum(1 for e,c in pairs if c and not e); n=b+cc
    if n==0: return b,cc,1.0
    p=sum(math.comb(n,i) for i in range(0,min(b,cc)+1))*2/(2**n)
    return b,cc,min(1.0,p)

# ---------- dataset ----------
if args.load_dataset:
    ds=json.load(open(args.load_dataset)); MUTS=ds["muts"]; ENG=ds["eng"]
    print(f"loaded dataset: {len(MUTS)} mutations + english from {args.load_dataset}")
else:
    print(f"generating {args.n} mutations + paraphrasing english...")
    MUTS=[gen_mutation() for _ in range(args.n)]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        ENG=list(ex.map(lambda m: paraphrase(canon_english(m)), MUTS))
    if args.save_dataset:
        json.dump({"muts":MUTS,"eng":ENG,"seed":args.seed}, open(args.save_dataset,"w"))
        print(f"saved dataset -> {args.save_dataset}")
N=len(MUTS)
CONV=[render_conv(m,args.grammar) for m in MUTS]

# ---------- run ----------
jobs=[]
for idx in range(N):
    for run in range(args.k):
        jobs.append((idx,"conv",run,CONV[idx])); jobs.append((idx,"eng",run,ENG[idx]))
for j,a in enumerate(ADVERSARIAL): jobs.append((f"adv{j}","adv",0,a))
print(f"running {len(jobs)} executor calls...")
res={}; done=0
with ThreadPoolExecutor(max_workers=args.workers) as ex:
    futs=[ex.submit(lambda jb:(jb,execute(jb[3])), j) for j in jobs]
    for fu in as_completed(futs):
        (idx,arm,run,line),got=fu.result(); res[(idx,arm,run)]=got; done+=1
        if done%150==0: print(f"  {done}/{len(jobs)}")

# ---------- score ----------
def case(idx,arm):
    oks=[mut_eq(MUTS[idx],res[(idx,arm,run)]) for run in range(args.k)]
    return all(oks), len(set(oks))>1
conv_pass=[];eng_pass=[];fc=fe=0;noteok=notetot=0;cfail=ctot=0;pairs=[];fails=[];buckets={}
for idx in range(N):
    cp,cf=case(idx,"conv"); ep,ef=case(idx,"eng")
    conv_pass.append(cp); eng_pass.append(ep); pairs.append((ep,cp)); fc+=cf; fe+=ef
    g0=res[(idx,"conv",0)]; nz=note_exact(MUTS[idx],g0)
    if nz is not None: notetot+=1; noteok+=int(nz)
    if any(o.get("note") in COLLISION_NOTES for o in MUTS[idx]): ctot+=1; cfail+=int(not cp)
    if not cp:
        cat=categorize(MUTS[idx],g0); buckets[cat]=buckets.get(cat,0)+1
        fails.append({"truth":MUTS[idx],"line":CONV[idx],"out":g0,"cat":cat})
loud_n=sum(1 for j in range(len(ADVERSARIAL)) if loud(res[(f"adv{j}","adv",0)]))

cp_p,cl,ch=wilson(sum(conv_pass),N); ep_p,el,eh=wilson(sum(eng_pass),N); b,cc,pv=mcnemar(pairs)
R=["="*64,f"  INTENT-CONVENTION FIDELITY — grammar {args.grammar.upper()}","="*64,
   f"executor={EXEC_MODEL}  paraphraser={PARA_MODEL}",
   f"n={N}  k={args.k}  temp=NATIVE  seed={args.seed}","",
   "STRUCTURAL ACCURACY (all-k correct; machine-critical fields):",
   f"  convention : {sum(conv_pass):>3}/{N} = {cp_p:6.1%}   95% CI [{cl:.1%}, {ch:.1%}]",
   f"  english    : {sum(eng_pass):>3}/{N} = {ep_p:6.1%}   95% CI [{el:.1%}, {eh:.1%}]",
   f"  DELTA (eng-conv) = {ep_p-cp_p:+.1%}","",
   f"PAIRED McNemar: eng-right/conv-wrong={b}  conv-right/eng-wrong={cc}  p={pv:.3f} "
   f"({'NS' if pv>=.05 else 'SIGNIFICANT'})","",
   f"FLAKE: convention {fc}/{N}={fc/N:.1%}   english {fe}/{N}={fe/N:.1%}","",
   f"NOTE VERBATIM (conv): {noteok}/{notetot}={ (noteok/notetot if notetot else 0):.1%}","",
   f"COLLISION-NOTE cases failed: {cfail}/{ctot}={ (cfail/ctot if ctot else 0):.1%}","",
   f"CONVENTION FAILURE BREAKDOWN: {json.dumps(buckets)}","",
   f"ADVERSARIAL loud-fail: {loud_n}/{len(ADVERSARIAL)}={loud_n/len(ADVERSARIAL):.1%}","="*64]
report="\n".join(R); print("\n"+report)
open(f"{OUT}/report_{TAG}.txt","w").write(report+"\n")
json.dump({"grammar":args.grammar,"conv_acc":cp_p,"eng_acc":ep_p,"delta":ep_p-cp_p,
    "conv_pass":conv_pass,"eng_pass":eng_pass,"flaky_conv":fc,"flaky_eng":fe,
    "note_ok":noteok,"note_tot":notetot,"collision_fail":cfail,"collision_tot":ctot,
    "buckets":buckets,"loud":loud_n,"adv_total":len(ADVERSARIAL),
    "all_conv_failures":fails}, open(f"{OUT}/results_{TAG}.json","w"), indent=2, default=str)
print(f"\nartifacts: report_{TAG}.txt  results_{TAG}.json")
