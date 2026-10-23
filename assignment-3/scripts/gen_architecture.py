#!/usr/bin/env python3
"""
Regenerate docs/architecture.md from the live crew state so the diagrams
never drift from the code.

Inputs:
  - .claude/agents/*.md         (name, model, role, allowed files)
  - .claude/state/project.json  (open tasks + blocker→unblocks graph)
  - .claude/tasks/*.json        (open task specs — ids, assigned_agent)

Outputs:
  - docs/architecture.md with three Mermaid diagrams:
      a) Agent hierarchy — Noah → HQ → workers → Sentry → HQ, with each
         agent's model.
      b) Shared memory map — read/write edges between every agent and the
         crew's shared files (project.json, decisions.md, messages/, inbox/,
         tasks/, CLAUDE.md).
      c) Task dependency graph — the live open tasks + depends-on edges
         inferred from project.json.blocked[*].unblocks_tasks.

Run manually or via the PostToolUse hook (which fires on any Write/Edit
that touches an agent file, CLAUDE.md, or a task spec).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = REPO / ".claude" / "agents"
TASKS = REPO / ".claude" / "tasks"
STATE = REPO / ".claude" / "state" / "project.json"
OUT = REPO / "docs" / "architecture.md"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -----------------------------------------------------------------------------
# Agent-file parsing

AGENT_ORDER = ["hq", "forge", "ledger", "painter", "painter-b",
               "cartographer", "sentry", "playtest"]


def parse_agent(path: Path) -> dict:
    """Parse frontmatter + a one-line role summary from an agent .md."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    front = {}
    body = text
    if m:
        for ln in m.group(1).splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                front[k.strip()] = v.strip()
        body = m.group(2)
    # Role = first non-empty paragraph under the first "# Role" or just first para
    role = ""
    role_match = re.search(r"^#\s*Role\s*\n+(.+?)(?:\n\n|\Z)", body, re.MULTILINE | re.DOTALL)
    if role_match:
        role = role_match.group(1).strip().split("\n")[0]
    else:
        for p in body.strip().split("\n\n"):
            if p.strip() and not p.startswith("#"):
                role = p.strip().split("\n")[0]
                break
    role = re.sub(r"[\*\`]", "", role)[:120]

    return {
        "name": front.get("name") or path.stem,
        "model": front.get("model") or "unknown",
        "role": role,
        "tools": front.get("tools") or "",
    }


def load_all_agents() -> dict[str, dict]:
    out = {}
    for p in sorted(AGENTS.glob("*.md")):
        a = parse_agent(p)
        out[a["name"]] = a
    return out


# -----------------------------------------------------------------------------
# Diagram A — Agent hierarchy

def diagram_agent_hierarchy(agents: dict) -> str:
    """Noah gates → HQ → each worker → Sentry → HQ. Model shown in each node."""
    def node_label(name: str) -> str:
        a = agents.get(name, {"model": "?"})
        model = a["model"]
        return f'{name}<br/><i>model: {model}</i>'

    workers = [n for n in AGENT_ORDER if n not in ("hq", "sentry") and n in agents]
    lines = ["```mermaid", "flowchart TD",
             '    noah["Noah<br/><i>user</i>"]:::user',
             f'    hq["{node_label("hq")}"]:::hq',
             f'    sentry["{node_label("sentry")}"]:::sentry']
    for w in workers:
        lines.append(f'    {w.replace("-", "_")}["{node_label(w)}"]:::worker')

    lines.append("")
    lines.append("    noah -->|user ask + approval gates| hq")
    for w in workers:
        wid = w.replace("-", "_")
        lines.append(f"    hq -->|task spec JSON| {wid}")
    for w in workers:
        wid = w.replace("-", "_")
        lines.append(f"    {wid} -->|structured message + handoff| sentry")
    lines.append("    sentry -->|verdict + bug report| hq")

    # Styling
    lines.append("")
    lines.append("    classDef user     fill:#fff2cc,stroke:#b58b00,color:#333")
    lines.append("    classDef hq       fill:#dbe9ff,stroke:#2a5bbd,color:#111")
    lines.append("    classDef worker   fill:#e7f2d6,stroke:#5a8f23,color:#111")
    lines.append("    classDef sentry   fill:#f8d7d7,stroke:#a93a3a,color:#111")
    lines.append("```")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Diagram B — Shared memory map

