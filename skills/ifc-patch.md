# IFC Model Patch — Apply Corrections to an IFC File

Systematically identify issues in an IFC file and apply structured corrections: fix GUID duplicates, update names, set properties, move elements to correct spatial containers, and add classification references.

## When to use
- User asks "fix the issues in this model"
- After a baseline check reveals fixable problems
- Bulk property updates needed (e.g. set Manufacturer for all pumps)
- Orphan elements need to be assigned to storeys
- GUID duplicates detected and need to be resolved
- "Apply these corrections to the model"
- Before COBie export — patch missing required fields

## Tools needed
This skill uses the `ifc-agent` MCP server tools:
- `run_baseline_check`
- `get_orphan_elements`
- `get_entities`
- `get_entity_properties`
- `get_spatial_tree`
- `fix_guid_duplicates`
- `reclassify_element`
- `add_or_update_pset`
- `assign_to_spatial_container`
- `add_classification_reference`
- `apply_patch_set`

## Workflow

### Step 1: Diagnose issues
Call `run_baseline_check(file_path)` to get a full issue list.
For orphan elements specifically: `get_orphan_elements(file_path)`.

Categorise issues into fixable categories:
- GUID duplicates → use `fix_guid_duplicates`
- Orphan elements → use `assign_to_spatial_container` after calling `get_spatial_tree` to find the right container
- Proxy elements that should be reclassified → use `reclassify_element`
- Missing properties → use `add_or_update_pset`
- Missing classification → use `add_classification_reference`

### Step 2: Plan the patch batch
For multiple changes to the same file, use `apply_patch_set` to apply all patches in one operation.

Example patch set:
```json
[
  {"operation": "set_name", "global_id": "abc123", "name": "CHW Pump 01"},
  {"operation": "set_property", "global_id": "abc123", "pset": "Pset_ManufacturerTypeInformation", "prop": "Manufacturer", "value": "Grundfos"},
  {"operation": "add_classification", "global_id": "abc123", "system": "Uniclass 2015", "identification": "Pr_70_65_64_86", "name": "Pumps"}
]
```

### Step 3: Fix GUID duplicates first
If GUID duplicates exist, call `fix_guid_duplicates(file_path)` BEFORE other patches.
Always work on the output file from this step for subsequent patches.

### Step 4: Fix orphan elements
Call `get_spatial_tree(file_path)` to get storey GlobalIds.
For each orphan, call `assign_to_spatial_container(file_path, element_global_id, storey_global_id)`.

### Step 5: Apply property and classification patches
Use `apply_patch_set` for bulk updates. Keep patch operations atomic — if one fails, others still apply.

### Step 6: Validate the patched file
Run `run_baseline_check` on the output file to confirm issues are resolved.

### Step 7: Report
```
🔧 IFC Patch Report: {filename}

Fixes applied:
  ✓ 3 duplicate GUIDs fixed → new_file_guid_fixed.ifc
  ✓ 12 orphan elements assigned to Level 1
  ✓ 8 proxies reclassified (IfcPump: 3, IfcAirTerminal: 5)
  ✓ 24 elements — Manufacturer property added to Pset_ManufacturerTypeInformation
  ✗ 2 elements — container assignment failed (no matching storey found)

Output file: {output_path}

Remaining issues: {n} (require manual BIM authoring tool fix)
```

## Rules
- Never overwrite the original file — always use output_path
- Report both successes and failures with GlobalIds
- If a fix requires human judgment (e.g. which storey an element belongs to), flag it
- GUID fixes must be done before any other patches to avoid operating on stale GlobalIds
