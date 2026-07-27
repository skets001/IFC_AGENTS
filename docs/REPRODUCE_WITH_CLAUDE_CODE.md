# Reproduce it with Claude Code

The whole point of packaging this PoC is that the **agents + skills + tool-use** pattern is not tied to our bespoke loop — you can reproduce it with an off-the-shelf agent harness. This guide shows how to drive the *same IfcOpenShell tools* from **Claude Code**, so the AI/ML team can learn the pattern with a mainstream agent.

There are three tracks, easiest first.

---

## Track A — run our own loop (baseline)

The fastest way to see the loop is our own runner (no Claude Code needed):

```bash
pip install -e ".[dev]"
cp .env.example .env          # add ANTHROPIC_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY
python poc/run_agent_poc.py tests/test_data/demo_model.ifc
```

Read `src/ifc_agent/agent_loop.py` alongside the printed tool trace — that *is* the pattern in ~250 lines.

---

## Track B — drive the tools from Claude Code (the main event)

Here Claude Code is the "brain" and our MCP server is the "hands." Claude Code calls our IfcOpenShell tools exactly the way our own loop does.

### 1. Start the tool server

```bash
ifc-agent serve
# FastMCP (streamable-HTTP) on http://127.0.0.1:8000/mcp
```

### 2. Register it with Claude Code

Either via the CLI:

```bash
claude mcp add --transport http ifc-agent http://127.0.0.1:8000/mcp
claude mcp list          # confirm it's connected
```

…or commit a project-scoped `.mcp.json` so your whole team gets it automatically:

```json
{
  "mcpServers": {
    "ifc-agent": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Inside a Claude Code session, run `/mcp` to see the server and its tools. They appear namespaced, e.g. `mcp__ifc-agent__load_model`, `mcp__ifc-agent__get_proxies`, `mcp__ifc-agent__reclassify_element`.

### 3. Bring the skills across

Claude Code reads **Agent Skills** from `.claude/skills/<name>/SKILL.md`, where each file has YAML frontmatter (`name`, `description`) followed by the workflow body. Our `skills/*.md` are the same idea minus the frontmatter, so converting is mechanical:

```bash
for f in skills/*.md; do
  name=$(basename "$f" .md)
  mkdir -p ".claude/skills/$name"
  {
    echo "---"
    echo "name: $name"
    echo "description: $(grep -m1 '^# ' "$f" | sed 's/^# //')"
    echo "---"
    echo
    cat "$f"
  } > ".claude/skills/$name/SKILL.md"
done
```

Now Claude Code will auto-load, say, `proxy-reclassify` when the task matches its description, and follow its workflow — the same playbook our loop uses.

> Tighten each skill's `description` so Claude Code triggers it at the right time — the description is what the model matches against.

### 4. Give it project context (optional but recommended)

Drop a `CLAUDE.md` at the repo root with the same kind of orientation our parent repo keeps in `AGENTS.md` (entry points, how tools save files, "never overwrite the original"). Claude Code loads it automatically as standing context.

### 5. Run it

Open Claude Code in the repo and prompt, e.g.:

```
Load tests/test_data/demo_model.ifc, run a baseline check, and reclassify any
IfcBuildingElementProxy elements you can confidently identify to correct IFC
classes. Keep landscape/annotation placeholders as proxies. Write a corrected
file and confirm the proxy count dropped. Show me exactly what changed.
```

Claude Code will call `mcp__ifc-agent__load_model` → `run_baseline_check` → `get_proxies` → `reclassify_element` → `run_specific_check`, then summarize — reproducing the PoC with a different brain over identical tools.

**Key point on keys:** Claude Code uses *its own* model, so Track B needs no LLM key for the reasoning. But three tools call an LLM *internally* (`auto_classify_proxies`, `enrich_cobie_data`, `extract_bep_rules`) — those still read a provider key from `.env`. The query/check/patch tools need no key at all.

---

## Track C — embed it with the Claude Agent SDK

For a programmatic agent (a service, a batch job), the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk) (Python/TypeScript) runs the same loop headlessly and can attach the same MCP server. This is the path to fold the PoC into the future digital-twin platform: point the SDK at `http://127.0.0.1:8000/mcp`, load the skills, and orchestrate corrections as a backend job with the human-approval gate in front of any write.

---

## What to take away

| Concept | In this repo | In Claude Code |
|---------|--------------|----------------|
| **Tool use** | 24 `@mcp.tool` IfcOpenShell functions | `mcp__ifc-agent__*` over `.mcp.json` |
| **Skills** | `skills/*.md` playbooks | `.claude/skills/*/SKILL.md` |
| **Agent persona** | `hermes_profiles.py` system prompts | `CLAUDE.md` + subagents |
| **The loop** | `agent_loop.py` | Claude Code's built-in agent loop |

Same architecture, two harnesses. That portability — reasoning is prompt+tools, tools are deterministic IfcOpenShell — is the reusable lesson for the platform.

> CLI flags and skill format evolve; check `claude --help`, `claude mcp --help`, and the current Claude Code docs for your installed version.