def diagram_memory_map(agents: dict) -> str:
    """Who reads / writes each shared file. Pulled from the per-agent protocol
    in CLAUDE.md (encoded here as a lookup table — the authoritative version is
    in CLAUDE.md itself; divergence shows up when this file regenerates stale)."""

    files = [
        ("project_json",   ".claude/state/project.json",   "HQ-only write · all read"),
        ("decisions_md",   ".claude/state/decisions.md",   "HQ-only write · all read"),
        ("messages",       ".claude/messages/<id>.json",   "worker writes · HQ reads"),
        ("inbox",          ".claude/inbox/<agent>.md",     "user/dashboard writes · HQ reads · agent reads own"),
        ("tasks",          ".claude/tasks/<id>.json",      "HQ-only write · worker reads own"),
        ("claude_md",      "CLAUDE.md",                    "HQ-only write · all read"),
        ("archive",        ".claude/archive/tasks/",       "HQ-only move · workers do NOT read by default"),
    ]
    writers = {
        "project_json": {"hq"},
        "decisions_md": {"hq"},
        "messages":     {"forge", "ledger", "painter", "painter-b", "cartographer", "sentry", "playtest"},
        "inbox":        {"user", "dashboard", "hq"},
        "tasks":        {"hq"},
        "claude_md":    {"hq"},
        "archive":      {"hq"},
    }
    readers = {
        "project_json": set(AGENT_ORDER),
        "decisions_md": set(AGENT_ORDER),
        "messages":     {"hq"},
        "inbox":        {"hq", "painter"},
        "tasks":        set(AGENT_ORDER),
        "claude_md":    set(AGENT_ORDER),
        "archive":      {"hq"},  # read-on-demand when HQ cites a file
    }

    lines = ["```mermaid", "flowchart LR"]
    # Node declarations: files
    for fid, label, _ in files:
        lines.append(f'    {fid}[("{label}")]:::file')
    # Node declarations: actors
    lines.append('    noah["Noah<br/><i>user</i>"]:::user')
    for n in AGENT_ORDER:
        if n not in agents:
            continue
        lines.append(f'    {n.replace("-", "_")}["{n}"]:::agent')

    lines.append("")
    # Write edges (W)
    for fid, _, _ in files:
        for actor in sorted(writers[fid]):
            if actor == "user":
                lines.append(f"    noah -- W --> {fid}")
            elif actor == "dashboard":
                pass  # dashboard isn't rendered as a node; skip to keep sparse
            else:
                aid = actor.replace("-", "_")
                lines.append(f"    {aid} == W ==> {fid}")
    # Read edges (R, dashed)
    for fid, _, _ in files:
        for actor in sorted(readers[fid]):
            if actor == "user":
                lines.append(f"    noah -. R .-> {fid}")
            else:
                aid = actor.replace("-", "_")
                lines.append(f"    {aid} -. R .-> {fid}")

    # Legend-ish policy labels
    lines.append("")
    lines.append("    classDef file  fill:#f4f0e6,stroke:#8a7a4a,color:#111")
    lines.append("    classDef agent fill:#e7f2d6,stroke:#5a8f23,color:#111")
    lines.append("    classDef user  fill:#fff2cc,stroke:#b58b00,color:#333")
    lines.append("```")

    # Append a policy table that's easier to read than edge labels
    lines.append("")
    lines.append("| File | Writers | Readers |")
    lines.append("|---|---|---|")
    for fid, label, policy in files:
        w = ", ".join(sorted(writers[fid])) or "—"
        r = ", ".join(sorted(readers[fid])) if readers[fid] else "—"
        lines.append(f"| `{label}` | {w} | {r} |")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Diagram C — Task dependency graph

