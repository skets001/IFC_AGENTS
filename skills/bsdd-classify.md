# bSDD Classification — Look Up and Apply buildingSMART Classifications

Search the buildingSMART Data Dictionary (bSDD) to find correct classifications for IFC elements, validate existing classifications, and apply classification references to model elements.

## When to use
- User asks "classify these elements using Uniclass / OmniClass / NBS"
- Proxy elements need to be assigned a classification code before reclassification
- Validating that existing classification references are recognized by bSDD
- "What is the Uniclass code for a chilled water pump?"
- "Check if all elements have valid bSDD classification references"
- After proxy reclassification — add standard classification codes

## Tools needed
This skill uses the `ifc-agent` MCP server tools:
- `bsdd_list_dictionaries`
- `bsdd_search_classes`
- `bsdd_get_class`
- `bsdd_validate_element_classification`
- `get_entities`
- `get_entity_properties`
- `add_classification_reference`
- `apply_patch_set`

## Workflow

### Step 1: Identify what needs classifying
- If user specifies a query: search bSDD directly with `bsdd_search_classes(query)`
- If user wants to classify elements in a model: call `get_entities(file_path, ifc_class)` for the relevant classes
- To validate existing classifications: call `bsdd_validate_element_classification(file_path, global_id)` per element

### Step 2: Find the right dictionary
Call `bsdd_list_dictionaries()` if the user hasn't specified a dictionary.
Common choices:
- Uniclass 2015 (UK/international)
- OmniClass (US)
- IFC 4.3 (buildingSMART native)
- NBS (UK specification)

### Step 3: Search for the class
Call `bsdd_search_classes(query, dictionary_uri)`.
- Try broad terms first: "pump", "door", "wall"
- Then narrow: "centrifugal pump", "fire door", "curtain wall"
- Return top 5 candidates with URI, name, and code

### Step 4: Get class details
For the best match, call `bsdd_get_class(class_uri)` to see:
- Full name and definition
- Required and optional properties
- Related IFC entity types

### Step 5: Apply classifications
For each element to classify:
```
add_classification_reference(
    file_path=...,
    global_ids=[...],
    classification_system="Uniclass 2015",
    identification="Pr_70_65_64_86",
    class_name="Pumps",
    output_path=...
)
```

Or use `apply_patch_set` for bulk classification:
```json
[
  {"operation": "add_classification", "global_id": "...", "system": "Uniclass 2015", "identification": "Pr_70_65_64_86", "name": "Pumps"}
]
```

### Step 6: Validate
Re-check with `bsdd_validate_element_classification` to confirm references are now recognized.

### Step 7: Report
```
🏷️ bSDD Classification Report

Dictionary: Uniclass 2015
Query: "pump"

Found: Pr_70_65_64_86 — Pumps
  URI: https://identifier.buildingsmart.org/uri/nbs/uniclass2015/...
  Required properties: FlowRate, PowerInput, Efficiency

Applied to 8 elements:
  ✓ IfcPump "CHW Pump 01" [GlobalId] → Pr_70_65_64_86 Pumps
  ✓ IfcPump "HHW Pump 02" [GlobalId] → Pr_70_65_64_86 Pumps
  ...

Output: {output_path}
```

## Common bSDD dictionaries and URIs
- Uniclass 2015: `https://identifier.buildingsmart.org/uri/nbs/uniclass2015/`
- IFC 4.3: `https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3`
- OmniClass: `https://identifier.buildingsmart.org/uri/csi/omniclass/`
