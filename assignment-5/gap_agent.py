#!/usr/bin/env python3
"""gap_agent.py - goal-oriented coding agent for a Unity game (ELVTR assignment 5).

Goal: close the most valuable gap between the game design document and the code.

  1. extract   read docs/gdd/*.md and list the features the design requires        (claude -p, no tools)
  2. scan      index Assets/Scripts and decide which features exist                (grep, then a claude -p judge)
  3. gaps      list the missing features
  4. rank      priority_score() for every gap; print the scores
  5. write     write the top-ranked feature into the game                          (claude -p with Read/Grep/Glob/Edit/Write)
  6. iterate   re-scan after each write; stop when the feature's requirements are met or after --max-tries

Standard library only. Needs the `claude` CLI logged in; no API key.

  python3 gap_agent.py --game ~/Projects/ELVTR-wt/A5-gap-agent                 # full run
  python3 gap_agent.py --game <repo> --plan-only                               # steps 1-4, writes nothing into the game
  python3 gap_agent.py --game <repo> --verify-cmd "scripts/unity_cli.sh test --platform edit"
"""
import argparse, concurrent.futures as cf, datetime, hashlib, json, os, re, subprocess, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_VERSION = "3"
SKIP_DOCS = {"00-README.md": "index of the other files", "11-production-crew.md": "how the team works, no game features",
             "17-lore.md": "story bible: names and text, no code features"}
ALLOWED_WRITE = ("Assets/Scripts/", "Assets/Tests/")          # inside the Unity project folder
WEIGHTS = {"impact": 0.40, "deps": 0.25, "small": 0.20, "low_risk": 0.15}
SMALL = {"S": 1.0, "M": 0.5, "L": 0.1}
LOW_RISK = {"low": 1.0, "medium": 0.5, "high": 0.1}


