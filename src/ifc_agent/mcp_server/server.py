"""IFC MCP Server — FastMCP server exposing IFC query + checker + mutation tools.

Full BIM team capability:
  - Query: load, get entities, properties, spatial containment, search
  - Check: baseline 6-check suite, per-check, IDS per-spec
  - Diff: compare two IFC files by GUID, class, properties, spatial structure
  - Patch: fix GUIDs, reclassify elements, add/update Psets, move to spatial container
  - bSDD: search dictionary, lookup class properties, validate classification
  - IDS: create spec, list specs, validate against spec, add requirements
  - COBie: harvest, enrich, inject FM properties
  - BEP: parse PDF/DOCX, compile to IDS
  - Classify: auto-classify proxies via LLM + bSDD cross-check

Start with:
    python -m ifc_agent.mcp_server.server
    # or: ifc-agent serve
"""

import json
import os
import time
import urllib.request
import urllib.parse
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.util.selector

from fastmcp import FastMCP

from ifc_agent.checker.runner import run_all
from ifc_agent.checker import report as report_module
from ifc_agent.anonymiser.strip import extract_safe_metadata, strip_personal_fields
from ifc_agent.ifc_utils import by_guid

mcp = FastMCP(name="ifc-agent")

# ── Model cache ──────────────────────────────────────────────────────────────
_model_cache: OrderedDict[str, ifcopenshell.file] = OrderedDict()
_MODEL_CACHE_SIZE = max(1, int(os.environ.get("IFC_AGENT_MCP_MODEL_CACHE_SIZE", "3")))


def _get_model(file_path: str) -> ifcopenshell.file:
    key = str(Path(file_path).resolve()) if Path(file_path).exists() else str(file_path)
    if key in _model_cache:
        _model_cache.move_to_end(key)
        return _model_cache[key]
    model = ifcopenshell.open(file_path)
    _model_cache[key] = model
    _model_cache.move_to_end(key)
    while len(_model_cache) > _MODEL_CACHE_SIZE:
        _model_cache.popitem(last=False)
    return model


def _invalidate_cache(file_path: str) -> None:
    key = str(Path(file_path).resolve()) if Path(file_path).exists() else str(file_path)
    _model_cache.pop(key, None)


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def load_model(file_path: str) -> str:
    """Load an IFC file and return a summary of its contents.

    Args:
        file_path: Absolute path to the IFC file.

    Returns:
        JSON with schema, entity count, project name, and type counts.
    """
    model = _get_model(file_path)
    type_counts = {}
    for type_name in [
        "IfcWall", "IfcDoor", "IfcWindow", "IfcSlab", "IfcColumn", "IfcBeam",
        "IfcSpace", "IfcStairFlight", "IfcRoof", "IfcBuildingElementProxy",
        "IfcFurnishingElement", "IfcFlowTerminal", "IfcUnitaryEquipment",
        "IfcPump", "IfcAirTerminal", "IfcCovering", "IfcRailing",
        "IfcMember", "IfcPlate", "IfcPipeSegment", "IfcDuctSegment",
    ]:
        count = len(model.by_type(type_name))
        if count:
            type_counts[type_name] = count

    projects = model.by_type("IfcProject")
    project_name = projects[0].Name if projects else "unknown"
    sites = model.by_type("IfcSite")
    buildings = model.by_type("IfcBuilding")
    storeys = model.by_type("IfcBuildingStorey")

    return json.dumps({
        "file_path": file_path,
        "schema": model.schema,
        "entity_count": len(list(model)),
        "project_name": project_name,
        "sites": len(sites),
        "buildings": len(buildings),
        "storeys": len(storeys),
        "type_counts": type_counts,
    }, indent=2)


@mcp.tool()
def get_entities(file_path: str, ifc_class: str) -> str:
    """Get all entities of a given IFC class.

    Args:
        file_path: Path to the IFC file.
        ifc_class: IFC class name (e.g. 'IfcWall', 'IfcDoor').

    Returns:
        JSON list with GlobalId, Name, Description, ObjectType per entity.
    """
    model = _get_model(file_path)
    result = [
        {
            "global_id": getattr(e, "GlobalId", None),
            "name": getattr(e, "Name", None),
            "description": getattr(e, "Description", None),
            "ifc_class": e.is_a(),
            "object_type": getattr(e, "ObjectType", None),
        }
        for e in model.by_type(ifc_class)
    ]
    return json.dumps(result, indent=2)


@mcp.tool()
def get_entity_properties(file_path: str, global_id: str) -> str:
    """Get all properties, property sets, type info, and container for an entity.

    Args:
        file_path: Path to the IFC file.
        global_id: The GlobalId of the entity.

    Returns:
        JSON with all property sets, type, and spatial container.
    """
    model = _get_model(file_path)
    entity = by_guid(model, global_id)
    if entity is None:
        return json.dumps({"error": f"Entity {global_id} not found"})

    try:
        psets = ifcopenshell.util.element.get_psets(entity)
    except Exception:
        psets = {}

    try:
        element_type = ifcopenshell.util.element.get_type(entity)
        type_info = {
            "type_name": getattr(element_type, "Name", None),
            "type_class": element_type.is_a() if element_type else None,
            "type_global_id": getattr(element_type, "GlobalId", None),
        }
    except Exception:
        type_info = None

    try:
        container = ifcopenshell.util.element.get_container(entity)
        container_info = {
            "name": getattr(container, "Name", None),
            "class": container.is_a() if container else None,
            "global_id": getattr(container, "GlobalId", None),
        }
    except Exception:
        container_info = None

    # Classification references
    classifications = []
    try:
        for rel in getattr(entity, "HasAssociations", []):
            if rel.is_a("IfcRelAssociatesClassification"):
                ref = rel.RelatingClassification
                classifications.append({
                    "identification": getattr(ref, "Identification", None),
                    "name": getattr(ref, "Name", None),
                    "system": getattr(getattr(ref, "ReferencedSource", None), "Name", None),
                })
    except Exception:
        pass

    return json.dumps({
        "global_id": global_id,
        "name": getattr(entity, "Name", None),
        "description": getattr(entity, "Description", None),
        "ifc_class": entity.is_a(),
        "object_type": getattr(entity, "ObjectType", None),
        "property_sets": psets,
        "type_info": type_info,
        "container": container_info,
        "classifications": classifications,
    }, indent=2, default=str)