def diagram_task_dependencies() -> str:
    """Build a graph of open tasks + depends-on edges inferred from
    project.json.blocked[*].unblocks_tasks (blocker → task)."""
    open_tasks = {}
    for p in sorted(TASKS.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if d.get("status") == "closed":
            continue
        tid = d.get("id") or p.stem.split("-")[0]
        slug = p.stem
        open_tasks[tid] = {
            "id": tid,
            "slug": slug,
            "assigned_agent": d.get("assigned_agent", "?"),
            "title": (d.get("title") or "")[:60],
            "blocked_by": d.get("blocked_by") or d.get("depends_on") or [],
        }

    blockers = []
    if STATE.exists():
        try:
            s = json.loads(STATE.read_text())
            blockers = s.get("blocked") or []
        except Exception:
            pass

    lines = ["```mermaid", "flowchart LR"]
    # Blocker nodes (owner-coloured)
    for i, b in enumerate(blockers):
        bid = f"B{i}"
        label = f'{b["item"]}<br/><i>owner: {b["owner"]}</i>'
        lines.append(f'    {bid}("{label}"):::blocker')
    # Task nodes
    for tid, t in sorted(open_tasks.items()):
        label = f'{tid}<br/>{t["title"]}<br/><i>agent: {t["assigned_agent"]}</i>'
        lines.append(f'    T{tid}["{label}"]:::task_{t["assigned_agent"]}')

    lines.append("")
    # Blocker → task edges
    for i, b in enumerate(blockers):
        bid = f"B{i}"
        for tid in b.get("unblocks_tasks") or []:
            if tid in open_tasks or any(tid in k for k in open_tasks):
                target = tid if tid.startswith("T") else "T" + tid
                lines.append(f"    {bid} -- blocks --> {target}")

    # Explicit task-to-task deps
    for tid, t in sorted(open_tasks.items()):
        for dep in t["blocked_by"]:
            dep_id = dep if dep.startswith("T") else "T" + dep
            lines.append(f"    {dep_id} --> T{tid}")

    # Styling
    lines.append("")
    lines.append("    classDef blocker       fill:#f8d7d7,stroke:#a93a3a,color:#111")
    lines.append("    classDef task_painter       fill:#f6ddea,stroke:#9f3a76,color:#111")
    lines.append("    classDef task_cartographer  fill:#e7f2d6,stroke:#5a8f23,color:#111")
    lines.append("    classDef task_forge         fill:#dbe9ff,stroke:#2a5bbd,color:#111")
    lines.append("    classDef task_sentry        fill:#f6efcf,stroke:#8a7030,color:#111")
    lines.append("    classDef task_ledger        fill:#eaeaea,stroke:#555,color:#111")
    lines.append("    classDef task_playtest      fill:#eef3ff,stroke:#3f4fd1,color:#111")
    lines.append("    classDef task_hq            fill:#dbe9ff,stroke:#2a5bbd,color:#111")
    lines.append("```")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Main writer

HEADER = """# Ambush! architecture — auto-generated

Generated from `.claude/agents/*.md` + `.claude/state/project.json` + `.claude/tasks/*.json`
by `scripts/gen_architecture.py`.

**Do not edit by hand** — any change here will be clobbered on the next regen.
If a diagram looks wrong, edit the source (agent frontmatter, task JSON, or
`project.json`) and the PostToolUse hook will regenerate this file.

_Last generated:_ `{ts}`
"""


def main() -> int:
    agents = load_all_agents()
    hierarchy = diagram_agent_hierarchy(agents)
    memory = diagram_memory_map(agents)
    tasks = diagram_task_dependencies()

    body = [
        HEADER.format(ts=iso_now()),
        "## a) Agent hierarchy",
        "",
        "Noah gates the user asks and approvals. HQ owns task splitting + state. "
        "Every worker returns a structured message to Sentry (QA tier), which "
        "verdicts back to HQ. Each node shows the model actually configured in "
        "the agent's frontmatter (sentry checks this against the file at verify "
        "time — see sentry's charter).",
        "",
        hierarchy,
        "",
        "## b) Shared memory map",
        "",
        "The two-file reading rule says every worker starts a task by reading "
        "`project.json` + `decisions.md` and nothing else. The structured "
        "handoff lands in `.claude/messages/<id>.json`. The task spec at "
        "`.claude/tasks/<id>.json` is HQ-owned. Writes are enforced by sentry's "
        "protected-path audit; divergence from the table below is a design bug.",
        "",
        memory,
        "",
        "## c) Open-task dependency graph",
        "",
        "Nodes are the live open tasks from `.claude/tasks/`. Blocker nodes at "
        "the top are the entries in `project.json.blocked[]`; the `unblocks_tasks` "
        "array on each blocker becomes the outgoing edge to every task it "
        "blocks. If a task spec itself declares `blocked_by` / `depends_on`, "
        "those are drawn as task→task edges.",
        "",
        tasks,
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(body), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
