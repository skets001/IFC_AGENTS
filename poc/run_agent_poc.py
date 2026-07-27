"""PoC: drive the Hermes agentic tool-use loop over a real IFC model.

This is the demonstration we ran internally: the LLM is given the IFC tool
set and asked to reclassify mis-exported `IfcBuildingElementProxy` elements to
correct IFC classes, then re-check its own work — a full plan → tool-call →
observe → correct → verify loop.

The original run used an internal SKETS architectural model (~460k entities)
that is NOT shipped in this repo. Point IFC_MODEL_PATH at any IFC4 file to
reproduce, e.g. the synthetic fixture in tests/test_data/demo_model.ifc.

Usage:
    export GROQ_API_KEY=...            # or OPENROUTER_API_KEY / ANTHROPIC_API_KEY
    export IFC_MODEL_PATH=/path/to/model.ifc
    python poc/run_agent_poc.py
    # or: python poc/run_agent_poc.py /path/to/model.ifc
"""
import os
import sys
import json

sys.path.insert(0, "src")

from ifc_agent.agent_loop import run_agent_loop, build_bim_team_system_prompt
from ifc_agent.hermes_profiles import get_hermes_profile

# Model under analysis — supplied via CLI arg or IFC_MODEL_PATH env var.
# The real PoC ran against an internal architectural model (not included).
FILE_PATH = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.environ.get("IFC_MODEL_PATH", "tests/test_data/demo_model.ifc")
)

# Example tasking — this mirrors the real correction brief we gave the agent.
# Baseline check first surfaced 48 IfcBuildingElementProxy elements in 19 groups
# plus a handful of untyped elements; the agent's job is to reclassify the
# clearly-identifiable proxies and leave genuine placeholders alone.
PROMPT = """
This is a real IFC4 architectural model. A baseline check found:
- Schema: IFC4 — OK
- GUIDs: unique — OK
- Spatial: all elements contained — OK
- PROXIES (FAIL): many IfcBuildingElementProxy elements grouped by name, e.g.
  Steel Platform, Steel Post, Metal Ladder, Wall Sweep / Tile base,
  Lighting Switches, plus landscape/annotation families (trees, massing,
  logo, model text) and some numeric-name-only elements.
- TYPE ASSIGNMENTS (FAIL): a few elements with no type.

Your task:
1. Call load_model to confirm the file loaded.
2. Call get_proxies to see all proxy metadata.
3. Reclassify the clearly identifiable proxies:
   - Steel Platform  -> IfcSlab   (structural platform)
   - Steel Post      -> IfcColumn
   - Metal Ladder    -> IfcStairFlight
   - Wall Sweep      -> IfcCovering
   - Lighting Switch -> IfcSwitchingDevice
   - Trees / Massing / Logo / Model Text / Generic Models -> keep as proxy
     (no standard IFC class; landscape/annotation)
   - Numeric-name-only -> call get_entity_properties on a sample first, then decide.
4. Use reclassify_element for each element that should change class.
5. After reclassifying, call run_specific_check with check_name="proxy" on the
   OUTPUT file to confirm the proxy count dropped.
6. Report exactly: which elements were reclassified, to which class, in which
   output file.
"""

profile = get_hermes_profile("hermes_orchestrator")
system_prompt = build_bim_team_system_prompt(profile, mode="patch")

print("=" * 70)
print("HERMES BIM AGENT — IFC PROXY CORRECTION WORKFLOW (PoC)")
print("=" * 70)
print(f"File: {FILE_PATH}")
print(f"Agent: {profile['label']}")
print()

result = run_agent_loop(
    prompt=PROMPT,
    system_prompt=system_prompt,
    file_path=FILE_PATH,
    hermes_profile=profile,
    max_steps=12,
)

print("\n" + "=" * 70)
print("TOOL CALL TRACE")
print("=" * 70)
for tc in result.get("tool_calls", []):
    args_preview = {k: str(v)[:60] for k, v in tc.get("args", {}).items()}
    print(f"\n[Step {tc['step']}] {tc['tool']}({json.dumps(args_preview)})")
    print(f"  -> {tc['result_preview'][:200]}")
    print(f"  elapsed: {tc['elapsed_s']}s")

print("\n" + "=" * 70)
print("AGENT FINAL ANSWER")
print("=" * 70)
print(result.get("answer", "No answer"))

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Steps taken: {result['steps']}")
print(f"Tool calls:  {len(result.get('tool_calls', []))}")
print(f"Provider:    {result['provider']} / {result.get('model', '')}")
print(f"Status:      {'OK' if result.get('ok') else 'ERROR: ' + result.get('error', '')}")
