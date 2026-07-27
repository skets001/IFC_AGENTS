"""Strict LLM metadata inference designed for extracting values directly from context without hallucination."""

import os
import json
from openai import OpenAI
from ifc_agent.config import config

SYSTEM_PROMPT = """You are a highly analytical BIM Metadata Extractor operating in strict descriptive mode.
You are given JSON metadata pertaining to an IFC architectural/mechanical element.
Often, crucial parameters like Manufacturer, Model Reference, and Barcode/Asset labels are loosely typed into raw "Name" or "Description" fields.
Your goal is to extract these properties directly from the source strings, filling standardized 'Pset_ManufacturerTypeInformation' slots.

RULES:
1. ONLY populate a field if the context strongly implies the value mathematically or historically within the text strings.
2. DO NOT hallucinate fake company names, dates, or model numbers if they are totally absent. Leave them as null.
3. Return ONLY valid JSON in the structure shown below:

{
  "Manufacturer": "Extracted string or null",
  "ModelReference": "Extracted string or null",
  "ArticleNumber": "Extracted string or null",
  "ModelLabel": "Extracted string or null",
  "AssemblyPlace": "Extracted string or null"
}
"""

def extract_cobie_parameters(element_metadata: dict) -> dict:
    """Pass element data to the local Groq LLM to safely map standard implicit COBie values."""
    if config.llm_provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        base_url = "https://api.groq.com/openai/v1"
        if not api_key:
            raise ValueError("GROQ_API_KEY env missing.")
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY env missing.")

    client = OpenAI(base_url=base_url, api_key=api_key)

    response = client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(element_metadata, indent=2)}
        ],
        temperature=0.0
    )

    content = response.choices[0].message.content.strip()

    import re
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        content = match.group(1)
    else:
        # Fallback if no markdown block was used but it contains the brackets
        match = re.search(r"(\{.*?\})", content, re.DOTALL)
        if match:
            content = match.group(1)

    try:
        return json.loads(content)
    except Exception:
        return {}
