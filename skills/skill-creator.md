# Skill Creator — Create and Modify Hermes Agent Skills

Create new BIM workflow skills or modify existing ones. Skills are Markdown files that describe when and how the Hermes agent should approach a type of task.

## When to use
- "Create a new skill for [workflow]"
- "Add a skill that handles [task type]"
- "Update the proxy reclassification skill to also check bSDD"
- "Show me the available skills"
- "Modify the skill named [name] to include [new step]"

## Tools needed
This skill uses the skill registry API:
- `GET /api/skills` — list all skills
- `GET /api/skills/{name}` — read a skill
- `POST /api/skills/create` — create a new skill
- `PUT /api/skills/{name}` — update a skill
- `DELETE /api/skills/{name}` — delete a skill

## Skill file structure

A skill file is a Markdown document with these sections:

```markdown
# {Title} — {Subtitle}

{One-paragraph description of what this skill does.}

## When to use
- Trigger condition 1
- Trigger condition 2
- Example user prompts that should trigger this skill

## Tools needed
This skill uses the `ifc-agent` MCP server tools:
- `tool_name_1`
- `tool_name_2`

## Workflow

### Step 1: {Step name}
{What to do and which tool to call}

### Step 2: {Step name}
{What to do and which tool to call}

...

## Report format
{How to format the final output to the user}
```

## Workflow for creating a new skill

### Step 1: Understand the workflow
Ask the user:
- What task does this skill perform?
- When should it trigger? (user prompts, conditions)
- Which MCP tools does it need?
- What should the output look like?

### Step 2: Draft the skill content
Create a structured Markdown document following the template above.

Good skill writing principles:
- Be specific about which tool to call at each step
- Include example inputs and outputs
- Specify how to handle errors and edge cases
- Add a report format with emoji status indicators
- Include priority/severity guidance

### Step 3: Create via API
```
POST /api/skills/create
{
  "name": "my-new-skill",
  "title": "My New Skill — Brief Subtitle",
  "description": "What this skill does in one paragraph.",
  "when_to_use": "- User asks X\n- Condition Y is met",
  "workflow": "### Step 1: ...\n### Step 2: ...",
  "tools_needed": ["load_model", "run_baseline_check"]
}
```

### Step 4: Test the skill
Ask the agent to perform the workflow described in the skill on a test IFC file.
Verify each step works as described.

### Step 5: Refine
Update with `PUT /api/skills/{name}` with improved content.

## Existing skills reference
| Skill | Purpose |
|-------|---------|
| `ifc-baseline-check` | 6-module quality check |
| `ifc-diff` | Compare two IFC versions |
| `ifc-patch` | Apply corrections to IFC file |
| `bsdd-classify` | bSDD classification lookup and assignment |
| `ids-workflow` | IDS authoring and validation |
| `cobie-complete` | COBie FM handover readiness |
| `proxy-reclassify` | IfcBuildingElementProxy reclassification |
| `bim-team-review` | Full project quality review |
| `skill-creator` | This skill — create new skills |

## Skill naming conventions
- Use lowercase kebab-case: `my-skill-name`
- Be descriptive but concise
- Include the domain: `ifc-`, `ids-`, `bsdd-`, `cobie-`, `bim-`
- Examples: `ifc-coordinate-check`, `ids-from-bep`, `cobie-fm-export`