# ----------------------------------------------------------------------------------------------- claude -p
def claude(prompt, model, system=None, tools=None, cwd=HERE, timeout=1500):
    """One headless call. tools=None: the model sees only the prompt. tools=[...]: it may use those tools in cwd."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--strict-mcp-config"]
    if system: cmd += ["--system-prompt" if tools is None else "--append-system-prompt", system]
    cmd += ["--tools", ""] if tools is None else ["--permission-mode", "acceptEdits", "--allowedTools", *tools]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if r.returncode != 0: raise RuntimeError("claude -p failed (%d): %s" % (r.returncode, (r.stderr or r.stdout)[:400]))
    env = json.loads(r.stdout)
    if env.get("is_error"): raise RuntimeError("claude -p error: %s" % str(env.get("result"))[:400])
    return env.get("result", ""), float(env.get("total_cost_usd") or 0)

def parse_json(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try: return json.loads(t[i:j + 1])
            except ValueError: pass
    raise ValueError("no JSON in the reply: " + text[:200])

def ask_json(prompt, model, system, tries=2):
    err = None
    for _ in range(tries):
        try:
            out, cost = claude(prompt, model, system); return parse_json(out), cost
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e: err = e
    raise RuntimeError("no usable reply: %s" % err)


# ----------------------------------------------------------------------------------------------- 1. extract
EXTRACT_SYS = "You read one file of a game design document and list the features it requires. You reply with JSON only."
EXTRACT = """Below is one file of the design document of a Unity tactics game. List the gameplay, UI and feedback FEATURES it requires
that need game code (C#). Skip art assets, story text, team process and pure numbers tables. At most {n} features, the most concrete first.

Reply with a JSON array. Each item:
  "name"        short name, 2-6 words
  "summary"     one sentence: what the player sees or what the game does
  "quote"       the sentence from the file that requires it, verbatim, at most 240 characters
  "section"     the heading it sits under
  "code_terms"  4-6 words or identifiers a C# implementation would almost certainly contain (class names, method stems, distinctive nouns)
  "loop_impact" 1-5: how much the core playable loop (set up, defend, enemy attacks, win or lose) is worse without it; 5 = cannot play
  "size"        "S" (one new file, under about 150 lines, a few lines of hook-up), "M" (several files) or "L" (a new system)
  "risk"        "low" (additive, cannot break existing behaviour), "medium" or "high" (changes combat, movement or AI results)
  "depends_on"  the other game systems it needs, as short names (for example "squad selection", "wave spawner")
  "doc_status"  "built", "not_built" or "unknown": what the file itself says about whether it exists

FILE {name}:
{text}"""

def extract_features(gdd_dir, model, cache_dir, per_file, log):
    files = sorted(f for f in os.listdir(gdd_dir) if f.endswith(".md") and f not in SKIP_DOCS)
    for f, why in SKIP_DOCS.items(): log("  skip %-26s %s" % (f, why))
    def one(f):
        text = open(os.path.join(gdd_dir, f), encoding="utf-8").read()
        key = hashlib.sha1((PROMPT_VERSION + model + str(per_file) + text).encode()).hexdigest()[:16]
        cp = os.path.join(cache_dir, "extract-%s-%s.json" % (f[:-3], key))
        if os.path.exists(cp): return f, json.load(open(cp)), 0.0, True
        items, cost = ask_json(EXTRACT.format(n=per_file, name=f, text=text[:60000]), model, EXTRACT_SYS)
        items = [i for i in items if isinstance(i, dict) and i.get("name")]
        json.dump(items, open(cp, "w"), indent=1, ensure_ascii=False); return f, items, cost, False
    feats, cost = [], 0.0
    with cf.ThreadPoolExecutor(4) as ex:
        for f, items, c, cached in ex.map(one, files):
            cost += c; log("  %-26s %2d features%s" % (f, len(items), "  (cached)" if cached else ""))
            for k, it in enumerate(items):
                it["id"] = "%s-%02d" % (f.split("-")[0], k + 1); it["gdd_file"] = f; feats.append(it)
    return feats, cost


# ----------------------------------------------------------------------------------------------- 2. scan
def index_code(scripts_dir):
    """file -> {text, classes, methods}. Plain regex, no compiler."""
    idx = {}
    for root, _, names in os.walk(scripts_dir):
        for n in names:
            if not n.endswith(".cs"): continue
            p = os.path.join(root, n); text = open(p, encoding="utf-8", errors="replace").read()
            idx[os.path.relpath(p, scripts_dir)] = {
                "text": text, "lines": text.count("\n") + 1,
                "classes": re.findall(r"\b(?:class|struct|enum|interface)\s+([A-Z]\w+)", text),
                "methods": sorted(set(re.findall(r"\b(?:public|internal)\s+(?:static\s+)?[\w<>\[\],\.]+\s+([A-Z]\w+)\s*\(", text)))}
    return idx

def squash(s): return re.sub(r"[^a-z0-9]", "", s.lower())

def grep_feature(feat, idx, squashed):
    """Deterministic pass: which of the feature's code terms occur anywhere in the scripts, and where."""
    hits, where = 0, []
    for term in feat.get("code_terms") or []:
        t = squash(term)
        if len(t) < 4: continue
        files = [f for f, s in squashed.items() if t in s]
        if files:
            hits += 1; f0 = min(files, key=lambda f: 0 if t in squash(f) else 1)
            m = re.search(re.escape(term), idx[f0]["text"], re.I)
            line = idx[f0]["text"].count("\n", 0, m.start()) + 1 if m else 0
            where.append("%s (%d files, e.g. %s:%d)" % (term, len(files), f0, line))
    n = max(1, len([t for t in feat.get("code_terms") or [] if len(squash(t)) >= 4]))
    return hits / n, where

JUDGE_SYS = "You decide whether features of a game design exist in a C# code base. You are strict: a name match alone is not proof. JSON only."
JUDGE = """CODE INDEX of Assets/Scripts (file: lines; classes; public methods):
{index}

For each FEATURE below decide from the index and the grep evidence:
  "status"       "exists" (clearly implemented), "partial" (some of it) or "missing" (no code for it)
  "evidence"     the file that implements it, or "" when missing
  "deps_present" 0.0-1.0: the share of the feature's depends_on systems that the index shows are implemented
  "missing_deps" the depends_on systems you could not find
Reply with a JSON array of {{"id", "status", "evidence", "deps_present", "missing_deps"}}, one per feature, same order.

FEATURES:
{features}"""

def index_text(idx):
    return "\n".join("%s: %d; %s; %s" % (f, d["lines"], ",".join(d["classes"][:6]), ",".join(d["methods"][:24])) for f, d in sorted(idx.items()))

def scan(feats, scripts_dir, model, log, only=None):
    """Sets status / evidence / deps_present on every feature (or only on the ids in `only`)."""
    idx = index_code(scripts_dir); squashed = {f: squash(f + d["text"]) for f, d in idx.items()}
    todo = [f for f in feats if only is None or f["id"] in only]
    for f in todo:
        f["term_hit"], f["grep"] = grep_feature(f, idx, squashed); f.pop("status", None)
    itext = index_text(idx)
    def batch(chunk):
        body = "\n".join(json.dumps({"id": f["id"], "name": f["name"], "summary": f["summary"], "quote": f.get("quote", ""),
                                     "depends_on": f.get("depends_on", []), "doc_status": f.get("doc_status"),
                                     "grep_hits": f["grep"]}, ensure_ascii=False) for f in chunk)
        return ask_json(JUDGE.format(index=itext, features=body), model, JUDGE_SYS)
    chunks = [todo[i:i + 20] for i in range(0, len(todo), 20)]; cost = 0.0; by = {f["id"]: f for f in todo}
    with cf.ThreadPoolExecutor(4) as ex:
        for verdicts, c in ex.map(batch, chunks):
            cost += c
            if isinstance(verdicts, dict): verdicts = verdicts.get("features") or verdicts.get("verdicts") or [verdicts]   # one feature: the judge may reply with a bare object
            for v in verdicts:
                if not isinstance(v, dict): continue
                f = by.get(v.get("id"))
                if not f: continue
                f["status"] = v.get("status", "missing"); f["evidence"] = v.get("evidence", "")
                f["deps_present"] = max(0.0, min(1.0, float(v.get("deps_present") or 0))); f["missing_deps"] = v.get("missing_deps", [])
    for f in todo:                                    # a feature the judge skipped falls back to the grep result
        if "status" not in f: f.update(status="exists" if f["term_hit"] >= 0.75 else "missing", evidence="", deps_present=0.5, missing_deps=[])
    log("  %d C# files indexed, %d features judged" % (len(idx), len(todo)))
    return cost


# ----------------------------------------------------------------------------------------------- 4. rank
def priority_score(feat):
    """0-100. Higher = build first.
       impact   40 %  how much the playable loop needs it (loop_impact 1-5 from the design text)
       deps     25 %  share of the systems it depends on that already exist in the code (from the scan)
       small    20 %  S = 1, M = 0.5, L = 0.1
       low_risk 15 %  low = 1, medium = 0.5, high = 0.1 (does it change combat, movement or AI results?)"""
    parts = {"impact": max(1, min(5, int(feat.get("loop_impact") or 1))) / 5.0,
             "deps": float(feat.get("deps_present", 0.0)),
             "small": SMALL.get(str(feat.get("size", "L")).upper()[:1], 0.1),
             "low_risk": LOW_RISK.get(str(feat.get("risk", "high")).lower(), 0.1)}
    return round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()), 1), parts