@mcp.tool()
def get_entities_in_spatial(file_path: str, spatial_global_id: str) -> str:
    """Get all entities contained within a spatial element (room, storey, building).

    Args:
        file_path: Path to the IFC file.
        spatial_global_id: GlobalId of the spatial element.

    Returns:
        JSON list of contained entities.
    """
    model = _get_model(file_path)
    spatial = by_guid(model, spatial_global_id)
    if spatial is None:
        return json.dumps({"error": f"Spatial element {spatial_global_id} not found"})

    result = []
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        if rel.RelatingStructure == spatial:
            for element in rel.RelatedElements:
                result.append({
                    "global_id": element.GlobalId,
                    "name": getattr(element, "Name", None),
                    "ifc_class": element.is_a(),
                })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_spatial_tree(file_path: str) -> str:
    """Return the full spatial hierarchy (Site > Building > Storey > Space).

    Args:
        file_path: Path to the IFC file.

    Returns:
        JSON tree of spatial structure with element counts per storey.
    """
    model = _get_model(file_path)

    def _children(element) -> list:
        result = []
        for rel in model.by_type("IfcRelAggregates"):
            if rel.RelatingObject == element:
                for child in rel.RelatedObjects:
                    node = {
                        "global_id": getattr(child, "GlobalId", None),
                        "name": getattr(child, "Name", None),
                        "class": child.is_a(),
                        "children": _children(child),
                    }
                    # Count contained elements for storeys/spaces
                    if child.is_a() in ("IfcBuildingStorey", "IfcSpace"):
                        count = 0
                        for rel2 in model.by_type("IfcRelContainedInSpatialStructure"):
                            if rel2.RelatingStructure == child:
                                count += len(rel2.RelatedElements)
                        node["contained_elements"] = count
                    result.append(node)
        return result

    projects = model.by_type("IfcProject")
    if not projects:
        return json.dumps({"error": "No IfcProject found"})

    tree = {
        "global_id": getattr(projects[0], "GlobalId", None),
        "name": getattr(projects[0], "Name", None),
        "class": "IfcProject",
        "children": _children(projects[0]),
    }
    return json.dumps(tree, indent=2)


@mcp.tool()
def search_elements(file_path: str, query: str, ifc_class: str = "") -> str:
    """Search elements by name, description, or property value.

    Args:
        file_path: Path to the IFC file.
        query: Search term (case-insensitive substring match on name/description/object_type).
        ifc_class: Optional IFC class filter (e.g. 'IfcWall'). Empty = all classes.

    Returns:
        JSON list of matching entities with their GlobalId and class.
    """
    model = _get_model(file_path)
    query_lower = query.lower()
    entities = model.by_type(ifc_class) if ifc_class else list(model)

    result = []
    for entity in entities:
        if not hasattr(entity, "GlobalId"):
            continue
        name = str(getattr(entity, "Name", "") or "").lower()
        desc = str(getattr(entity, "Description", "") or "").lower()
        obj_type = str(getattr(entity, "ObjectType", "") or "").lower()
        if query_lower in name or query_lower in desc or query_lower in obj_type:
            result.append({
                "global_id": entity.GlobalId,
                "name": getattr(entity, "Name", None),
                "ifc_class": entity.is_a(),
                "object_type": getattr(entity, "ObjectType", None),
            })
        if len(result) >= 200:
            break
    return json.dumps(result, indent=2)


