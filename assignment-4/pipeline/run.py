#!/usr/bin/env python3
"""Ambush! dynamic content pipeline.

    python3 tools/content_pipeline/run.py <assault|unit_cards|battle_text> [--rounds 3] [--model sonnet]

Generator (claude -p, headless, your Claude subscription) reads only the GDD files for the content type
and writes JSON. Deterministic checks (JSON schema + rule checks in code) and a separate critic agent
(claude -p, different system prompt and role) review it. Issues go back to the generator, which revises
and resubmits — at most --rounds rounds. Every round is logged to tools/content_pipeline/logs/.
Passing output is written to the game's data folder; a failure after the last round exits non-zero.
"""
import argparse, datetime, json, os, re, subprocess, sys
import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from content_types import TYPES, REPO_GAME_DATA  # noqa: E402


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def claude(system_prompt, prompt, model):
    """One headless call. No tools: the model only reads what we pass in."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", system_prompt]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=HERE, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed ({r.returncode}): {r.stderr[:400]}")
    env = json.loads(r.stdout)
    if env.get("is_error"):
        raise RuntimeError(f"claude -p returned an error: {str(env.get('result'))[:400]}")
    return env.get("result", ""), env.get("total_cost_usd")


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in the reply")
    return json.loads(t[i:j + 1])


def deterministic(doc, ct):
    issues = []
    v = jsonschema.Draft202012Validator(ct["schema"])
    for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path)):
        issues.append("schema: $" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.path) + f": {e.message[:160]}")
    if not issues:  # rule checks assume a schema-valid document
        issues += ["rule: " + s for s in ct["rules"](doc)]
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("content_type", choices=sorted(TYPES))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--strict", action="store_true", help="treat every critic issue of kind contradiction as blocking, whatever its severity")
    a = ap.parse_args()
    ct = TYPES[a.content_type]
    gen_sys = read("tools/content_pipeline/prompts/generator.md")
    crit_sys = read("tools/content_pipeline/prompts/critic.md")
    sources = "\n\n".join(f"=== {p} ===\n{read(p)}" for p in ct["gdd"] + ct["extra"])
    schema = json.dumps(ct["schema"], indent=1)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    log_path = os.path.join(HERE, "logs", f"{a.content_type}-{stamp}.jsonl")
    md_path = log_path.replace(".jsonl", ".md")
    md = [f"# {a.content_type} — {stamp}\n", f"GDD inputs: {', '.join(ct['gdd'] + ct['extra'])}\n"]
    doc, feedback, cost = None, None, 0.0

    for rnd in range(1, a.rounds + 1):
        if feedback is None:
            prompt = f"{sources}\n\n=== TASK ===\n{ct['task']}\n\n=== JSON SCHEMA ===\n{schema}\n\nReturn the JSON object only."
        else:
            prompt = (f"{sources}\n\n=== TASK ===\n{ct['task']}\n\n=== JSON SCHEMA ===\n{schema}\n\n"
                      f"=== YOUR PREVIOUS SUBMISSION ===\n{json.dumps(doc, indent=1, ensure_ascii=False)}\n\n"
                      f"=== ISSUES TO FIX (from the checks and the critic) ===\n{feedback}\n\n"
                      "Fix every issue. Keep what was not flagged. Return the full revised JSON object only.")
        raw, c = claude(gen_sys, prompt, a.model); cost += c or 0
        try:
            doc = parse_json(raw); parse_err = None
        except Exception as e:
            doc, parse_err = {}, str(e)
        det = [f"parse: {parse_err}"] if parse_err else deterministic(doc, ct)
        crit = {"pass": False, "issues": []}
        if not parse_err:
            craw, c = claude(crit_sys, f"{sources}\n\n=== WHAT THE CONTENT IS FOR ===\n{ct['task']}\n\n=== CANDIDATE JSON ===\n"
                                       f"{json.dumps(doc, indent=1, ensure_ascii=False)}", a.model); cost += c or 0
            try:
                crit = parse_json(craw)
            except Exception as e:
                crit = {"pass": False, "issues": [{"severity": "block", "kind": "rule", "where": "$", "problem": f"critic reply unparseable: {e}", "gdd": "", "fix": ""}]}
        blocks = [i for i in crit.get("issues", []) if i.get("severity") == "block"
                  or (a.strict and i.get("kind") == "contradiction")]
        ok = not det and not blocks
        rec = {"round": rnd, "deterministic_issues": det, "critic_pass": crit.get("pass"), "critic_issues": crit.get("issues", []),
               "pass": ok, "output": doc}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        md.append(f"\n## Round {rnd} — {'PASS' if ok else 'FAIL'}\n")
        md.append(f"Deterministic checks: {'clean' if not det else str(len(det)) + ' issue(s)'}\n")
        md += [f"- {d}\n" for d in det]
        md.append(f"Critic: {'pass' if crit.get('pass') else 'fail'} — {len(blocks)} blocking, {len(crit.get('issues', [])) - len(blocks)} minor\n")
        md += [f"- [{i.get('severity')}/{i.get('kind')}] `{i.get('where')}` — {i.get('problem')}" + (f" GDD: \"{i.get('gdd')}\"" if i.get('gdd') else "") + (f" Fix: {i.get('fix')}" if i.get('fix') else "") + "\n" for i in crit.get("issues", [])]
        print(f"[{a.content_type}] round {rnd}: deterministic {len(det)} issue(s), critic {len(blocks)} blocking -> {'PASS' if ok else 'revise'}")
        if ok:
            out_rel = os.path.join(REPO_GAME_DATA, ct["out"])
            os.makedirs(os.path.join(REPO, REPO_GAME_DATA), exist_ok=True)
            with open(os.path.join(REPO, out_rel), "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False); f.write("\n")
            with open(os.path.join(HERE, "out", ct["out"]), "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False); f.write("\n")
            md.append(f"\n**Result: PASS in round {rnd}.** Written to `{out_rel}`. Cost reported by claude -p: ${cost:.3f}\n")
            open(md_path, "w", encoding="utf-8").write("".join(md))
            print(f"[{a.content_type}] PASS -> {out_rel}  (log {os.path.relpath(md_path, REPO)})")
            return 0
        feedback = "\n".join([f"- {d}" for d in det] + [f"- [{i.get('kind')}] {i.get('where')}: {i.get('problem')} -> {i.get('fix')}" for i in blocks]
                             + [f"- (minor) [{i.get('kind')}] {i.get('where')}: {i.get('problem')} -> {i.get('fix')}" for i in crit.get("issues", []) if i.get("severity") != "block"])
    md.append(f"\n**Result: FAIL after {a.rounds} rounds.** Nothing written to the game. Cost: ${cost:.3f}\n")
    open(md_path, "w", encoding="utf-8").write("".join(md))
    print(f"[{a.content_type}] FAIL after {a.rounds} rounds — see {os.path.relpath(md_path, REPO)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
