"""Extract metadata from Proxy elements to prepare for AI classification."""

import ifcopenshell
import ifcopenshell.util.element

def extract_proxies(model: ifcopenshell.file) -> list[dict]:
    """Find all IfcBuildingElementProxy objects and extract their metadata."""
    proxies = model.by_type("IfcBuildingElementProxy")
    results = []

    for p in proxies:
        obj_data = {
            "global_id": getattr(p, "GlobalId", ""),
            "name": getattr(p, "Name", ""),
            "description": getattr(p, "Description", ""),
            "object_type": getattr(p, "ObjectType", ""),
            "properties": {}
        }
        
        # Extract properties
        psets = ifcopenshell.util.element.get_psets(p)
        for pset_name, properties in psets.items():
            if isinstance(properties, dict):
                # Filter out pure id properties or None
                clean_props = {k: v for k, v in properties.items() if v is not None}
                obj_data["properties"][pset_name] = clean_props

        results.append(obj_data)

    return results