@mcp.tool()
def get_safe_metadata(file_path: str) -> str:
    """Extract cloud-safe metadata (PII stripped) for enrichment queries.

    Args:
        file_path: Path to the IFC file.

    Returns:
        JSON list of safe metadata tuples.
    """
    model = _get_model(file_path)
    safe_data = extract_safe_metadata(model)
    return json.dumps(safe_data, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECKER TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def run_baseline_check(file_path: str, output_format: str = "json") -> str:
    """Run all baseline quality checks (schema, IDS, spatial, GUID, proxy, type).

    Args:
        file_path: Path to the IFC file.
        output_format: 'json' or 'html'.

    Returns:
        Check results with per-check pass/fail and issue counts.
    """
    checker_report = run_all(file_path)
    if output_format == "html":
        output_dir = Path(file_path).parent / "reports"
        output_dir.mkdir(exist_ok=True)
        html_path = output_dir / f"{Path(file_path).stem}_report.html"
        report_module.to_html(checker_report, html_path)
        return json.dumps({
            "summary": checker_report.telegram_summary,
            "html_report": str(html_path),
            "results": checker_report.to_dict(),
        }, indent=2, default=str)
    return report_module.to_json(checker_report)


@mcp.tool()
def run_specific_check(file_path: str, check_name: str, ids_path: str = "") -> str:
    """Run a single checker module.

    Args:
        file_path: Path to the IFC file.
        check_name: One of: schema, ids, spatial, guid, proxy, type.
        ids_path: Path to IDS file (only needed for 'ids' check).

    Returns:
        JSON result for the requested check.
    """
    kwargs = {}
    if check_name == "ids" and ids_path:
        kwargs["ids_path"] = ids_path
    report = run_all(file_path, checks=[check_name], **kwargs)
    result = report.results.get(check_name)
    if result:
        return json.dumps(result.to_dict(), indent=2, default=str)
    return json.dumps({"error": f"Check '{check_name}' did not run", "errors": report.errors}, indent=2)


@mcp.tool()
def get_proxies(file_path: str) -> str:
    """List all IfcBuildingElementProxy elements with metadata for reclassification.

    Args:
        file_path: Path to the IFC file.

    Returns:
        JSON with proxy count, grouped pattern analysis, and element list.
    """
    from ifc_agent.checker.proxy_check import run as proxy_run
    result = proxy_run(file_path)
    return json.dumps(result.to_dict(), indent=2)


@mcp.tool()
def get_orphan_elements(file_path: str) -> str:
    """Find elements with no spatial containment (not in any storey or space).

    Args:
        file_path: Path to the IFC file.

    Returns:
        JSON with orphan elements list and count.
    """
    from ifc_agent.checker.spatial_check import run as spatial_run
    result = spatial_run(file_path)
    return json.dumps(result.to_dict(), indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# DIFF TOOLS — compare two IFC files
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def diff_ifc_files(file_path_a: str, file_path_b: str) -> str:
    """Compare two IFC files and report additions, deletions, and modifications.

    Compares by GlobalId across both files:
    - Added: GUIDs present in B but not A
    - Deleted: GUIDs present in A but not B
    - Modified: GUIDs in both where Name, IFC class, or ObjectType changed
    - Property changes: pset key/value differences for shared elements

    Args:
        file_path_a: Path to the baseline IFC file (original).
        file_path_b: Path to the revised IFC file (updated).

    Returns:
        JSON diff report with added/deleted/modified element lists and summary.
    """
    model_a = _get_model(file_path_a)
    model_b = _get_model(file_path_b)

    def _index(model: ifcopenshell.file) -> dict:
        idx = {}
        for entity in model:
            gid = getattr(entity, "GlobalId", None)
            if gid:
                try:
                    psets = ifcopenshell.util.element.get_psets(entity)
                except Exception:
                    psets = {}
                idx[gid] = {
                    "name": getattr(entity, "Name", None),
                    "ifc_class": entity.is_a(),
                    "object_type": getattr(entity, "ObjectType", None),
                    "description": getattr(entity, "Description", None),
                    "psets": psets,
                }
        return idx

    idx_a = _index(model_a)
    idx_b = _index(model_b)

    guids_a = set(idx_a)
    guids_b = set(idx_b)

    added = [
        {"global_id": gid, **{k: v for k, v in idx_b[gid].items() if k != "psets"}}
        for gid in sorted(guids_b - guids_a)
    ]
    deleted = [
        {"global_id": gid, **{k: v for k, v in idx_a[gid].items() if k != "psets"}}
        for gid in sorted(guids_a - guids_b)
    ]

    modified = []
    for gid in sorted(guids_a & guids_b):
        ea, eb = idx_a[gid], idx_b[gid]
        field_changes = {}
        for field in ("name", "ifc_class", "object_type", "description"):
            if ea.get(field) != eb.get(field):
                field_changes[field] = {"from": ea.get(field), "to": eb.get(field)}

        # Compare psets
        pset_changes = {}
        all_psets = set(ea["psets"]) | set(eb["psets"])
        for pset_name in all_psets:
            pa = ea["psets"].get(pset_name, {})
            pb = eb["psets"].get(pset_name, {})
            if pa != pb:
                all_props = set(pa) | set(pb)
                changed_props = {
                    p: {"from": pa.get(p), "to": pb.get(p)}
                    for p in all_props
                    if pa.get(p) != pb.get(p)
                }
                if changed_props:
                    pset_changes[pset_name] = changed_props

        if field_changes or pset_changes:
            modified.append({
                "global_id": gid,
                "ifc_class": eb["ifc_class"],
                "name": eb["name"],
                "field_changes": field_changes,
                "pset_changes": pset_changes,
            })

    # Spatial structure diff
    def _spatial_map(model):
        sm = {}
        for rel in model.by_type("IfcRelContainedInSpatialStructure"):
            container_gid = getattr(rel.RelatingStructure, "GlobalId", None)
            for el in rel.RelatedElements:
                sm[el.GlobalId] = container_gid
        return sm

    spatial_a = _spatial_map(model_a)
    spatial_b = _spatial_map(model_b)
    moved = []
    for gid in sorted(guids_a & guids_b):
        cont_a = spatial_a.get(gid)
        cont_b = spatial_b.get(gid)
        if cont_a != cont_b:
            moved.append({
                "global_id": gid,
                "name": idx_b[gid]["name"],
                "ifc_class": idx_b[gid]["ifc_class"],
                "from_container": cont_a,
                "to_container": cont_b,
            })

    return json.dumps({
        "file_a": file_path_a,
        "file_b": file_path_b,
        "summary": {
            "added": len(added),
            "deleted": len(deleted),
            "modified": len(modified),
            "moved": len(moved),
            "total_in_a": len(guids_a),
            "total_in_b": len(guids_b),
        },
        "added": added,
        "deleted": deleted,
        "modified": modified,
        "moved": moved,
    }, indent=2, default=str)


@mcp.tool()
def diff_element_properties(file_path_a: str, file_path_b: str, global_id: str) -> str:
    """Deep compare a single element's properties between two IFC versions.

    Args:
        file_path_a: Baseline IFC file.
        file_path_b: Revised IFC file.
        global_id: GlobalId of the element to compare.

    Returns:
        JSON with side-by-side property comparison for every pset.
    """
    model_a = _get_model(file_path_a)
    model_b = _get_model(file_path_b)

    ea = by_guid(model_a, global_id)
    eb = by_guid(model_b, global_id)

    if ea is None and eb is None:
        return json.dumps({"error": f"Element {global_id} not found in either file"})

    def _get_info(model, entity):
        if entity is None:
            return None
        try:
            psets = ifcopenshell.util.element.get_psets(entity)
        except Exception:
            psets = {}
        try:
            container = ifcopenshell.util.element.get_container(entity)
            container_info = {"name": getattr(container, "Name", None), "class": container.is_a() if container else None}
        except Exception:
            container_info = None
        return {
            "name": getattr(entity, "Name", None),
            "ifc_class": entity.is_a(),
            "object_type": getattr(entity, "ObjectType", None),
            "description": getattr(entity, "Description", None),
            "container": container_info,
            "psets": psets,
        }

    info_a = _get_info(model_a, ea)
    info_b = _get_info(model_b, eb)

    return json.dumps({
        "global_id": global_id,
        "in_file_a": info_a,
        "in_file_b": info_b,
    }, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH / MUTATION TOOLS — modify IFC files
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def fix_guid_duplicates(file_path: str, output_path: str = "") -> str:
    """Find and fix all duplicate GlobalIds by assigning new valid GUIDs.

    Args:
        file_path: Source IFC file.
        output_path: Output path. Defaults to '<stem>_guid_fixed.ifc'.

    Returns:
        JSON with count of fixed duplicates and output file path.
    """
    model = ifcopenshell.open(file_path)
    seen: dict[str, list] = {}
    for entity in model:
        gid = getattr(entity, "GlobalId", None)
        if gid:
            seen.setdefault(gid, []).append(entity)

    fixed = 0
    for gid, entities in seen.items():
        for entity in entities[1:]:
            entity.GlobalId = ifcopenshell.guid.new()
            fixed += 1

    real_output = output_path or str(Path(file_path).with_stem(Path(file_path).stem + "_guid_fixed"))
    model.write(real_output)
    _invalidate_cache(file_path)

    return json.dumps({
        "status": "success",
        "duplicates_fixed": fixed,
        "output_file": real_output,
    }, indent=2)


@mcp.tool()
def reclassify_element(
    file_path: str,
    global_id: str,
    new_ifc_class: str,
    new_name: str = "",
    output_path: str = "",
) -> str:
    """Change the IFC class of an element (e.g. IfcBuildingElementProxy → IfcPump).

    This creates a new entity of the target class, copies all properties and
    relationships, and removes the old entity.

    Args:
        file_path: Source IFC file.
        global_id: GlobalId of the element to reclassify.
        new_ifc_class: Target IFC class name.
        new_name: Optional new Name for the element.
        output_path: Output path. Defaults to '<stem>_reclassified.ifc'.

    Returns:
        JSON with status and output file path.
    """
    model = ifcopenshell.open(file_path)
    entity = by_guid(model, global_id)
    if entity is None:
        return json.dumps({"status": "error", "message": f"Entity {global_id} not found"})

    old_class = entity.is_a()
    old_name = getattr(entity, "Name", None)

    try:
        # Use ifcopenshell.api to reassign type if it is a proxy
        new_entity = ifcopenshell.api.run("root.reassign_class", model, product=entity, ifc_class=new_ifc_class)
        if new_name:
            new_entity.Name = new_name
        real_output = output_path or str(Path(file_path).with_stem(Path(file_path).stem + "_reclassified"))
        model.write(real_output)
        _invalidate_cache(file_path)
        return json.dumps({
            "status": "success",
            "global_id": getattr(new_entity, "GlobalId", global_id),
            "old_class": old_class,
            "new_class": new_entity.is_a(),
            "old_name": old_name,
            "new_name": getattr(new_entity, "Name", None),
            "output_file": real_output,
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
def add_or_update_pset(
    file_path: str,
    global_ids: list,
    pset_name: str,
    properties: dict,
    output_path: str = "",
) -> str:
    """Add or update a property set on one or more elements.

    Creates the Pset if it does not exist; updates existing property values.

    Args:
        file_path: Source IFC file.
        global_ids: List of element GlobalIds to update.
        pset_name: Name of the property set (e.g. 'Pset_ManufacturerTypeInformation').
        properties: Dict of property name → value to set.
        output_path: Output path. Defaults to '<stem>_pset_updated.ifc'.

    Returns:
        JSON with count of updated elements and output file path.
    """
    model = ifcopenshell.open(file_path)
    updated = 0
    errors = []

    for gid in global_ids:
        entity = by_guid(model, gid)
        if entity is None:
            errors.append(f"Entity {gid} not found")
            continue
        try:
            ifcopenshell.api.run(
                "pset.edit_pset",
                model,
                product=entity,
                name=pset_name,
                properties=properties,
            )
            updated += 1
        except Exception as e:
            try:
                pset = ifcopenshell.api.run("pset.add_pset", model, product=entity, name=pset_name)
                ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties=properties)
                updated += 1
            except Exception as e2:
                errors.append(f"Entity {gid}: {e2}")

    real_output = output_path or str(Path(file_path).with_stem(Path(file_path).stem + "_pset_updated"))
    model.write(real_output)
    _invalidate_cache(file_path)
    return json.dumps({
        "status": "success",
        "updated_elements": updated,
        "errors": errors,
        "output_file": real_output,
    }, indent=2)


@mcp.tool()
def assign_to_spatial_container(
    file_path: str,
    global_id: str,
    container_global_id: str,
    output_path: str = "",
) -> str:
    """Move an element into a spatial container (storey or space).

    Removes existing spatial containment relationship and adds a new one.

    Args:
        file_path: Source IFC file.
        global_id: GlobalId of the element to move.
        container_global_id: GlobalId of the target IfcBuildingStorey or IfcSpace.
        output_path: Output path.

    Returns:
        JSON with status and output file path.
    """
    model = ifcopenshell.open(file_path)
    entity = by_guid(model, global_id)
    container = by_guid(model, container_global_id)

    if entity is None:
        return json.dumps({"status": "error", "message": f"Element {global_id} not found"})
    if container is None:
        return json.dumps({"status": "error", "message": f"Container {container_global_id} not found"})

    try:
        ifcopenshell.api.run("spatial.assign_container", model, product=entity, relating_structure=container)
        real_output = output_path or str(Path(file_path).with_stem(Path(file_path).stem + "_moved"))
        model.write(real_output)
        _invalidate_cache(file_path)
        return json.dumps({
            "status": "success",
            "element": global_id,
            "new_container": container_global_id,
            "container_name": getattr(container, "Name", None),
            "output_file": real_output,
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
def add_classification_reference(
    file_path: str,
    global_ids: list,
    classification_system: str,
    identification: str,
    class_name: str,
    output_path: str = "",
) -> str:
    """Add a classification reference (e.g. Uniclass, OmniClass) to elements.

    Args:
        file_path: Source IFC file.
        global_ids: List of element GlobalIds to classify.
        classification_system: Name of the classification system (e.g. 'Uniclass 2015').
        identification: Classification code (e.g. 'Ss_65_10_95').
        class_name: Human-readable name (e.g. 'Ventilation systems').
        output_path: Output path.

    Returns:
        JSON with count of classified elements and output file path.
    """
    model = ifcopenshell.open(file_path)

    # Get or create classification system
    system = None
    for cls in model.by_type("IfcClassification"):
        if cls.Name == classification_system:
            system = cls
            break
    if system is None:
        system = model.createIfcClassification(Name=classification_system)

    updated = 0
    errors = []
    for gid in global_ids:
        entity = by_guid(model, gid)
        if entity is None:
            errors.append(f"Entity {gid} not found")
            continue
        try:
            ref = model.createIfcClassificationReference(
                Identification=identification,
                Name=class_name,
                ReferencedSource=system,
            )
            model.createIfcRelAssociatesClassification(
                GlobalId=ifcopenshell.guid.new(),
                RelatedObjects=[entity],
                RelatingClassification=ref,
            )
            updated += 1
        except Exception as e:
            errors.append(f"Entity {gid}: {e}")

    real_output = output_path or str(Path(file_path).with_stem(Path(file_path).stem + "_classified"))
    model.write(real_output)
    _invalidate_cache(file_path)
    return json.dumps({
        "status": "success",
        "classified_elements": updated,
        "errors": errors,
        "output_file": real_output,
    }, indent=2)


@mcp.tool()
def apply_patch_set(file_path: str, patches: list, output_path: str = "") -> str:
    """Apply a list of structured patch operations to an IFC file.

    Each patch is a dict with 'operation' and operation-specific fields:
      - {"operation": "set_property", "global_id": "...", "pset": "...", "prop": "...", "value": "..."}
      - {"operation": "set_name", "global_id": "...", "name": "..."}
      - {"operation": "set_object_type", "global_id": "...", "object_type": "..."}
      - {"operation": "set_description", "global_id": "...", "description": "..."}
      - {"operation": "add_classification", "global_id": "...", "system": "...", "identification": "...", "name": "..."}

    Args:
        file_path: Source IFC file.
        patches: List of patch operation dicts.
        output_path: Output path.

    Returns:
        JSON with per-patch status and output file path.
    """
    model = ifcopenshell.open(file_path)
    results = []

    for i, patch in enumerate(patches):
        op = patch.get("operation")
        gid = patch.get("global_id")
        entity = by_guid(model, gid) if gid else None

        try:
            if op == "set_property":
                if entity is None:
                    raise ValueError(f"Entity {gid} not found")
                pset_name = patch["pset"]
                prop_name = patch["prop"]
                value = patch["value"]
                try:
                    ifcopenshell.api.run("pset.edit_pset", model, product=entity,
                                         name=pset_name, properties={prop_name: value})
                except Exception:
                    pset = ifcopenshell.api.run("pset.add_pset", model, product=entity, name=pset_name)
                    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={prop_name: value})
                results.append({"index": i, "operation": op, "status": "ok", "global_id": gid})

            elif op == "set_name":
                if entity is None:
                    raise ValueError(f"Entity {gid} not found")
                entity.Name = patch["name"]
                results.append({"index": i, "operation": op, "status": "ok", "global_id": gid})

            elif op == "set_object_type":
                if entity is None:
                    raise ValueError(f"Entity {gid} not found")
                entity.ObjectType = patch["object_type"]
                results.append({"index": i, "operation": op, "status": "ok", "global_id": gid})

            elif op == "set_description":
                if entity is None:
                    raise ValueError(f"Entity {gid} not found")
                entity.Description = patch["description"]
                results.append({"index": i, "operation": op, "status": "ok", "global_id": gid})

            elif op == "add_classification":
                if entity is None:
                    raise ValueError(f"Entity {gid} not found")
                system_name = patch["system"]
                system = None
                for cls in model.by_type("IfcClassification"):
                    if cls.Name == system_name:
                        system = cls
                        break
                if system is None:
                    system = model.createIfcClassification(Name=system_name)
                ref = model.createIfcClassificationReference(
                    Identification=patch.get("identification", ""),
                    Name=patch.get("name", ""),
                    ReferencedSource=system,
                )
                model.createIfcRelAssociatesClassification(
                    GlobalId=ifcopenshell.guid.new(),
                    RelatedObjects=[entity],
                    RelatingClassification=ref,
                )
                results.append({"index": i, "operation": op, "status": "ok", "global_id": gid})

            else:
                results.append({"index": i, "operation": op, "status": "error", "message": f"Unknown operation: {op}"})

        except Exception as e:
            results.append({"index": i, "operation": op, "status": "error",
                            "global_id": gid, "message": str(e)})

    real_output = output_path or str(Path(file_path).with_stem(Path(file_path).stem + "_patched"))
    model.write(real_output)
    _invalidate_cache(file_path)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return json.dumps({
        "status": "success",
        "patches_applied": ok_count,
        "patches_failed": len(results) - ok_count,
        "results": results,
        "output_file": real_output,
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# bSDD TOOLS — buildingSMART Data Dictionary API
# ═══════════════════════════════════════════════════════════════════════════════

_BSDD_BASE = "https://api.bsdd.buildingsmart.org"


def _bsdd_get(path: str, params: dict = None) -> dict:
    url = f"{_BSDD_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def bsdd_search_classes(query: str, dictionary_uri: str = "", language_code: str = "EN") -> str:
    """Search the buildingSMART Data Dictionary for classes matching a query.

    Args:
        query: Search term (e.g. 'pump', 'fire door', 'concrete wall').
        dictionary_uri: Optional URI to limit search to one dictionary
                        (e.g. 'https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3').
        language_code: Language for results (default 'EN').

    Returns:
        JSON list of matching classes with URI, name, code, and dictionary.
    """
    params = {"SearchText": query, "LanguageCode": language_code, "TypeFilter": "Class"}
    if dictionary_uri:
        params["DictionaryUri"] = dictionary_uri
    data = _bsdd_get("/api/TextSearch", params)
    if "error" in data:
        return json.dumps(data)
    classes = data.get("classes", data.get("Classes", []))
    result = [
        {
            "uri": c.get("uri", c.get("Uri")),
            "name": c.get("name", c.get("Name")),
            "code": c.get("code", c.get("Code")),
            "dictionary_name": c.get("dictionaryName", c.get("DictionaryName")),
            "dictionary_uri": c.get("dictionaryUri", c.get("DictionaryUri")),
        }
        for c in (classes if isinstance(classes, list) else [])
    ]
    return json.dumps({"query": query, "results": result, "count": len(result)}, indent=2)


@mcp.tool()
def bsdd_get_class(class_uri: str, language_code: str = "EN") -> str:
    """Get full class definition from bSDD including properties and relations.

    Args:
        class_uri: Full bSDD URI for the class
                   (e.g. 'https://identifier.buildingsmart.org/uri/buildingsmart/ifc/4.3/class/IfcPump').
        language_code: Language for property names/descriptions.

    Returns:
        JSON with class definition, required properties, and related IFC classes.
    """
    data = _bsdd_get("/api/Class", {"Uri": class_uri, "LanguageCode": language_code})
    if "error" in data:
        return json.dumps(data)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def bsdd_list_dictionaries() -> str:
    """List available bSDD dictionaries (classification systems).

    Returns:
        JSON list of available dictionaries with name, version, URI, and organization.
    """
    data = _bsdd_get("/api/Dictionary")
    if "error" in data:
        return json.dumps(data)
    dicts = data.get("dictionaries", data.get("Dictionaries", []))
    result = [
        {
            "name": d.get("name", d.get("Name")),
            "version": d.get("version", d.get("Version")),
            "uri": d.get("uri", d.get("Uri")),
            "organization_name": d.get("organizationNameOwner", d.get("OrganizationNameOwner")),
            "language_code": d.get("defaultLanguageCode", d.get("DefaultLanguageCode")),
        }
        for d in (dicts if isinstance(dicts, list) else [])
    ]
    return json.dumps({"dictionaries": result, "count": len(result)}, indent=2)


@mcp.tool()
def bsdd_validate_element_classification(file_path: str, global_id: str) -> str:
    """Validate an element's classification references against bSDD.

    Checks each classification reference on the element against the live bSDD API
    to confirm it is a valid, recognized class URI.

    Args:
        file_path: Path to the IFC file.
        global_id: GlobalId of the element to validate.

    Returns:
        JSON with validation results for each classification reference.
    """
    model = _get_model(file_path)
    entity = by_guid(model, global_id)
    if entity is None:
        return json.dumps({"error": f"Entity {global_id} not found"})

    results = []
    for rel in getattr(entity, "HasAssociations", []):
        if not rel.is_a("IfcRelAssociatesClassification"):
            continue
        ref = rel.RelatingClassification
        identification = getattr(ref, "Identification", None)
        name = getattr(ref, "Name", None)
        source = getattr(ref, "ReferencedSource", None)
        system_name = getattr(source, "Name", None) if source else None

        # Try to look it up in bSDD by building a URI guess or direct lookup
        uri = getattr(ref, "Location", None)
        bsdd_valid = False
        bsdd_info = {}

        if uri:
            data = _bsdd_get("/api/Class", {"Uri": uri})
            bsdd_valid = "error" not in data and bool(data)
            if bsdd_valid:
                bsdd_info = {
                    "name": data.get("name"),
                    "code": data.get("code"),
                    "dictionary": data.get("dictionaryName"),
                }

        results.append({
            "identification": identification,
            "name": name,
            "system": system_name,
            "uri": uri,
            "bsdd_valid": bsdd_valid,
            "bsdd_info": bsdd_info,
        })

    return json.dumps({
        "global_id": global_id,
        "name": getattr(entity, "Name", None),
        "ifc_class": entity.is_a(),
        "classification_refs": results,
        "all_valid": all(r["bsdd_valid"] for r in results) if results else None,
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# IDS AUTHORING TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_ids_specs(ids_path: str) -> str:
    """List all specifications in an IDS file with their applicability and requirements.

    Args:
        ids_path: Path to the IDS XML file.

    Returns:
        JSON list of specifications with name, applicability facets, and requirements.
    """
    try:
        from ifctester import ids as ids_module
        spec = ids_module.open(ids_path)
        result = []
        for s in spec.specifications:
            applicability = []
            for facet in s.applicability:
                facet_dict = {"type": type(facet).__name__}
                for attr in ("name", "value", "predefinedType", "system", "identification"):
                    val = getattr(facet, attr, None)
                    if val is not None:
                        facet_dict[attr] = str(val)
                applicability.append(facet_dict)

            requirements = []
            for facet in s.requirements:
                req_dict = {"type": type(facet).__name__, "cardinality": getattr(facet, "cardinality", "required")}
                for attr in ("name", "value", "predefinedType", "system", "identification"):
                    val = getattr(facet, attr, None)
                    if val is not None:
                        req_dict[attr] = str(val)
                requirements.append(req_dict)

            result.append({
                "name": s.name,
                "description": getattr(s, "description", None),
                "minOccurs": getattr(s, "minOccurs", None),
                "maxOccurs": getattr(s, "maxOccurs", None),
                "applicability": applicability,
                "requirements": requirements,
            })
        return json.dumps({"ids_file": ids_path, "specifications": result, "count": len(result)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.tool()
def validate_ids_spec(file_path: str, ids_path: str, spec_name: str = "") -> str:
    """Validate an IFC file against a specific IDS specification (or all specs).

    Args:
        file_path: Path to the IFC file.
        ids_path: Path to the IDS XML file.
        spec_name: Name of a specific specification to run. Empty = run all.

    Returns:
        JSON with pass/fail per specification and failed element GlobalIds.
    """
    try:
        from ifctester import ids as ids_module
        from ifctester.reporter import Json as JsonReporter
        model = _get_model(file_path)
        spec = ids_module.open(ids_path)

        # Filter to specific spec if requested
        if spec_name:
            spec.specifications = [s for s in spec.specifications if s.name == spec_name]
            if not spec.specifications:
                return json.dumps({"error": f"No specification named '{spec_name}' found in {ids_path}"})

        spec.validate(model)

        results = []
        for s in spec.specifications:
            failed_entities = []
            for facet in s.requirements:
                for entity_result in getattr(facet, "failed_entities", []):
                    failed_entities.append({
                        "global_id": getattr(entity_result, "GlobalId", None),
                        "name": getattr(entity_result, "Name", None),
                        "ifc_class": entity_result.is_a() if hasattr(entity_result, "is_a") else None,
                    })

            results.append({
                "name": s.name,
                "status": getattr(s, "status", None),
                "total_applicable": getattr(s, "total_applicable", 0),
                "total_passed": getattr(s, "total_passes", 0),
                "total_failed": len(failed_entities),
                "failed_entities": failed_entities[:50],
            })

        return json.dumps({
            "file": file_path,
            "ids": ids_path,
            "specifications": results,
            "overall_passed": all(r["status"] for r in results),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@mcp.tool()
def create_ids_from_model(
    file_path: str,
    output_ids_path: str,
    title: str = "Model Requirements",
    ifc_classes: list = None,
    required_psets: list = None,
) -> str:
    """Generate a starter IDS file from observed model patterns.

    Analyzes the model and generates IDS specifications for the given IFC classes
    and required property sets, based on what the model currently has.

    Args:
        file_path: Path to the IFC file to analyze.
        output_ids_path: Where to save the generated IDS file.
        title: Title for the IDS document.
        ifc_classes: List of IFC classes to generate specs for. None = auto-detect top types.
        required_psets: List of Pset names to require. None = require psets found in model.

    Returns:
        JSON with count of specifications generated and output file path.
    """
    try:
        from ifctester import ids as ids_module
        model = _get_model(file_path)

        if ifc_classes is None:
            # Auto-detect top 10 most common classes (excluding abstract/spatial)
            skip = {"IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey",
                    "IfcSpace", "IfcRelAggregates", "IfcRelContainedInSpatialStructure",
                    "IfcPropertySet", "IfcRelDefinesByProperties", "IfcOwnerHistory"}
            counts: dict[str, int] = {}
            for e in model:
                cls = e.is_a()
                if cls not in skip and hasattr(e, "GlobalId"):
                    counts[cls] = counts.get(cls, 0) + 1
            ifc_classes = [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:10]]

        if required_psets is None:
            # Gather psets that appear in >20% of elements of each class
            required_psets = []
            for cls in ifc_classes:
                pset_counts: dict[str, int] = {}
                entities = model.by_type(cls)
                for e in entities:
                    try:
                        for pset_name in ifcopenshell.util.element.get_psets(e):
                            pset_counts[pset_name] = pset_counts.get(pset_name, 0) + 1
                    except Exception:
                        pass
                threshold = max(1, len(entities) * 0.2)
                for pset_name, cnt in pset_counts.items():
                    if cnt >= threshold and pset_name not in required_psets:
                        required_psets.append(pset_name)

        # Build IDS
        my_ids = ids_module.Ids(title=title)
        spec_count = 0
        for cls in ifc_classes:
            entities = model.by_type(cls)
            if not entities:
                continue

            spec = ids_module.Specification(name=f"{cls} Requirements", minOccurs=0, maxOccurs="unbounded")
            spec.applicability.append(ids_module.Entity(name=cls))

            # Require name is present
            spec.requirements.append(
                ids_module.Attribute(name="Name", cardinality="required")
            )

            # Require relevant psets
            for pset_name in required_psets[:5]:
                pset_entities = [e for e in entities if pset_name in (ifcopenshell.util.element.get_psets(e) or {})]
                if len(pset_entities) > len(entities) * 0.2:
                    spec.requirements.append(
                        ids_module.Property(propertySet=pset_name, baseName="Name", cardinality="required")
                    )

            my_ids.specifications.append(spec)
            spec_count += 1

        Path(output_ids_path).parent.mkdir(parents=True, exist_ok=True)
        my_ids.to_xml(output_ids_path)
        return json.dumps({
            "status": "success",
            "specifications_created": spec_count,
            "ifc_classes": ifc_classes,
            "required_psets": required_psets,
            "output_file": str(output_ids_path),
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# BEP / RULE ENGINE TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def extract_bep_rules(file_path: str, output_yaml_path: str) -> str:
    """Parse a BEP document (PDF/DOCX) using LLM and output structured YAML rules.

    Args:
        file_path: Path to the BEP document (PDF or DOCX).
        output_yaml_path: Where to save the output YAML file.

    Returns:
        JSON with extraction stats and rule names.
    """
    from ifc_agent.bep_parser.ingest import extract_text
    from ifc_agent.bep_parser.extractor import extract_rules_to_yaml
    try:
        text = extract_text(file_path)
        data = extract_rules_to_yaml(text, output_yaml_path=output_yaml_path)
        rules = [r.get("name", "Unnamed") for r in data.get("rules", [])]
        return json.dumps({
            "status": "success",
            "extracted_rules": len(rules),
            "rule_names": rules,
            "output_file": str(output_yaml_path),
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
def compile_bep_yaml_to_ids(yaml_path: str, output_ids_path: str) -> str:
    """Compile an extracted YAML rule pack into an executable IDS XML file.

    Args:
        yaml_path: Path to the YAML rule pack.
        output_ids_path: Destination path for the IDS file.

    Returns:
        JSON with compilation stats and output path.
    """
    from ifc_agent.bep_parser.compiler import compile_yaml_to_ids
    try:
        spec = compile_yaml_to_ids(yaml_path, output_ids_path=output_ids_path)
        return json.dumps({
            "status": "success",
            "compiled_specifications": len(spec.specifications),
            "output_file": str(output_ids_path),
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def auto_classify_proxies(file_path: str, output_path: str = "") -> str:
    """Classify all IfcBuildingElementProxy elements using LLM inference.

    Uses element Name, Description, ObjectType, and attached properties to infer
    the correct IFC class, then creates a corrected IFC file.

    Args:
        file_path: Source IFC file.
        output_path: Optional output path.

    Returns:
        JSON with proxy count, classification results, and output file path.
    """
    from ifc_agent.classification.proxy_extractor import extract_proxies
    from ifc_agent.classification.bsdd_resolver import infer_class
    from ifc_agent.classification.mutator import classify_and_mutate
    try:
        model = ifcopenshell.open(file_path)
        proxies = extract_proxies(model)
        if not proxies:
            return json.dumps({"status": "success", "mutated_count": 0, "message": "No proxies found."})
        predictions = {p["global_id"]: infer_class(p) for p in proxies}
        res = classify_and_mutate(file_path, predictions, output_path=output_path or None)
        res["status"] = "success"
        res["proxies_scanned"] = len(proxies)
        res["predictions"] = {k: v for k, v in list(predictions.items())[:20]}
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# COBie ENRICHMENT TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def enrich_cobie_data(file_path: str, output_path: str = "") -> str:
    """Harvest incomplete FM elements and inject missing COBie properties via LLM.

    Args:
        file_path: Source IFC file.
        output_path: Optional output path.

    Returns:
        JSON with enrichment stats and output file path.
    """
    from ifc_agent.enrichment.harvester import harvest_metadata
    from ifc_agent.enrichment.ai_mapper import extract_cobie_parameters
    from ifc_agent.enrichment.injector import evaluate_and_inject
    try:
        model = ifcopenshell.open(file_path)
        items = harvest_metadata(model)
        if not items:
            return json.dumps({"status": "success", "elements_mutated": 0, "message": "No elements required enrichment."})
        map_inject = {}
        for meta in items:
            out = extract_cobie_parameters(meta)
            if out:
                map_inject[meta["global_id"]] = out
        res = evaluate_and_inject(file_path, map_inject, output_path=output_path or None)
        res["status"] = "success"
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# Server entry point
# ═══════════════════════════════════════════════════════════════════════════════

def start_server(host: str = "127.0.0.1", port: int = 8000):
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    start_server()