def rank(gaps):
    for g in gaps: g["score"], g["score_parts"] = priority_score(g)
    return sorted(gaps, key=lambda g: (-g["score"], g["id"]))

def score_table(ranked, top=15):
    rows = ["| # | id | feature | score | impact (40) | deps met (25) | small (20) | low risk (15) | size | risk |", "|---|---|---|---|---|---|---|---|---|---|"]
    for i, g in enumerate(ranked[:top]):
        p = g["score_parts"]
        rows.append("| %d | %s | %s | **%.1f** | %.1f | %.1f | %.1f | %.1f | %s | %s |" % (
            i + 1, g["id"], g["name"], g["score"], 40 * p["impact"], 25 * p["deps"], 20 * p["small"], 15 * p["low_risk"], g.get("size"), g.get("risk")))
    return "\n".join(rows)


# ----------------------------------------------------------------------------------------------- 5. write
SPEC_SYS = "You turn one design requirement into a short, checkable specification for a Unity C# feature. JSON only."
SPEC = """A feature of the design is missing from the game. Write its acceptance requirements so that a script can check them.

FEATURE: {feat}

DESIGN TEXT ({gdd_file}, the section it comes from):
{section}

CODE INDEX of Assets/Scripts:
{index}

Reply with a JSON object:
  "class_name"    the main new C# class
  "requirements"  3-6 items, each {{"text": what must be true, "pattern": a regular expression that matches C# source under Assets/Scripts
                  or Assets/Tests once it is true}}. One requirement must prove the feature is hooked into the running game (the pattern
                  matches a use of the new class in a file other than its own). One must be a test that exercises it.
  "context_files" up to 6 existing files from the index the author must read first"""

