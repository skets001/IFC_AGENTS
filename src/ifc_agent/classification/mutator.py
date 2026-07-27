"""Mutates the IFC graph safely by reassigning classes."""

import logging

import ifcopenshell
import ifcopenshell.api
from pathlib import Path

from ifc_agent.ifc_utils import by_guid

logger = logging.getLogger(__name__)


def classify_and_mutate(file_path: str | Path, classifications: dict[str, str], output_path: str | Path | None = None) -> dict:
    """Takes a dictionary mapping GlobalId to new IfcClass and safely mutates the model.
    
    Args:
        file_path: The source IFC file to open.
        classifications: Dict mapping global_id to standard IfcClass (e.g. {'3bClayEqP40OVHuvRNzi45': 'IfcColumn'}).
        output_path: Destination path for the corrected model. If None, saves next to original with `_classified` suffix.
    """
    file_path = Path(file_path)
    model = ifcopenshell.open(str(file_path))
    
    mutated_count = 0
    for global_id, new_class in classifications.items():
        if new_class == "IfcBuildingElementProxy":
            continue # Needs no change

        element = by_guid(model, global_id)
        if element:
            # We use ifcopenshell API to safely transition the element's entity type
            # while maintaining all its relational graph limits, properties, and placements.
            try:
                ifcopenshell.api.run("root.reassign_class", model, product=element, ifc_class=new_class)
                mutated_count += 1
            except Exception as e:
                logger.warning("Failed to reassign %s to %s: %s", global_id, new_class, e)
                
    if not output_path:
        stem = file_path.stem
        output_path = file_path.parent / f"{stem}_classified.ifc"
        
    model.write(str(output_path))
    return {"mutated_count": mutated_count, "output_path": str(output_path)}
