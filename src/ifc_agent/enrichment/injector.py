"""Provides mutation interfaces utilizing ifcopenshell API algorithms to graft required parameters without breaking file relationships."""

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element
from pathlib import Path

from ifc_agent.ifc_utils import by_guid

def evaluate_and_inject(file_path: str | Path, injection_map: dict[str, dict], output_path: str | Path | None = None) -> dict:
    """Safely apply a map of parsed parameters into target property sets safely across the IFC graph.
    
    Args:
        file_path: Origin file
        injection_map: Mapping of GlobalId -> extracted properties dictionaries.
        output_path: Destination path
    """
    file_path = Path(file_path)
    model = ifcopenshell.open(str(file_path))
    
    mutated_count = 0
    props_added = 0
    
    for global_id, properties in injection_map.items():
        if not any(properties.values()):
            continue  # Empty extraction implies no implicit parameters existed 
            
        element = by_guid(model, global_id)
        if not element:
            continue
            
        # Clean null values
        clean_props = {k: str(v) for k, v in properties.items() if v is not None}
        if not clean_props:
            continue
            
        # Determine if Pset_ManufacturerTypeInformation already exists
        target_pset_name = "Pset_ManufacturerTypeInformation"
        
        pset_element = None
        for rel in getattr(element, "IsDefinedBy", []):
            if rel.is_a("IfcRelDefinesByProperties"):
                prop_def = rel.RelatingPropertyDefinition
                if prop_def.is_a("IfcPropertySet") and prop_def.Name == target_pset_name:
                    pset_element = prop_def
                    break
        
        if not pset_element:
            # Create standard Pset if absent
            pset_element = ifcopenshell.api.run("pset.add_pset", model, product=element, name=target_pset_name)
            
        # Push properties deterministically
        ifcopenshell.api.run("pset.edit_pset", model, pset=pset_element, properties=clean_props)
        mutated_count += 1
        props_added += len(clean_props)
        
    if not output_path:
        stem = file_path.stem
        output_path = file_path.parent / f"{stem}_enriched.ifc"
        
    model.write(str(output_path))
    return {
        "elements_mutated": mutated_count, 
        "properties_added": props_added,
        "output_path": str(output_path)
    }
