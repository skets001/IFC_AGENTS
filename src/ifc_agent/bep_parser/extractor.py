"""LLM Extraction Engine. Uses OpenRouter to parse BEP text into a YAML rule pack."""

import os
import json
import yaml
from pathlib import Path
from openai import OpenAI
from ifc_agent.config import config

# The prompt used to extract BIM requirements into structured JSON
SYSTEM_PROMPT = """You are an expert BIM Manager and IFC Specialist. 
Analyze the provided BIM Execution Plan (BEP) extract. 
Identify all IFC specifications, property requirements, and naming conventions.

Extract the rules into the following exact JSON structure, returning ONLY valid JSON:
{
  "project_name": "Name of the project if mentioned",
  "rules": [
    {
      "name": "A short descriptive name for this rule (e.g. 'Wall Naming Convention')",
      "description": "Description of what this rule does",
      "applicable_entities": ["IFCWALL", "IFCDOOR", "..."],
      "requirements": [
        {
          "type": "attribute",
          "name": "Name",
          "expected_pattern": "^Wall-.*" // Optional regex
        },
        {
          "type": "property",
          "property_set": "Pset_WallCommon",
          "name": "FireRating",
          "expected_value": "REI60" // Optional strict value
        }
      ]
    }
  ]
}

Only return the raw JSON object. Do not wrap in markdown ```json blocks.
Be comprehensive but explicit.
"""

def extract_rules_to_yaml(bep_text: str, output_yaml_path: str | Path | None = None) -> dict:
    """Run LLM extraction on the text and output a YAML rule pack."""
    
    if config.llm_provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        base_url = "https://api.groq.com/openai/v1"
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is missing.")
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is missing.")

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
    )

    response = client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Here is the BEP context:\n\n{bep_text}"}
        ],
        temperature=0.0
    )

    content = response.choices[0].message.content.strip()
    
    # Clean possible markdown block if LLM ignored strict instructions
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse LLM structured output as JSON: {e}\n\n{content}")

    # Write to YAML if a path is provided
    if output_yaml_path:
        out_path = Path(output_yaml_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open('w', encoding='utf-8') as f:
            # We enforce standard python dictionary to yaml mapping
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return data
