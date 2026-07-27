"""IFC model metadata and element indexing utilities."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element

from ifc_agent.validation_store import ValidationStore, model_id_for_path


def index_ifc_file(file_path: str | Path, store: ValidationStore) -> dict[str, Any]:
    path = Path(file_path)
    model = ifcopenshell.open(str(path))
    metadata = extract_model_metadata(path, model)
    elements = list(extract_element_index(model))
    metadata["element_count"] = len(elements)
    metadata["indexed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    model_id = store.upsert_model(metadata)
    element_count = store.replace_elements(model_id, elements)
    return {"model_id": model_id, "file_path": str(path), "metadata": metadata, "element_count": element_count}


def extract_model_metadata(path: Path, model: ifcopenshell.file) -> dict[str, Any]:
    projects = model.by_type("IfcProject")
    sites = model.by_type("IfcSite")
    buildings = model.by_type("IfcBuilding")
    return {
        "model_id": model_id_for_path(path),
        "file_path": str(path),
        "file_name": path.name,
        "file_size": path.stat().st_size if path.exists() else None,
        "file_mtime": int(path.stat().st_mtime * 1000) if path.exists() else None,
        "schema": model.schema,
        "project_name": getattr(projects[0], "Name", None) if projects else None,
        "site_name": getattr(sites[0], "Name", None) if sites else None,
        "building_name": getattr(buildings[0], "Name", None) if buildings else None,
        "entity_count": len(list(model)),
    }


def extract_element_index(model: ifcopenshell.file):
    seen: set[int] = set()
    for ifc_class in ["IfcElement", "IfcSpatialElement", "IfcProject", "IfcTypeObject", "IfcSystem", "IfcZone"]:
        try:
            entities = model.by_type(ifc_class)
        except Exception:
            entities = []
        for entity in entities:
            if entity.id() in seen or not getattr(entity, "GlobalId", None):
                continue
            seen.add(entity.id())
            yield _index_entity(entity)


def _index_entity(entity) -> dict[str, Any]:
    element_type = _safe_type(entity)
    storey = _safe_container(entity, "IfcBuildingStorey")
    space = _safe_container(entity, "IfcSpace")
    return {
        "global_id": getattr(entity, "GlobalId", None),
        "ifc_id": entity.id(),
        "ifc_class": entity.is_a(),
        "name": getattr(entity, "Name", None),
        "tag": getattr(entity, "Tag", None),
        "object_type": getattr(entity, "ObjectType", None),
        "predefined_type": ifcopenshell.util.element.get_predefined_type(entity),
        "type_global_id": getattr(element_type, "GlobalId", None) if element_type else None,
        "type_name": getattr(element_type, "Name", None) if element_type else None,
        "storey": getattr(storey, "Name", None) if storey else None,
        "space": getattr(space, "Name", None) if space else None,
        "systems": _systems(entity),
        "classifications": _classifications(entity),
        "documents": _documents(entity),
        "property_sets": _psets_with_values(entity),
        "relationships": {
            "type": _summary(element_type),
            "storey": _summary(storey),
            "space": _summary(space),
            "container": _summary(_safe_container(entity, None)),
        },
    }


def _safe_type(entity):
    try:
        return ifcopenshell.util.element.get_type(entity)
    except Exception:
        return None


def _safe_container(entity, ifc_class: str | None):
    try:
        return ifcopenshell.util.element.get_container(entity, ifc_class=ifc_class)
    except Exception:
        return None


def _psets_with_values(entity) -> dict[str, Any]:
    try:
        return ifcopenshell.util.element.get_psets(entity)
    except Exception:
        return {}


def _classifications(entity) -> list[dict[str, Any]]:
    try:
        import ifcopenshell.util.classification as classification_util
        references = classification_util.get_references(entity) or []
    except Exception:
        references = []
        classification_util = None
    rows = []
    for ref in references:
        classification = None
        if classification_util is not None:
            try:
                classification = classification_util.get_classification(ref)
            except Exception:
                classification = None
        rows.append(
            {
                "identification": getattr(ref, "Identification", None) or getattr(ref, "ItemReference", None),
                "name": getattr(ref, "Name", None),
                "location": getattr(ref, "Location", None),
                "source_name": getattr(classification, "Name", None) if classification else None,
                "source_location": getattr(classification, "Location", None) if classification else None,
            }
        )
    return rows


def _systems(entity) -> list[dict[str, Any]]:
    rows = []
    for rel in getattr(entity, "HasAssignments", []) or []:
        if not rel.is_a("IfcRelAssignsToGroup"):
            continue
        group = getattr(rel, "RelatingGroup", None)
        if group and (group.is_a("IfcSystem") or group.is_a("IfcZone") or group.is_a("IfcGroup")):
            rows.append(_summary(group))
    return [row for row in rows if row]


def _documents(entity) -> list[dict[str, Any]]:
    rows = []
    for rel in getattr(entity, "HasAssociations", []) or []:
        if not rel.is_a("IfcRelAssociatesDocument"):
            continue
        document = getattr(rel, "RelatingDocument", None)
        rows.append(_summary(document))
    return [row for row in rows if row]


def _summary(entity) -> dict[str, Any] | None:
    if entity is None:
        return None
    return {
        "global_id": getattr(entity, "GlobalId", None),
        "ifc_class": entity.is_a(),
        "name": getattr(entity, "Name", None),
        "id": entity.id(),
    }
