"""Agentic tool-use loop for the IFC Intelligence / Hermes agent.

This implements a proper multi-turn tool-call loop that:
1. Gives the LLM a full set of IFC tool definitions
2. Executes any tool calls the LLM requests
3. Feeds results back until the LLM returns a final answer
4. Returns a structured response with full reasoning trace

Supports OpenRouter and Groq via the OpenAI-compatible API.
Tools are implemented as local Python callables that mirror the MCP server tools,
so the agent works without needing the MCP server to be running.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element

from ifc_agent.config import config
from ifc_agent.ifc_utils import by_guid

MAX_AGENT_STEPS = int(os.environ.get("IFC_AGENT_MAX_STEPS", "15"))
LLM_TIMEOUT = float(os.environ.get("IFC_AGENT_LLM_TIMEOUT_SECONDS", "60"))

# ── Tool definitions (OpenAI function-calling format) ─────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "load_model",
            "description": "Load an IFC file and return schema, entity count, project name, and type breakdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the IFC file."},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entities",
            "description": "Get all entities of a given IFC class (e.g. IfcWall, IfcDoor, IfcPump).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "ifc_class": {"type": "string", "description": "IFC class name."},
                },
                "required": ["file_path", "ifc_class"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_properties",
            "description": "Get all property sets, type info, spatial container, and classification references for an element by GlobalId.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "global_id": {"type": "string", "description": "GlobalId of the entity."},
                },
                "required": ["file_path", "global_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spatial_tree",
            "description": "Get the full spatial hierarchy (Site > Building > Storey > Space) with element counts.",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_elements",
            "description": "Search elements by name, description, or ObjectType substring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "query": {"type": "string", "description": "Search term."},
                    "ifc_class": {"type": "string", "description": "Optional IFC class filter."},
                },
                "required": ["file_path", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_baseline_check",
            "description": "Run all 6 baseline quality checks: schema, IDS, spatial containment, GUID uniqueness, proxy detection, type assignments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "output_format": {"type": "string", "enum": ["json", "html"], "description": "Output format."},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_specific_check",
            "description": "Run a single quality check: schema | ids | spatial | guid | proxy | type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "check_name": {"type": "string", "enum": ["schema", "ids", "spatial", "guid", "proxy", "type"]},
                    "ids_path": {"type": "string", "description": "Path to IDS file (only for 'ids' check)."},
                },
                "required": ["file_path", "check_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proxies",
            "description": "List all IfcBuildingElementProxy elements with metadata for reclassification.",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orphan_elements",
            "description": "Find elements with no spatial containment (not assigned to any storey or space).",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_ifc_files",
            "description": "Compare two IFC files and report added, deleted, modified, and moved elements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path_a": {"type": "string", "description": "Baseline IFC file (original)."},
                    "file_path_b": {"type": "string", "description": "Revised IFC file (updated)."},
                },
                "required": ["file_path_a", "file_path_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fix_guid_duplicates",
            "description": "Find and fix all duplicate GlobalIds by assigning new valid GUIDs. Saves a new IFC file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "output_path": {"type": "string", "description": "Output file path. Leave empty for auto."},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reclassify_element",
            "description": "Change the IFC class of an element (e.g. IfcBuildingElementProxy → IfcPump). Saves a new IFC file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "global_id": {"type": "string"},
                    "new_ifc_class": {"type": "string", "description": "Target IFC class."},
                    "new_name": {"type": "string", "description": "Optional new Name for the element."},
                    "output_path": {"type": "string"},
                },
                "required": ["file_path", "global_id", "new_ifc_class"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_or_update_pset",
            "description": "Add or update a property set on one or more elements. Saves a new IFC file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "global_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of element GlobalIds to update.",
                    },
                    "pset_name": {"type": "string", "description": "Property set name."},
                    "properties": {
                        "type": "object",
                        "description": "Dict of property name → value.",
                        "additionalProperties": {"type": "string"},
                    },
                    "output_path": {"type": "string"},
                },
                "required": ["file_path", "global_ids", "pset_name", "properties"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_to_spatial_container",
            "description": "Move an element into a spatial container (storey or space). Saves a new IFC file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "global_id": {"type": "string"},
                    "container_global_id": {"type": "string", "description": "GlobalId of the target storey or space."},
                    "output_path": {"type": "string"},
                },
                "required": ["file_path", "global_id", "container_global_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_classification_reference",
            "description": "Add a bSDD/Uniclass/OmniClass classification reference to one or more elements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "global_ids": {"type": "array", "items": {"type": "string"}},
                    "classification_system": {"type": "string", "description": "e.g. 'Uniclass 2015'"},
                    "identification": {"type": "string", "description": "Classification code e.g. 'Ss_65_10_95'"},
                    "class_name": {"type": "string", "description": "Human-readable class name."},
                    "output_path": {"type": "string"},
                },
                "required": ["file_path", "global_ids", "classification_system", "identification", "class_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch_set",
            "description": "Apply a list of structured patch operations to an IFC file in one batch. Operations: set_property, set_name, set_object_type, set_description, add_classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "patches": {
                        "type": "array",
                        "description": "List of patch operations.",
                        "items": {"type": "object"},
                    },
                    "output_path": {"type": "string"},
                },
                "required": ["file_path", "patches"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bsdd_search_classes",
            "description": "Search the buildingSMART Data Dictionary for classes matching a term.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "dictionary_uri": {"type": "string", "description": "Optional URI to limit search to one dictionary."},
                    "language_code": {"type": "string", "description": "Language code, default EN."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bsdd_get_class",
            "description": "Get full class definition from bSDD including required properties and relations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_uri": {"type": "string", "description": "Full bSDD URI for the class."},
                    "language_code": {"type": "string"},
                },
                "required": ["class_uri"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bsdd_list_dictionaries",
            "description": "List available bSDD dictionaries (Uniclass, OmniClass, IFC, etc.).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_ids_specs",
            "description": "List all specifications in an IDS file with their applicability and requirements.",
            "parameters": {
                "type": "object",
                "properties": {"ids_path": {"type": "string"}},
                "required": ["ids_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_ids_spec",
            "description": "Validate an IFC file against IDS specifications. Optionally filter to one spec by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "ids_path": {"type": "string"},
                    "spec_name": {"type": "string", "description": "Specific spec name, or empty for all specs."},
                },
                "required": ["file_path", "ids_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_classify_proxies",
            "description": "Classify all IfcBuildingElementProxy elements using LLM inference + bSDD cross-check.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enrich_cobie_data",
            "description": "Harvest incomplete FM elements and inject missing COBie properties (Manufacturer, Model, etc.) via LLM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
]


# ── Local tool implementations (mirror MCP tools) ──────────────────────────────

def _dispatch_tool(name: str, args: dict) -> str:
    """Dispatch a tool call to its local implementation. Returns JSON string."""
    from ifc_agent.mcp_server import server as mcp_server

    tool_fn = getattr(mcp_server, name, None)
    if tool_fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    # FastMCP may wrap the function; try __wrapped__ fallback
    callable_fn = getattr(tool_fn, "__wrapped__", tool_fn)
    if not callable(callable_fn):
        callable_fn = tool_fn

    try:
        result = callable_fn(**args)
        # Ensure we always return a string
        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)
    except TypeError as e:
        return json.dumps({"error": f"Tool call error for {name}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Tool execution error for {name}: {e}"})


# ── Agent loop ─────────────────────────────────────────────────────────────────

def _build_client():
    """Build an OpenAI-compatible client for the configured LLM provider."""
    from ifc_agent.config import LLM_PROVIDERS
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    provider = config.llm_provider
    api_key = config.get_llm_api_key()

    # Fall back through available providers
    if not api_key:
        for p_name, p_info in LLM_PROVIDERS.items():
            candidate_key = os.environ.get(p_info["env_key"], "")
            if candidate_key:
                provider = p_name
                api_key = candidate_key
                break

    if not api_key:
        raise RuntimeError(
            "No LLM API key found. Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY in your .env file."
        )

    base_url = LLM_PROVIDERS[provider]["base_url"] if provider in LLM_PROVIDERS else "https://api.groq.com/openai/v1"
    model = config.llm_model

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed. Run: pip install openai") from exc

    extra_headers = {}
    if provider == "anthropic":
        extra_headers = {"anthropic-version": "2023-06-01"}

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=LLM_TIMEOUT,
        default_headers=extra_headers if extra_headers else None,
    )
    return client, model, provider


def run_agent_loop(
    prompt: str,
    system_prompt: str,
    file_path: Optional[str] = None,
    hermes_profile: Optional[dict] = None,
    max_steps: int = MAX_AGENT_STEPS,
    context: Optional[dict] = None,
) -> dict[str, Any]:
    """Run the Hermes agentic tool-use loop.

    The agent receives the user prompt and a full set of IFC tool definitions.
    It can call tools iteratively, receiving results after each call, until it
    produces a final answer or reaches max_steps.

    Args:
        prompt: User's natural language request.
        system_prompt: System prompt (includes Hermes profile instructions).
        file_path: Optional IFC file in context.
        hermes_profile: Optional Hermes agent profile dict.
        max_steps: Maximum tool-call iterations before forcing a final answer.
        context: Optional additional context dict injected into first message.

    Returns:
        Dict with: ok, answer, tool_calls (trace), steps, provider, agent.
    """
    client, model, provider = _build_client()

    # Build the initial user message
    context_text = ""
    if context:
        context_text = f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}\n"
    if file_path:
        context_text += f"\n\nActive IFC file: {file_path}\n"

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context_text}\n\nUser request: {prompt}"},
    ]

    tool_call_trace: list[dict] = []
    steps = 0
    final_answer = ""

    while steps < max_steps:
        steps += 1
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=2000,
            )
        except Exception as e:
            # Fallback: some providers don't support tool_choice="auto"
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000,
                )
            except Exception as e2:
                return {
                    "ok": False,
                    "error": str(e2),
                    "answer": f"LLM call failed: {e2}",
                    "tool_calls": tool_call_trace,
                    "steps": steps,
                    "provider": provider,
                }

        choice = response.choices[0]
        msg = choice.message

        # Append assistant message to history
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        # If no tool calls, we have a final answer
        if not tool_calls:
            final_answer = msg.content or ""
            break

        # Execute each tool call and append results
        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            t_start = time.time()
            result_str = _dispatch_tool(fn_name, fn_args)
            t_elapsed = round(time.time() - t_start, 2)

            # Truncate large results to avoid context overflow
            if len(result_str) > 8000:
                result_data = json.loads(result_str) if result_str.startswith(("{", "[")) else {"raw": result_str}
                result_str = json.dumps(_truncate_tool_result(result_data), default=str)

            tool_call_trace.append({
                "step": steps,
                "tool": fn_name,
                "args": fn_args,
                "elapsed_s": t_elapsed,
                "result_preview": result_str[:500],
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

        # If stop_reason is 'stop' after tool calls, one more LLM pass
        if choice.finish_reason == "stop":
            break

    # If we hit max_steps without a final answer, ask the model for a summary
    if not final_answer and steps >= max_steps:
        messages.append({
            "role": "user",
            "content": "You have reached the maximum number of tool calls. Please provide your final answer and recommendations based on the information gathered so far.",
        })
        try:
            summary_response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=2000,
            )
            final_answer = summary_response.choices[0].message.content or ""
        except Exception:
            final_answer = "Analysis complete. See tool call trace for details."

    return {
        "ok": True,
        "answer": final_answer,
        "tool_calls": tool_call_trace,
        "steps": steps,
        "provider": provider,
        "model": model,
        "agent": hermes_profile["id"] if hermes_profile else "hermes_orchestrator",
        "agent_label": hermes_profile["label"] if hermes_profile else "Hermes Orchestrator",
    }


def _truncate_tool_result(data: Any, max_list_items: int = 20) -> Any:
    """Recursively truncate large lists/dicts to keep context manageable."""
    if isinstance(data, list):
        truncated = [_truncate_tool_result(item) for item in data[:max_list_items]]
        if len(data) > max_list_items:
            truncated.append({"_truncated": f"... {len(data) - max_list_items} more items"})
        return truncated
    if isinstance(data, dict):
        return {k: _truncate_tool_result(v) for k, v in data.items()}
    return data


# ── System prompt builders ─────────────────────────────────────────────────────

def build_bim_team_system_prompt(hermes_profile: Optional[dict] = None, mode: str = "general") -> str:
    """Build the system prompt for the Hermes BIM team agent."""
    base = """You are the Hermes BIM Intelligence Agent — an expert AI BIM team member that can:
