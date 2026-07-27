# IDS Requirements Workflow — Create, Validate, and Manage IDS Specifications

Author, validate, and manage IDS (Information Delivery Specification) files. Check models against existing IDS specs, identify gaps, and generate new specs from observed model patterns.

## When to use
- "Validate this model against our IDS requirements"
- "Create an IDS file from what we see in the model"
- "List all requirements in the baseline.ids file"
- "Which elements are failing the COBie handover spec?"
- "Generate IDS requirements for walls and doors"
- After a BEP is parsed — compile it to IDS
- Before model sign-off — validate all IDS specs pass

## Tools needed
This skill uses the `ifc-agent` MCP server tools:
- `list_ids_specs`
- `validate_ids_spec`
- `run_specific_check` (with check_name="ids")
- `create_ids_from_model`
- `extract_bep_rules`
- `compile_bep_yaml_to_ids`
- `get_entities`
- `get_entity_properties`

## Workflow

### Scenario A: Validate against existing IDS

1. **List specs**: `list_ids_specs(ids_path)` to see all specifications and their requirements.

2. **Run validation**: 
   - Full IDS file: `run_specific_check(file_path, "ids", ids_path=ids_path)`
   - Single spec: `validate_ids_spec(file_path, ids_path, spec_name="Spec Name")`

3. **Analyse failures**: For each failed spec, report:
   - How many elements are applicable
   - How many failed
   - The first 10 failed GlobalIds with their names and IFC classes

4. **Prioritise**: Sort failures by:
   - 🔴 Critical: elements with no name, wrong class, missing required pset
   - 🟡 Significant: missing recommended properties
   - 🟢 Minor: non-mandatory requirements

5. **Report**:
```
📋 IDS Validation: {ids_path}

Spec: Wall Naming Requirements
  ✓ 45/45 applicable elements passed

Spec: COBie Type Information
  ✗ 18/32 applicable elements FAILED
  Failed elements:
    - [GlobalId] IfcPump "CHW Pump 01" — Missing Pset_ManufacturerTypeInformation
    - [GlobalId] IfcAirTerminal "AHU-B1" — Missing Pset_ManufacturerTypeInformation
    ...

Overall: 1/2 specs passed | 18 issues to resolve
```

### Scenario B: Create IDS from model patterns

1. **Analyse model**: `load_model(file_path)` to see what's in the model.

2. **Generate starter IDS**:
```
create_ids_from_model(
    file_path=...,
    output_ids_path="rules/auto_generated.ids",
    title="Auto-Generated Model Requirements",
    ifc_classes=["IfcWall", "IfcDoor", "IfcWindow", "IfcSlab"],
    required_psets=["Pset_WallCommon", "Pset_DoorCommon"]
)
```

3. **Review and refine**: List the generated specs with `list_ids_specs`.

4. **Validate**: Run `validate_ids_spec` on the model to see current compliance.

### Scenario C: BEP → IDS pipeline

1. **Extract rules from BEP**: `extract_bep_rules(bep_path, "rules/extracted.yaml")`
2. **Compile to IDS**: `compile_bep_yaml_to_ids("rules/extracted.yaml", "rules/from_bep.ids")`
3. **Validate model**: `run_specific_check(file_path, "ids", ids_path="rules/from_bep.ids")`

## IDS file locations
Standard IDS files in this project:
- `rules/baseline.ids` — Basic naming requirements
- `rules/cobie_fm_handover.ids` — COBie/FM handover specification

## Spec authoring guidance
A good IDS spec has:
- Clear name describing the requirement
- Applicability: IFC class + optional property filter
- Requirements: specific property sets and property names
- Cardinality: required vs. optional
- Appropriate minOccurs/maxOccurs
