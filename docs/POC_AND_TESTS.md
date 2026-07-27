# PoC & Tests

What we actually ran, and how it's tested.

---

## The proof-of-concept

**Goal:** take a real, dirty architectural IFC and let the agent make it more digital-twin-ready by correcting mis-exported proxy elements — end to end, with the model choosing and verifying its own actions.

**Input (internal model, not shipped):** an IFC4 architectural model (~460k entities, ~109k GlobalIds, ~6.4k elements). A baseline check found it otherwise healthy except:

- **48 `IfcBuildingElementProxy`** elements in **19 name-groups**, e.g.
  - `Steel Platform` (structural decking) · `Steel Post` · `Metal Ladder` · `Wall Sweep / Tile base` · `Lighting Switches`
  - landscape/annotation families: `RPC Tree` (trees) · `Massing` · `Logo Family` · `Model Text` · `Generic Models`
  - ~18 elements with **numeric-only names** (need inspection)
- **9 elements with no type assignment** (ramp flights, roofs, a slab)

**The correction rules the PoC applied:**

| Proxy pattern | Action | Target class | Why |
|---------------|--------|--------------|-----|
| Steel Platform | reclassify | `IfcSlab` | structural platform/decking |
| Steel Post | reclassify | `IfcColumn` | vertical structural member |
| Metal Ladder | reclassify | `IfcStairFlight` | circulation/access |
| Wall Sweep / Tile base | reclassify | `IfcCovering` | architectural finish |
| Lighting Switch | reclassify | `IfcSwitchingDevice` | electrical control |
| Trees / Massing / Logo / Model Text / Generic | **keep as proxy** | — | no standard IFC class; not a physical asset |
| Numeric-name-only | **review** | — | inspect properties before deciding |

This "reclassify the confident ones, keep genuine placeholders, flag the rest for humans" policy is the important part — the agent is **not** allowed to force every proxy into a class. Mutations always went to a **new** `_corrected.ifc`; the source was never overwritten.

### Two ways we ran it

| Script | Decision-maker | Point |
|--------|----------------|-------|
| `poc/run_agent_poc.py` | **LLM agent** | The model plans, calls `get_proxies` / `reclassify_element` / `run_specific_check`, and verifies the proxy count dropped — the full agentic loop with a printed tool trace. |
| `poc/reclassify_proxies_poc.py` | **Hard-coded rules** | Same tools, same outcome, but the mapping is Python. Proves the IfcOpenShell tool layer stands alone and gives a deterministic baseline to compare the agent against. |

Run either against the synthetic fixture (no internal model needed):

```bash
# deterministic
python poc/reclassify_proxies_poc.py tests/test_data/demo_model.ifc

# agentic (needs an LLM key in .env)
python poc/run_agent_poc.py tests/test_data/demo_model.ifc
```

> The synthetic `demo_model.ifc` is tiny (a wall, a door, a proxy), so it demonstrates the *mechanics*. The scale story (48 proxies across 19 groups) comes from the internal model, which is intentionally excluded.

### Reference scripts (`poc/scripts/`)

Parameterized, argparse-driven building blocks used during the PoC — all non-destructive (source → new output + JSON/CSV audit):

- `generate_proxy_proposal.py` — turn a proxy audit into a reclassify/skip/review proposal (with confidence + rationale).
- `tag_proxy_reclassification_proposals.py` — write proposals into the IFC as `Pset_IFCAgentProxyReview` properties (advisory, non-mutating).
- `apply_proxy_group.py` / `apply_proxy_target.py` — apply one group / one target class at a time.
- `correct_skets_ifc.py` — a full combined pass (dedupe GUIDs + reclassify proxies) with an audit trail.
- `fix_duplicate_guids.py` — regenerate duplicate GlobalIds into a copy.

---

## Tests

Run everything with:

```bash
pytest
```

All fixtures are created **programmatically with IfcOpenShell** or are tiny synthetic files — **no API key and no external/client IFC is required.**

| Test file | Verifies |
|-----------|----------|
| `tests/test_checker.py` | All 6 checks + the runner. Builds a clean model and a deliberately-broken model (orphan beam, `FCU-01` proxy, untyped column, duplicate GUID) and asserts each check detects the right issues; asserts IDS validation writes JSON/HTML/CSV/summary reports. |
| `tests/test_classification.py` | `classify_and_mutate` turns an `IfcBuildingElementProxy` into an `IfcPump` while preserving its name — the safe reassignment. |
| `tests/test_enrichment.py` | `evaluate_and_inject` writes `Manufacturer`/`ModelReference` into `Pset_ManufacturerTypeInformation` without breaking the model. |
| `tests/test_bep_parser.py` | `compile_yaml_to_ids` turns a YAML rule pack into a valid 2-spec IDS (wall fire rating + door naming). |
| `tests/test_mcp_server.py` | The MCP model-cache LRU evicts the oldest entry at capacity. |
| `tests/test_validation_store.py` | The SQLite store round-trips models / runs / normalized issues. |

These are the "tests we did" — together they cover the tool layer end to end (detect → classify → enrich → compile → persist → serve), which is exactly what the agent orchestrates.

> The GUI/API test (`test_gui_api.py` in the parent repo) is intentionally **excluded** here, since this bundle drops the web layer.
