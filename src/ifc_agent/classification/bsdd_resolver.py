"""AI Classification Engine logic with bSDD alignment."""

import os
import json
from openai import OpenAI
from ifc_agent.config import config

SYSTEM_PROMPT = """You are a Building Information Modeling (BIM) AI Classifier.
Your task is to infer the correct standard IFC entity type for a given element proxy.
You will be provided with a JSON representing the metadata (Name, Description, Properties) of an IfcBuildingElementProxy.
Analyze the name, description, and attached properties. 
Return exactly the most appropriate IFC class to substitute it with (e.g., 'IfcWall', 'IfcDoor', 'IfcPump', 'IfcFurniture', 'IfcSensor').
Provide only valid JSON in the following format, with no markdown code blocks:

{
  "inferred_class": "IfcClass"
}
"""

def infer_class(proxy_metadata: dict) -> str:
    """Pass proxy metadata to Groq to guess the real IFC classification."""
    
    # Provider mapping
    if config.llm_provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        base_url = "https://api.groq.com/openai/v1"
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is missing. Add it to .env.")
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is missing. Add it to .env.")

    client = OpenAI(base_url=base_url, api_key=api_key)

    response = client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(proxy_metadata, indent=2)}
        ],
        temperature=0.0
    )

    content = response.choices[0].message.content.strip()
    
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    try:
        data = json.loads(content)
        return data.get("inferred_class", "IfcBuildingElementProxy")
    except json.JSONDecodeError as e:
        # Fallback to the original proxy if classification goes completely wrong
        return "IfcBuildingElementProxy"
