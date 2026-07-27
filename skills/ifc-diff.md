# IFC Model Diff — Compare Two IFC Versions

Compare two IFC files to identify what changed between revisions: added elements, deleted elements, property changes, reclassifications, and spatial moves.

## When to use
- User uploads a revised model and asks "what changed?"
- BIM coordinator needs a change log between CDE revisions
- QA audit before accepting a new model revision
- After a contractor updates their model — check for unintended changes
- "Show me the differences between model A and model B"

## Tools needed
This skill uses the `ifc-agent` MCP server tools:
- `load_model`
- `diff_ifc_files`
- `diff_element_properties`
- `get_entity_properties`

## Workflow

### Step 1: Load both models
Call `load_model` on both files to confirm they are valid and get a summary:
- Schema version
- Entity count
- Project names (should match for same project revisions)

### Step 2: Run the full diff
Call `diff_ifc_files(file_path_a, file_path_b)` where:
- `file_path_a` = original/baseline
- `file_path_b` = updated/revised

This returns:
- **Added**: elements in B but not A (new GlobalIds)
- **Deleted**: elements in A but not B (removed GlobalIds)
- **Modified**: shared GlobalIds where Name, IFC class, ObjectType, or description changed
- **Moved**: shared GlobalIds where the spatial container changed

### Step 3: Analyse the impact
Categorize changes by severity:
- 🔴 **Critical**: IFC class changes (reclassifications), GUID collisions, deletions of load-bearing elements
- 🟡 **Significant**: Spatial moves (element reassigned to different storey/space), large property changes
- 🟢 **Minor**: Name/description updates, new optional properties added

### Step 4: Deep-dive selected elements
For any critical or significant changes, call `diff_element_properties(file_a, file_b, global_id)` to see the full property-level comparison.

### Step 5: Report
Format the response as:

```
📊 IFC Change Report: {filename_a} → {filename_b}

Summary:
  Added:    {n} elements
  Deleted:  {n} elements
  Modified: {n} elements (property/name changes)
  Moved:    {n} elements (spatial reassignment)

Critical changes:
  - [GlobalId] IfcWall "Wall-001": reclassified from IfcBuildingElementProxy → IfcWall
  - [GlobalId] IfcBeam "Beam-003": deleted from Level 2

Significant changes:
  - [GlobalId] IfcPump "CHW Pump 01": moved from Ground Floor → Plant Room

Minor changes:
  - [n] elements: Description field updated
```

### Step 6: Recommend action
- If deletions are unexpected: flag for BIM coordinator review
- If reclassifications occurred: validate against IDS
- If spatial moves occurred: check spatial containment rules
- If new elements were added: run baseline check on new elements

## Priority of concerns
1. 🔴 IFC class changes (may break IDS validation, COBie mapping)
2. 🔴 Unexpected deletions
3. 🟡 Spatial moves (affect FM/COBie floor/space assignments)
4. 🟡 GUID changes (break federation links)
5. 🟢 Property additions/updates (usually positive)
