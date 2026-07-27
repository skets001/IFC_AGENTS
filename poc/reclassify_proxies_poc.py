"""PoC: deterministic (non-LLM) proxy reclassification via the MCP tool functions.

Same correction outcome as run_agent_poc.py, but the mapping logic is hard-coded
in Python instead of decided by the LLM. This is useful to (a) show that the
IfcOpenShell tool layer is fully usable on its own, and (b) produce a repeatable
baseline to compare the agent's LLM-driven decisions against.

It calls the MCP server tool functions directly (no HTTP, no LLM), chaining the
output file so each reclassification builds on the last, then re-checks proxies.

The real PoC ran against an internal architectural model (not shipped). Point
IFC_MODEL_PATH at any IFC4 file to reproduce.

Usage:
    export IFC_MODEL_PATH=/path/to/model.ifc
    python poc/reclassify_proxies_poc.py
    # or: python poc/reclassify_proxies_poc.py /path/to/model.ifc /path/to/out.ifc
"""
import os
import sys
import json
from collections import Counter

sys.path.insert(0, "src")

from ifc_agent.mcp_server.server import (
    get_proxies,
    reclassify_element,
    run_specific_check,
    get_entity_properties,
)

FILE = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.environ.get("IFC_MODEL_PATH", "tests/test_data/demo_model.ifc")
)
OUTPUT = sys.argv[2] if len(sys.argv) > 2 else FILE.replace(".ifc", "_corrected.ifc")

# Classification rules (name/ObjectType substring -> target IFC class)
RECLASSIFY_RULES = [
    ("AC Steel Platform", "IfcSlab"),
    ("Steel Post", "IfcColumn"),
    ("Metal Ladder", "IfcStairFlight"),
    ("Wall Sweep", "IfcCovering"),
    ("Lighting Switch", "IfcSwitchingDevice"),
    ("Steel Platform Terrace", "IfcSlab"),
]

# These keep IfcBuildingElementProxy (no good standard IFC class).
KEEP_AS_PROXY = ["RPC Tree", "Massing", "Logo Family", "Model Text", "Generic Models"]

print("=" * 70)
print("IFC PROXY RECLASSIFICATION — DETERMINISTIC PATCH (PoC)")
print("=" * 70)

print("\n[1] Loading proxy list...")
proxies = json.loads(get_proxies(FILE)).get("proxies", [])
print(f"    Found {len(proxies)} IfcBuildingElementProxy elements")

to_reclassify: dict[str, tuple[str, str]] = {}
to_keep: list[tuple[str, str]] = []
ungrouped: list[tuple[str, str, str]] = []

for p in proxies:
    gid = p["global_id"]
    name = p.get("name", "") or ""
    obj_type = p.get("object_type", "") or ""
    combined = f"{name} {obj_type}"

    if any(pat.lower() in combined.lower() for pat in KEEP_AS_PROXY):
        to_keep.append((gid, name))
        continue

    for pattern, target_class in RECLASSIFY_RULES:
        if pattern.lower() in combined.lower():
            to_reclassify[gid] = (target_class, name)
            break
    else:
        ungrouped.append((gid, name, obj_type))

print(f"\n    To reclassify:  {len(to_reclassify)}")
print(f"    Keep as proxy:  {len(to_keep)}")
print(f"    Needs review:   {len(ungrouped)}")

print("\n[2] Reclassification plan:")
for cls, count in sorted(Counter(c for c, _ in to_reclassify.values()).items()):
    print(f"    {cls}: {count} elements")

if ungrouped:
    print("\n    Ungrouped (numeric names) — inspecting first 3:")
    for gid, name, obj_type in ungrouped[:3]:
        try:
            psets = json.loads(get_entity_properties(FILE, gid)).get("property_sets", {})
            print(f"      [{gid}] name='{name}' psets={list(psets)[:3]}")
        except Exception as exc:
            print(f"      [{gid}] could not inspect: {exc}")

print("\n[3] Applying reclassifications (chaining output files)...")
current_file = FILE
success = 0
for gid, (target_class, name) in to_reclassify.items():
    res = json.loads(
        reclassify_element(
            file_path=current_file,
            global_id=gid,
            new_ifc_class=target_class,
            output_path=OUTPUT,
        )
    )
    if res.get("status") == "success":
        success += 1
        current_file = OUTPUT  # next reclassification builds on the last output
        print(f"  ok  {name[:50]} -> {target_class}")
    else:
        print(f"  ERR {name[:50]}: {res.get('message', '')}")

print("\n[4] Verifying output...")
if success:
    check = json.loads(run_specific_check(current_file, "proxy"))
    print(f"    Remaining proxies: {check.get('proxy_count', '?')}")
    print(f"    Check passed: {check.get('passed', False)}")

print("\n" + "=" * 70)
print(f"Reclassified {success} elements -> {OUTPUT}")
print(f"Kept as proxy (correct): {len(to_keep)} | Needs review: {len(ungrouped)}")
print("=" * 70)