- Query and analyze IFC files (entities, properties, spatial hierarchy, classifications)
- Run quality checks (schema, IDS, spatial containment, GUID uniqueness, proxies, type assignments)
- Compare IFC files to find differences (diff)
- Patch and correct IFC files (fix GUIDs, reclassify elements, add properties, move elements)
- Look up classification standards in bSDD (buildingSMART Data Dictionary)
- Create and validate IDS requirement specifications
- Enrich models with COBie FM data
- Classify proxy elements with correct IFC classes

You work like a BIM team member: you break tasks into steps, call the right tools, analyze results, and provide clear recommendations with specific element GlobalIds, property names, and file paths.

When modifying an IFC file, always:
1. First query the current state to understand what needs changing
2. Confirm what changes are needed
3. Apply changes via the appropriate patch/mutation tool
4. Report the output file path and what was changed

Be specific: cite GlobalIds, IFC classes, property set names, and exact values.
Think step by step. If you need more information, call the appropriate query tool first."""

    if hermes_profile:
        base += f"""

You are operating as: {hermes_profile['label']}
Role: {hermes_profile['role']}
Mission: {hermes_profile['mission']}

Focus areas:
{chr(10).join(f"- {focus}" for focus in hermes_profile.get('specialist_focus', []))}

Allowed actions:
{chr(10).join(f"- {action}" for action in hermes_profile.get('allowed_actions', []))}"""

    mode_instructions = {
        "check": "\n\nFocus on quality checking: run baseline checks, IDS validation, and report all issues with severity and remediation steps.",
        "classify": "\n\nFocus on classification: find proxy elements, check bSDD for correct classes, reclassify elements, and add classification references.",
        "enrich": "\n\nFocus on data enrichment: check COBie completeness, identify missing FM properties, and inject data where possible.",
        "diff": "\n\nFocus on model comparison: identify what changed between model versions, summarize impact, and flag regressions.",
        "patch": "\n\nFocus on corrections: identify issues, plan patches, apply them in batch, and confirm the output.",
        "ids": "\n\nFocus on IDS requirements: list existing specs, validate against them, identify gaps, and recommend new requirements.",
    }
    base += mode_instructions.get(mode, "")
    return base
