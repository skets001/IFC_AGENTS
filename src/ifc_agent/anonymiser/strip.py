"""Data anonymisation / PII stripping for IFC files.

Implements the privacy-by-design layer from Section 1.4 of the roadmap.
Strips personal/sensitive fields before any data leaves the local environment
for cloud API calls (OpenRouter enrichment, bSDD lookups, etc.).
"""

import ifcopenshell
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# Fields to strip / pseudonymise before cloud API calls
STRIP_FIELDS = {
    "IfcSite": ["RefLatitude", "RefLongitude", "RefElevation"],
    "IfcProject": ["LongName"],
    "IfcAddress": None,            # Strip entire entity data
    "IfcPerson": None,             # Strip entire entity data
    "IfcOrganization": ["Name"],
}

# OwnerHistory fields to clear
OWNER_HISTORY_CLEAR = ["OwningUser", "OwningApplication"]

# Fields safe to send for enrichment queries
SAFE_FOR_CLOUD = [
    "Name",
    "Description",
    "ObjectType",
    "PredefinedType",
    "Pset_ManufacturerTypeInformation.Manufacturer",
    "Pset_ManufacturerTypeInformation.ModelLabel",
]


@dataclass
class AnonymiseResult:
    """Result of anonymisation process."""
    fields_stripped: int = 0
    entities_processed: int = 0
    stripped_details: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fields_stripped": self.fields_stripped,
            "entities_processed": self.entities_processed,
            "stripped_details": self.stripped_details,
            "errors": self.errors,
        }


def extract_safe_metadata(model: ifcopenshell.file) -> list[dict]:
    """Extract only cloud-safe metadata tuples from the model.

    Returns a list of dicts with equipment identifiers suitable
    for sending to OpenRouter for enrichment queries.
    No geometry, no GPS, no personal data, no project identifiers.
    """
    safe_data = []

    for product in model.by_type("IfcProduct"):
        entry = {
            "ifc_class": product.is_a(),
            "name": getattr(product, "Name", None) or "",
            "description": getattr(product, "Description", None) or "",
            "object_type": getattr(product, "ObjectType", None) or "",
            "global_id": product.GlobalId,
        }

        # Extract predefined type if available
        predefined = getattr(product, "PredefinedType", None)
        if predefined:
            entry["predefined_type"] = str(predefined)

        # Extract manufacturer info from Psets (safe data)
        try:
            psets = ifcopenshell.util.element.get_psets(product)
            mfr_pset = psets.get("Pset_ManufacturerTypeInformation", {})
            if mfr_pset:
                entry["manufacturer"] = mfr_pset.get("Manufacturer", "")
                entry["model_label"] = mfr_pset.get("ModelLabel", "")
        except Exception:
            pass

        # Only include entries with meaningful identification
        if entry["name"] or entry["object_type"]:
            safe_data.append(entry)

    return safe_data


def strip_personal_fields(
    model: ifcopenshell.file,
    output_path: Optional[str | Path] = None,
) -> AnonymiseResult:
    """Strip personal/sensitive fields from an IFC model.

    Creates a sanitised copy suitable for sharing or cloud processing.
    The original model object is modified in-place; save to output_path
    to preserve the original file.

    Args:
        model: An ifcopenshell model (will be modified in-place).
        output_path: If provided, save the anonymised model here.

    Returns:
        AnonymiseResult with details of what was stripped.
    """
    result = AnonymiseResult()

    # Strip IfcSite coordinates
    for site in model.by_type("IfcSite"):
        result.entities_processed += 1
        for attr in STRIP_FIELDS.get("IfcSite", []):
            if hasattr(site, attr):
                try:
                    setattr(site, attr, None)
                    result.fields_stripped += 1
                    result.stripped_details.append(f"IfcSite.{attr}")
                except Exception as e:
                    result.errors.append(f"Could not strip IfcSite.{attr}: {e}")

    # Strip IfcProject.LongName
    for project in model.by_type("IfcProject"):
        result.entities_processed += 1
        for attr in STRIP_FIELDS.get("IfcProject", []):
            if hasattr(project, attr):
                try:
                    setattr(project, attr, "[REDACTED]")
                    result.fields_stripped += 1
                    result.stripped_details.append(f"IfcProject.{attr}")
                except Exception as e:
                    result.errors.append(f"Could not strip IfcProject.{attr}: {e}")

    # Strip IfcPerson data
    for person in model.by_type("IfcPerson"):
        result.entities_processed += 1
        for attr_name in ["FamilyName", "GivenName", "MiddleNames", "Id"]:
            if hasattr(person, attr_name):
                try:
                    setattr(person, attr_name, "[REDACTED]")
                    result.fields_stripped += 1
                    result.stripped_details.append(f"IfcPerson.{attr_name}")
                except Exception:
                    pass

    # Strip IfcOrganization.Name
    for org in model.by_type("IfcOrganization"):
        result.entities_processed += 1
        try:
            org.Name = "[REDACTED]"
            result.fields_stripped += 1
            result.stripped_details.append("IfcOrganization.Name")
        except Exception:
            pass

    # Clear owner history references to people and applications.
    for owner_history in model.by_type("IfcOwnerHistory"):
        result.entities_processed += 1
        for attr_name in OWNER_HISTORY_CLEAR:
            if hasattr(owner_history, attr_name):
                try:
                    setattr(owner_history, attr_name, None)
                    result.fields_stripped += 1
                    result.stripped_details.append(f"IfcOwnerHistory.{attr_name}")
                except Exception as e:
                    result.errors.append(f"Could not strip IfcOwnerHistory.{attr_name}: {e}")

    # Strip address data
    for addr in model.by_type("IfcAddress"):
        result.entities_processed += 1
        for attr_name in dir(addr):
            if not attr_name.startswith("_") and attr_name[0].isupper():
                try:
                    val = getattr(addr, attr_name)
                    if isinstance(val, str) and val:
                        setattr(addr, attr_name, "[REDACTED]")
                        result.fields_stripped += 1
                    elif isinstance(val, (list, tuple)) and val:
                        redacted = type(val)("[REDACTED]" for _ in val)
                        setattr(addr, attr_name, redacted)
                        result.fields_stripped += 1
                except Exception:
                    pass

    # Save anonymised model if output path provided
    if output_path:
        try:
            model.write(str(output_path))
        except Exception as e:
            result.errors.append(f"Failed to write anonymised model: {e}")

    return result