CODE_SYS = ("You are a careful Unity 6 C# engineer adding ONE small feature to an existing game. You write code that compiles the first time: "
            "you read the files you touch and the APIs you call before you write. You never run commands.")
CODE = """Add this missing feature to the game. Work in the Unity project folder "{unity}".

FEATURE: {name}: {summary}
DESIGN TEXT ({gdd_file}): "{quote}"
{section}

REQUIREMENTS (a script re-scans the code after you finish; every pattern must match):
{reqs}

RULES
- You may create or edit files only under "{unity}/Assets/Scripts/" and "{unity}/Assets/Tests/". Nothing else: no scenes, prefabs, data, art, docs.
- Read first: {context}. Follow the conventions you see (namespaces Ambush.*, runtime-built UI, FeatureFlags, [RuntimeInitializeOnLoadMethod] bootstraps).
- New behaviour goes in new files; edits to existing files are a few lines of hook-up. Do not change any existing number, rule or test.
- Put the feature behind a new FeatureFlags property that defaults to true, so it runs in the built game.
- Runtime code must work in a standalone build: no UnityEditor, AssetDatabase or Shader.Find; build visuals in code or load with Resources.
- Must not throw when its inputs are absent (other scenes, no squads yet). No per-frame allocations that grow.
- Add one PlayMode or EditMode test next to the existing tests (look at one existing test file and its .asmdef first) that exercises the feature.
- Do not write .meta files; Unity creates them.
{feedback}
When you are done, reply with a short list: the files you created or changed and one line each on why."""

def gdd_section(gdd_dir, feat, limit=5000):
    text = open(os.path.join(gdd_dir, feat["gdd_file"]), encoding="utf-8").read(); q = (feat.get("quote") or "")[:60]
    i = text.find(q) if q else -1
    if i < 0: i = max(0, text.find(feat.get("section") or "\0"))
    a = text.rfind("\n#", 0, i); a = 0 if a < 0 else a
    return text[a:a + limit]

def git_changes(repo):
    out = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo, capture_output=True, text=True).stdout
    res = {}
    for l in out.splitlines():                      # status + content hash, so a second edit of an already-new file still counts as a change
        if not l.strip(): continue
        p = l[3:].strip().strip('"'); fp = os.path.join(repo, p)
        res[p] = l[:2] + (hashlib.sha1(open(fp, "rb").read()).hexdigest()[:10] if os.path.isfile(fp) else "")
    return res

def write_feature(game, unity, feat, spec, section, model, feedback, log):
    before = git_changes(game)
    reqs = "\n".join("- %s   [pattern: %s]" % (r["text"], r["pattern"]) for r in spec["requirements"])
    prompt = CODE.format(unity=unity, name=feat["name"], summary=feat["summary"], gdd_file=feat["gdd_file"], quote=feat.get("quote", ""),
                         section=section, reqs=reqs, context=", ".join(spec.get("context_files") or ["Game/FeatureFlags.cs"]),
                         feedback=("\nTHE PREVIOUS TRY WAS NOT ACCEPTED. Fix exactly this:\n" + feedback + "\n") if feedback else "")
    reply, cost = claude(prompt, model, CODE_SYS, tools=["Read", "Grep", "Glob", "Edit", "Write"], cwd=game, timeout=2400)
    after = git_changes(game); changed = sorted(p for p in after if after[p] != before.get(p)); stray = []
    for p in changed:                                # anything outside the allowed folders is undone, and reported
        if any(p.startswith(unity + "/" + a) for a in ALLOWED_WRITE): continue
        stray.append(p)
        if after[p][:2] == "??": os.remove(os.path.join(game, p))
        else: subprocess.run(["git", "checkout", "--", p], cwd=game)
    for p in stray: log("  reverted out-of-scope change: " + p)
    return [p for p in changed if p not in stray], stray, reply, cost


