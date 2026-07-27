# IFC Baseline Check — Hermes Skill

## Purpose
Run a comprehensive quality check on any IFC building model. This is the foundation check that should run on every model before any enrichment or classification work.

## When to use
- User uploads or mentions an IFC file
- User asks "check this model" or "validate this IFC"
- Before any enrichment, classification, or COBie work
- As part of a DT readiness assessment

## Tools needed
This skill uses the `ifc-agent` MCP server tools. Ensure the MCP server is running.

## Workflow

### Step 1: Load the model
Call `load_model` with the file path to get a quick summary:
- Schema version (IFC2X3, IFC4, IFC4X3)
- Total entity count
- Element type breakdown

### Step 2: Run baseline check
Call `run_baseline_check` with the file path. This runs all 6 checks:

1. **Schema check** — Can the file be parsed? What IFC version?
2. **IDS check** — Do elements meet the baseline naming requirements?
3. **Spatial check** — Are all elements contained in a spatial structure?
4. **GUID check** — Are all GlobalIds unique?
5. **Proxy check** — How many IfcBuildingElementProxy elements exist?
6. **Type check** — Do all elements have type assignments?

### Step 3: Interpret results
For each check, report:
- ✓ PASS or ✗ FAIL
- Summary count (e.g., "12 orphan elements", "8 proxies")
- Top issues if any

### Step 4: Summarise for user
Format the response as:

```
🏗️ IFC Check Report: {filename}

Schema:   ✓ IFC4 — 2,847 entities
IDS:      ✓ 4/4 specs passed
Spatial:  ✗ 12 orphan elements
GUID:     ✓ All unique
Proxy:    ✗ 8 proxy elements (need reclassification)
Type:     ✗ 27 elements without type assignment

Overall: 3/6 passed | 47 issues
```

### Step 5: Recommend actions
Based on failures, suggest:
- **Orphan elements**: "These elements need to be assigned to a space or storey in the BIM authoring tool"
- **Proxies**: "These can be reclassified — shall I suggest correct IFC classes?"
- **Missing types**: "Type assignments improve FM handover quality"
- **GUID duplicates**: "Critical issue — duplicates cause data loss in federation"

## Priority of issues
1. 🔴 GUID duplicates (data integrity risk)
2. 🔴 Schema errors (file may be corrupt)
3. 🟡 Orphan elements (spatial structure incomplete)
4. 🟡 Missing types (FM readiness)
5. 🟠 Proxies (reclassification needed)
6. 🟢 IDS naming (cosmetic / compliance)

## HTML report
If the user wants a detailed report, call `run_baseline_check` with `output_format="html"`.
The HTML report will be saved to the reports/ directory.
