# Hermes Agent Skills

This directory contains skill files that describe BIM workflows the Hermes agent can execute.
Each skill is a Markdown file defining: when to use the skill, which tools to call, and how to format the output.

## Available Skills

| Skill | File | Purpose |
|-------|------|---------|
| IFC Baseline Check | `ifc-baseline-check.md` | 6-module quality check (schema, IDS, spatial, GUID, proxy, type) |
| IFC Diff | `ifc-diff.md` | Compare two IFC versions for additions, deletions, and changes |
| IFC Patch | `ifc-patch.md` | Apply corrections to an IFC file (fix GUIDs, reclassify, add properties) |
| bSDD Classify | `bsdd-classify.md` | Look up buildingSMART Data Dictionary classifications |
| IDS Workflow | `ids-workflow.md` | Author, validate, and manage IDS requirement specifications |
| COBie Complete | `cobie-complete.md` | FM handover readiness check and COBie data enrichment |
| Proxy Reclassify | `proxy-reclassify.md` | Identify and reclassify IfcBuildingElementProxy elements |
| BIM Team Review | `bim-team-review.md` | Full project quality review and correction plan |
| Skill Creator | `skill-creator.md` | Create and modify agent skills |

## Managing Skills via API

Skills can be managed via the REST API:

```bash
# List all skills
GET /api/skills

# Get a specific skill
GET /api/skills/ifc-diff

# Create a new skill
POST /api/skills/create
{
  "name": "my-skill",
  "title": "My Skill — What it Does",
  "description": "One paragraph description.",
  "when_to_use": "- When the user asks X",
  "workflow": "### Step 1: ...\n### Step 2: ...",
  "tools_needed": ["load_model", "run_baseline_check"]
}

# Update an existing skill
PUT /api/skills/my-skill
{"name": "my-skill", "content": "# My Skill\n\n..."}

# Delete a skill
DELETE /api/skills/my-skill
```

## Skill File Structure

```markdown
# Title — Subtitle

One-paragraph description.

## When to use
- Trigger condition 1
- Example user prompts

## Tools needed
This skill uses the `ifc-agent` MCP server tools:
- `tool_name`

## Workflow

### Step 1: Step name
What to do and which tool to call.

## Report format
How to format the output.
```

## MCP Tools Available to Skills

| Category | Tools |
|----------|-------|
| **Query** | `load_model`, `get_entities`, `get_entity_properties`, `get_spatial_tree`, `search_elements` |
| **Check** | `run_baseline_check`, `run_specific_check`, `get_proxies`, `get_orphan_elements` |
| **Diff** | `diff_ifc_files`, `diff_element_properties` |
| **Patch** | `fix_guid_duplicates`, `reclassify_element`, `add_or_update_pset`, `assign_to_spatial_container`, `add_classification_reference`, `apply_patch_set` |
| **bSDD** | `bsdd_search_classes`, `bsdd_get_class`, `bsdd_list_dictionaries`, `bsdd_validate_element_classification` |
| **IDS** | `list_ids_specs`, `validate_ids_spec`, `create_ids_from_model` |
| **BEP** | `extract_bep_rules`, `compile_bep_yaml_to_ids` |
| **Classify** | `auto_classify_proxies` |
| **COBie** | `enrich_cobie_data` |

## Agentic loop

When using `/api/agent/run`, Hermes reads the relevant skill file as part of its system prompt
and then executes the workflow by calling tools iteratively until the task is complete.

## Installing in Claude Code / external Hermes

Copy skill files to your Hermes/Claude Code skills directory:

```bash
cp skills/*.md ~/.hermes/skills/
# or reference this directory in your Hermes config
```