# ----------------------------------------------------------------------------------------------- 6. iterate
def check_requirements(game, unity, spec):
    """Deterministic re-scan: every requirement pattern must match some .cs file under Scripts or Tests."""
    texts = {}
    for sub in ALLOWED_WRITE:
        for root, _, names in os.walk(os.path.join(game, unity, sub)):
            for n in names:
                if n.endswith(".cs"): p = os.path.join(root, n); texts[os.path.relpath(p, game)] = open(p, encoding="utf-8", errors="replace").read()
    res = []
    for r in spec["requirements"]:
        try: rx = re.compile(r["pattern"], re.M)
        except re.error as e: res.append({"text": r["text"], "pattern": r["pattern"], "met": False, "where": "bad pattern: %s" % e}); continue
        own = spec.get("class_name", "\0") + ".cs"; hit = [f for f, t in texts.items() if rx.search(t)]
        hook = "hook" in r["text"].lower() or "other than" in r["text"].lower()
        if hook: hit = [f for f in hit if not f.endswith("/" + own)]
        res.append({"text": r["text"], "pattern": r["pattern"], "met": bool(hit), "where": hit[0] if hit else ""})
    return res

def run_verify(cmd, game, log_path):
    r = subprocess.run(cmd, shell=True, cwd=game, capture_output=True, text=True, timeout=3600)
    out = (r.stdout or "") + "\n" + (r.stderr or ""); open(log_path, "w").write(out)
    errs = [l for l in out.splitlines() if re.search(r"error CS\d+|FAILED|Failed:|rc=[1-9]|ERROR", l)]
    return r.returncode == 0, "\n".join(errs[-25:]) or out[-1500:]


