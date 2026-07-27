"""Small IfcOpenShell compatibility helpers."""

from __future__ import annotations


def by_guid(model, global_id: str):
    """Return an IFC root entity by GlobalId across IfcOpenShell versions."""
    if not global_id:
        return None
    if hasattr(model, "by_guid"):
        return model.by_guid(global_id)
    for entity in model.by_type("IfcRoot"):
        if getattr(entity, "GlobalId", None) == global_id:
            return entity
    return None
