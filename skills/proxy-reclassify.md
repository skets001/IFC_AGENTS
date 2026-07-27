# Proxy Reclassification — Identify and Fix IfcBuildingElementProxy Elements

Find all IfcBuildingElementProxy elements in a model, infer their correct IFC class using LLM + bSDD, and apply reclassification with optional classification codes.

## When to use
- "Reclassify all proxies in this model"
- "These proxy elements need to be proper IFC classes"
- Model has IfcBuildingElementProxy elements from a CAD/BIM conversion
- Before IDS validation (proxies often fail class-based requirements)
- Preparing a model for FM handover (proxies won't map to COBie correctly)
- "What should these proxy elements really be?"

## Tools needed
- `get_proxies`
- `get_entity_properties`
- `bsdd_search_classes`
- `bsdd_get_class`
- `auto_classify_proxies`
- `reclassify_element`
- `add_classification_reference`
- `apply_patch_set`

## Workflow

### Step 1: Survey proxies
Call `get_proxies(file_path)` to get:
- Total proxy count
- Proxy elements grouped by ObjectType pattern
- Sample element names and descriptions

### Step 2: Group and infer classes
For each group of proxies with similar names/ObjectType:
1. Look at Name, Description, ObjectType
2. Search bSDD: `bsdd_search_classes(name_hint)`
3. Match to correct IFC class

Common proxy → IFC class mappings:
| Proxy Name Pattern | Target IFC Class |
|-------------------|-----------------|
| *pump*, *PUMP* | IfcPump |
| *fan*, *FAN*, *AHU* | IfcFan or IfcAirHandlingUnit |
| *valve*, *VALVE* | IfcValve |
| *sensor*, *SENSOR* | IfcSensor |
| *light*, *luminaire* | IfcLightFixture |
| *switch*, *outlet* | IfcSwitchingDevice or IfcOutlet |
| *boiler*, *heater* | IfcBoiler or IfcSpaceHeater |
| *chiller* | IfcChiller |
| *cooling tower* | IfcCoolingTower |

### Step 3: Auto-classify (LLM-assisted)
For bulk reclassification using LLM inference:
```
auto_classify_proxies(file_path, output_path)
```
This processes all proxies, infers classes, and creates a corrected IFC file.

Review the `predictions` in the result before accepting — the agent shows you what each proxy was inferred to be.

### Step 4: Manual reclassification for uncertain cases
For proxies where auto-classify is uncertain:
```
reclassify_element(
    file_path=...,
    global_id="...",
    new_ifc_class="IfcPump",
    new_name="CHW Pump 01",
    output_path=...
)
```

### Step 5: Add classification codes
After reclassification, add bSDD classification references:
```
bsdd_search_classes("pump", "https://identifier.buildingsmart.org/uri/nbs/uniclass2015/")
→ Find: Pr_70_65_64_86 — Pumps

add_classification_reference(
    file_path=...,
    global_ids=["guid1", "guid2"],
    classification_system="Uniclass 2015",
    identification="Pr_70_65_64_86",
    class_name="Pumps"
)
```

### Step 6: Validate
Run `run_specific_check(output_file, "proxy")` on the output to confirm proxy count reduced.

### Step 7: Report
```
🔄 Proxy Reclassification Report: {filename}

Proxies found: 23

Group analysis:
  "CHW Pump*" (6 elements) → IfcPump (confidence: high)
    bSDD: Uniclass Pr_70_65_64_86 — Pumps
  "AHU*", "Air Handler*" (4 elements) → IfcAirHandlingUnit (confidence: high)
    bSDD: Uniclass Pr_70_65_55_70 — Air handling units
  "LIGHT*" (8 elements) → IfcLightFixture (confidence: medium)
  "CUSTOM ELEMENT 01" (5 elements) → IfcBuildingElementProxy (uncertain — manual review needed)

Applied: 18 reclassifications
Pending manual review: 5 elements

Output: {output_path}
```

## Confidence levels
- **High**: Name/ObjectType directly matches an IFC class (e.g. "PUMP" → IfcPump)
- **Medium**: LLM inference from description + properties
- **Low/Uncertain**: Ambiguous or no useful metadata — flag for BIM team review

## Post-reclassification checklist
- [ ] Re-run baseline check (proxy count should decrease)
- [ ] Validate against IDS if class-based rules exist
- [ ] Add classification codes (Uniclass/OmniClass)
- [ ] Check that type assignments exist for new classes
- [ ] Verify COBie pset mapping works for new classes
