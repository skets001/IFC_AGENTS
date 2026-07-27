"""Harvester for fetching context to feed deductive LLM processes."""

import ifcopenshell
import ifcopenshell.util.element

def harvest_metadata(model: ifcopenshell.file) -> list[dict]:
    """Retrieve raw context from key physical elements (avoiding base structural elements where COBie isn't needed usually)."""
    # Restrict to Mechanical, Plumbing, Electrical, Equipment, Furniture...
    target_classes = [
        "IfcFan", "IfcPump", "IfcBoiler", "IfcChiller", 
        "IfcFlowTerminal", "IfcUnitaryEquipment", "IfcDistributionControlElement",
        "IfcFurnishingElement"
    ]
    
    results = []
    
    for cls in target_classes:
        elements = model.by_type(cls)
        for e in elements:
            # We skip elements that already have complete Manufacturer Psets
            psets = ifcopenshell.util.element.get_psets(e)
            mfg_pset = psets.get("Pset_ManufacturerTypeInformation", {})
            if mfg_pset.get("Manufacturer") and mfg_pset.get("ModelReference"):
                continue  # Already clean!
                
            data = {
                "global_id": getattr(e, "GlobalId", ""),
                "ifc_class": e.is_a(),
                "name": getattr(e, "Name", ""),
                "description": getattr(e, "Description", ""),
                "object_type": getattr(e, "ObjectType", ""),
                "existing_psets": psets
            }
            results.append(data)
            
    return results
