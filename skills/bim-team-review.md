# BIM Team Review — Full Project Quality Review and Correction Plan

A comprehensive multi-agent BIM review that checks model quality, validates against standards, compares revisions, and produces a prioritized correction plan with actionable patches.

## When to use
- "Review this model and tell me what needs fixing"
- "Prepare a BIM quality report for the client"
- "Check if this model is ready for COBie handover"
- "Run the full BIM team review"
- Before a data drop milestone (design freeze, tender, handover)
- When onboarding a new subcontractor model

## Tools needed
This skill uses all `ifc-agent` MCP server tools across multiple passes:
- `load_model`, `get_spatial_tree`
- `run_baseline_check`
- `get_proxies`, `get_orphan_elements`
- `list_ids_specs`, `validate_ids_spec`
- `bsdd_search_classes`, `bsdd_validate_element_classification`
- `get_entities`, `get_entity_properties`
- `diff_ifc_files` (if previous version available)

## Workflow

### Pass 1: Model Overview (ifc_parser)
1. `load_model(file_path)` — schema, entity count, project info
2. `get_spatial_tree(file_path)` — check spatial hierarchy completeness

Flag:
- Missing site/building/storey structure
- Unexpectedly high entity count (possible duplicates)
- Wrong schema version for project requirements

### Pass 2: Baseline Quality Check (ifc_parser + ids_manager)
1. `run_baseline_check(file_path)` — all 6 checks
2. For IDS failures: `validate_ids_spec(file_path, "rules/cobie_fm_handover.ids")`

Categorise all issues:
- 🔴 Data integrity (GUID duplicates, schema errors)
- 🟡 Completeness (orphan elements, missing types, proxies)
- 🟢 Compliance (IDS naming, COBie properties)

### Pass 3: Classification Review (asset_intel + bsdd)
1. `get_proxies(file_path)` — list all proxies needing reclassification
2. For each proxy type group, `bsdd_search_classes(name)` to find correct IFC class
3. Spot-check existing classifications: `bsdd_validate_element_classification` on sample elements

### Pass 4: COBie/FM Readiness (cobie_manager)
1. Check for Manufacturer, ModelNumber, SerialNumber on maintainable elements
2. Identify elements missing Pset_ManufacturerTypeInformation
3. Check IfcSystem/zone assignments for MEP elements

### Pass 5: Change Detection (if previous version available)
1. `diff_ifc_files(baseline_file, current_file)` — identify all changes
2. Flag any unexpected deletions or class changes
3. Note new elements that need QA

### Pass 6: Produce Correction Plan
Aggregate all findings into a prioritized correction plan:

```
🏗️ BIM Team Review: {project_name}
Model: {filename}
Date: {date}
Reviewer: Hermes BIM Intelligence Agent

═══════════════════════════════════════
EXECUTIVE SUMMARY
═══════════════════════════════════════
Overall readiness: 62% — Not ready for handover

Schema:    ✓ IFC4 — 2,847 entities
Spatial:   ✗ 12 orphan elements (Level 1)
GUIDs:     ✗ 3 duplicates
Proxies:   ✗ 8 elements need reclassification
Types:     ✗ 27 without type assignment
IDS:       ✗ 18 COBie failures
bSDD:      ⚠ 24 elements with no classification

═══════════════════════════════════════
CRITICAL ISSUES (fix before milestone)
═══════════════════════════════════════
1. 3 GUID duplicates → run fix_guid_duplicates
   Affected: [GlobalId1], [GlobalId2], [GlobalId3]

2. 12 orphan elements (not in any storey)
   Action: assign_to_spatial_container to Level 1
   Elements: [list of GlobalIds]

═══════════════════════════════════════
SIGNIFICANT ISSUES (fix before handover)
═══════════════════════════════════════
3. 8 proxy elements requiring reclassification:
   - "CHW Pump-01" → IfcPump (confidence: high)
   - "AHU B1" → IfcAirHandlingUnit (confidence: high)
   Action: auto_classify_proxies

4. 27 elements without type assignments
   Action: Add type relationships in BIM authoring tool

═══════════════════════════════════════
COMPLIANCE ISSUES (fix before COBie export)
═══════════════════════════════════════
5. 18 elements missing Manufacturer/Model in Pset_ManufacturerTypeInformation
   Action: enrich_cobie_data or manual data entry

6. 24 elements with no classification reference
   Action: bsdd_search_classes + add_classification_reference

═══════════════════════════════════════
RECOMMENDED PATCH SEQUENCE
═══════════════════════════════════════
Step 1: fix_guid_duplicates → model_guid_fixed.ifc
Step 2: assign_to_spatial_container (12 elements) → model_spatial_fixed.ifc
Step 3: auto_classify_proxies → model_classified.ifc
Step 4: enrich_cobie_data → model_cobie_enriched.ifc
Step 5: Re-run baseline_check → confirm all critical issues resolved
```

## Agent handoff protocol
- **ifc_parser**: schema, spatial, GUIDs, types, proxies
- **ids_manager**: IDS validation failures, spec gaps
- **bep_generator**: BEP/EIR clause gaps based on evidence
- **cobie_manager**: COBie completeness, FM readiness
- **asset_intel**: Maintainable asset identification, lifecycle gaps

## Output artifacts
- `reports/{model_stem}_bim_review.html` — full HTML report
- `reports/{model_stem}_correction_plan.json` — machine-readable plan
- Corrected IFC file path (if patches were applied)