# ----------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, help="root of the game repo (contains docs/gdd and the Unity project)")
    ap.add_argument("--unity", default="ELVATR GAME 1", help="Unity project folder inside the repo")
    ap.add_argument("--model", default="sonnet", help="model for extract / scan / spec"); ap.add_argument("--code-model", default="opus")
    ap.add_argument("--per-file", type=int, default=10); ap.add_argument("--max-tries", type=int, default=3)
    ap.add_argument("--verify-cmd", default="", help="run in the game repo after each write; exit 0 = compiles and tests pass; {class} = the new class name")
    ap.add_argument("--plan-only", action="store_true", help="stop after ranking"); ap.add_argument("--pick", default="", help="build this feature id instead of rank 1 (logged)")
    ap.add_argument("--resume", default="", help="outputs/run-... folder of a run that stopped after a write: reuse its features, target and spec, start at the re-scan")
    a = ap.parse_args()
    game = os.path.abspath(os.path.expanduser(a.game)); gdd = os.path.join(game, "docs/gdd"); scripts = os.path.join(game, a.unity, "Assets/Scripts")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S"); out = os.path.join(HERE, "outputs", "run-" + ts); cache = os.path.join(HERE, "outputs", "cache")
    os.makedirs(out, exist_ok=True); os.makedirs(cache, exist_ok=True); logf = open(os.path.join(out, "run.log"), "w"); cost = 0.0
    def log(s=""):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()
    def save(name, obj):
        with open(os.path.join(out, name), "w") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False))

    log("GOAL: close the most valuable gap between %s and %s" % (os.path.relpath(gdd, game), os.path.relpath(scripts, game)))
    prev = os.path.abspath(a.resume) if a.resume else ""
    if prev:
        feats = json.load(open(os.path.join(prev, "features.json"))); log("\n[1-2] resumed from %s: features and scan verdicts reused" % os.path.basename(prev))
    else:
        log("\n[1] extract: required features from the GDD"); feats, c = extract_features(gdd, a.model, cache, a.per_file, log); cost += c
        log("\n[2] scan: which features exist in the code"); cost += scan(feats, scripts, a.model, log)
    save("features.json", feats)
    n = {s: sum(1 for f in feats if f["status"] == s) for s in ("exists", "partial", "missing")}
    log("  exists %(exists)d   partial %(partial)d   missing %(missing)d" % n)
    gaps = [f for f in feats if f["status"] == "missing"]
    log("\n[3] gaps: %d missing features" % len(gaps))
    for g in gaps: log("  %-6s %-44s %s" % (g["id"], g["name"][:44], g["gdd_file"]))
    ranked = rank(gaps); table = score_table(ranked, top=len(ranked))
    log("\n[4] priority_score (weights: %s)" % ", ".join("%s %d %%" % (k, v * 100) for k, v in WEIGHTS.items())); log(score_table(ranked)); save("scores.md", table)
    save("gaps.json", ranked)
    if not ranked: log("no gaps: nothing to build"); return 0
    target = next((g for g in ranked if g["id"] == a.pick), None) if a.pick else ranked[0]
    if target is None: log("--pick %s is not a gap" % a.pick); return 2
    log("\nTARGET: %s  %s  (score %.1f%s)\n  %s\n  GDD: \"%s\"" % (target["id"], target["name"], target["score"],
        ", picked by hand with --pick" if a.pick else ", rank 1", target["summary"], target.get("quote", "")))
    if a.plan_only: log("\n--plan-only: stopping before the write. Cost so far $%.2f" % cost); return 0

    section = gdd_section(gdd, target)
    if prev: spec, c = json.load(open(os.path.join(prev, "spec.json"))), 0.0
    else: spec, c = ask_json(SPEC.format(feat=json.dumps({k: target[k] for k in ("name", "summary", "quote", "code_terms", "depends_on")}, ensure_ascii=False),
                                   gdd_file=target["gdd_file"], section=section, index=index_text(index_code(scripts))), a.model, SPEC_SYS); cost += c
    save("spec.json", spec); log("\n[5] requirements for %s:" % spec.get("class_name"))
    for r in spec["requirements"]: log("  - %s" % r["text"])

    feedback, done, tries = "", False, []
    for t in range(1, a.max_tries + 1):
        if prev and t == 1:
            log("\n[5] write, try 1: already done in the resumed run, not repeated"); changed, stray, reply = [], [], "(resumed)"
        else:
            log("\n[5] write, try %d of %d (claude -p, %s, tools Read/Grep/Glob/Edit/Write)" % (t, a.max_tries, a.code_model))
            changed, stray, reply, c = write_feature(game, a.unity, target, spec, section, a.code_model, feedback, log); cost += c
        for p in changed: log("  wrote " + p)
        log("\n[6] re-scan after try %d" % t); res = check_requirements(game, a.unity, spec)
        for r in res: log("  %s  %s%s" % ("MET  " if r["met"] else "UNMET", r["text"], ("   <- " + r["where"]) if r["where"] else ""))
        cost += scan(feats, scripts, a.model, log, only={target["id"]}); log("  scan verdict for the feature: %s (%s)" % (target["status"], target.get("evidence", "")))
        ok_v, verr = True, ""
        if a.verify_cmd:
            vc = a.verify_cmd.replace("{class}", spec.get("class_name", ""))
            log("  verify: " + vc); ok_v, verr = run_verify(vc, game, os.path.join(out, "verify-try%d.log" % t)); log("  verify: %s" % ("PASS" if ok_v else "FAIL"))
        unmet = [r for r in res if not r["met"]]; done = not unmet and target["status"] == "exists" and ok_v
        tries.append({"try": t, "changed": changed, "reverted": stray, "requirements": res, "scan_status": target["status"], "verify_pass": ok_v,
                      "verify_errors": verr if not ok_v else "", "agent_reply": reply}); save("tries.json", tries)
        if done: log("\nSTOP: every requirement met after try %d." % t); break
        feedback = "\n".join(["Unmet requirement: %s [pattern: %s]" % (r["text"], r["pattern"]) for r in unmet] +
                             (["The code scan still judges the feature '%s'." % target["status"]] if target["status"] != "exists" else []) +
                             (["Compile / test output:\n" + verr] if not ok_v else []))
        log("  not accepted:\n" + textwrap.indent(feedback[:1500], "    "))
    else: log("\nSTOP: %d tries used, requirements still unmet." % a.max_tries)
    save("report.json", {"target": target, "spec": spec, "accepted": done, "tries": len(tries), "cost_usd": round(cost, 2),
                         "counts": n, "weights": WEIGHTS, "picked_by_hand": bool(a.pick)})
    log("cost $%.2f   logs in %s" % (cost, out)); return 0 if done else 2

if __name__ == "__main__":
    sys.exit(main())
