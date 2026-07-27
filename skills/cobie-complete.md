# COBie Completeness — FM Handover Readiness Check and Enrichment

Assess COBie (Construction Operations Building Information Exchange) completeness for FM handover, identify missing fields, and enrich the model with available data.

## When to use
- "Is this model ready for FM handover?"
- "Check COBie completeness for maintainable assets"
- "What data is missing for the facilities manager?"
- "Enrich the model with manufacturer and model numbers"
- Before generating a COBie spreadsheet export
- As part of a practical completion checklist

## Tools needed
- `get_entities`
- `get_entity_properties`
- `run_specific_check` (check_name="ids", with cobie_fm_handover.ids)
- `validate_ids_spec`
- `enrich_cobie_data`
- `add_or_update_pset`
- `apply_patch_set`
- `bsdd_search_classes`

## COBie Data Requirements

### Type-level (per asset type)
| Field | IFC Location | Required? |
|-------|-------------|----------|
| TypeName | IfcTypeObject.Name | ✓ Required |
| Category | IfcClassificationReference.Identification | ✓ Required |
| Description | IfcTypeObject.Description | ✓ Required |
| Manufacturer | Pset_ManufacturerTypeInformation.Manufacturer | ✓ Required |
| ModelNumber | Pset_ManufacturerTypeInformation.ModelLabel | ✓ Required |
| WarrantyGuaranteeDuration | Pset_Warranty.WarrantyPeriod | Recommended |
| ReplacementCost | Pset_EconomicImpactValues.ReplacementCost | Optional |

### Component-level (per asset instance)
| Field | IFC Location | Required? |
|-------|-------------|----------|
| Name | IfcElement.Name | ✓ Required |
| TypeName | IfcTypeObject.Name | ✓ Required |
| Space | IfcRelContainedInSpatialStructure | ✓ Required |
| TagNumber | Pset_ManufacturerOccurrence.TagNumber | ✓ Required |
| SerialNumber | Pset_ManufacturerOccurrence.SerialNumber | Recommended |
| InstallationDate | Pset_ManufacturerOccurrence.ManufactureDate | Recommended |

## Workflow

### Step 1: Run COBie IDS validation
```
validate_ids_spec(
    file_path=...,
    ids_path="rules/cobie_fm_handover.ids",
)
```
Get the list of all failing elements and which COBie fields are missing.

### Step 2: Categorise maintainable assets
Call `get_entities(file_path, "IfcFlowTerminal")` and similar MEP classes:
- IfcPump, IfcFan, IfcCompressor, IfcAirTerminal
- IfcFlowTerminal, IfcUnitaryEquipment
- IfcCommunicationsAppliance, IfcElectricAppliance
- IfcFireSuppressionTerminal, IfcSanitaryTerminal

For each, check Pset_ManufacturerTypeInformation is present.

### Step 3: Identify data gaps
For each maintainable element group, check:
- Is Manufacturer populated? (most critical)
- Is ModelNumber populated?
- Is the element in a Space? (not just a Storey)
- Is TagNumber assigned?
- Does the element have a Type object?

### Step 4: Enrich available data
For bulk enrichment via LLM:
```
enrich_cobie_data(file_path, output_path)
```
This harvests incomplete elements, uses LLM to infer Manufacturer/Model where the element Name suggests a real product, and injects the values.

For manual/known data, use `apply_patch_set`:
```json
[
  {
    "operation": "set_property",
    "global_id": "...",
    "pset": "Pset_ManufacturerTypeInformation",
    "prop": "Manufacturer",
    "value": "Grundfos"
  }
]
```

### Step 5: Validate again
Re-run `validate_ids_spec` to confirm improvement.

### Step 6: Report
```
📦 COBie Completeness Report: {filename}

Maintainable assets analysed: 87

Field completeness:
  TypeName:        87/87 ✓ (100%)
  Category:        62/87 ✗ (71%) — 25 elements missing classification
  Manufacturer:    43/87 ✗ (49%) — 44 elements missing
  ModelNumber:     38/87 ✗ (44%) — 49 elements missing
  Space assignment: 81/87 ✗ (93%) — 6 elements not in a space
  TagNumber:       12/87 ✗ (14%) — 75 elements missing

COBie handover readiness: 62% — Enrichment required

After enrichment (enrich_cobie_data):
  Manufacturer: +28 inferred from element names
  ModelNumber: +22 inferred from element names

Remaining gaps (require manual data from contractor):
  - 16 elements: Manufacturer unknown
  - 27 elements: ModelNumber unknown
  - 75 elements: TagNumber (must come from installer)
```

## Handover readiness thresholds
- 🔴 < 50%: Not ready — critical data missing
- 🟡 50–80%: Partial — enrichment work needed
- 🟢 > 80%: Good — minor gaps only
- ✓ 100%: Full COBie compliance
