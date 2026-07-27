"""Configuration management for IFC Agent."""

from pathlib import Path
from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Supported LLM providers and their defaults
LLM_PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "supports_tools": True,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-3.5-sonnet",
        "supports_tools": True,
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-6",
        "supports_tools": True,
    },
}


@dataclass
class AgentConfig:
    """Central configuration for the IFC Intelligence Agent."""

    # Paths
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    workspace: Path = field(default=None)
    rules_dir: Path = field(default=None)
    reports_dir: Path = field(default=None)
    test_data_dir: Path = field(default=None)

    # MCP Server
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    # Privacy tier (1=fully local, 2=self-hosted cloud, 3=hybrid, 4=full cloud)
    privacy_tier: int = field(default_factory=lambda: int(os.environ.get("IFC_AGENT_PRIVACY_TIER", "2")))

    # LLM provider — auto-detect from available keys, allow explicit override
    llm_provider: str = field(default_factory=lambda: os.environ.get("IFC_AGENT_LLM_PROVIDER", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("IFC_AGENT_LLM_MODEL", ""))

    # Agent loop settings
    max_agent_steps: int = field(default_factory=lambda: int(os.environ.get("IFC_AGENT_MAX_STEPS", "15")))

    # Checker defaults
    default_checks: list = field(default_factory=lambda: [
        "schema", "ids", "spatial", "guid", "proxy", "type"
    ])

    def __post_init__(self):
        if self.workspace is None:
            self.workspace = Path(os.environ.get("IFC_AGENT_WORKSPACE", self.project_root / "gui_workspace"))
        if self.rules_dir is None:
            self.rules_dir = Path(os.environ.get("IFC_AGENT_RULES_DIR", self.project_root / "rules"))
        if self.reports_dir is None:
            self.reports_dir = Path(os.environ.get("IFC_AGENT_REPORTS_DIR", self.project_root / "reports"))
        if self.test_data_dir is None:
            self.test_data_dir = self.project_root / "tests" / "test_data"

        # Auto-detect provider from available API keys if not explicitly set
        if not self.llm_provider:
            if os.environ.get("ANTHROPIC_API_KEY"):
                self.llm_provider = "anthropic"
            elif os.environ.get("OPENROUTER_API_KEY"):
                self.llm_provider = "openrouter"
            elif os.environ.get("GROQ_API_KEY"):
                self.llm_provider = "groq"
            else:
                self.llm_provider = "groq"

        # Auto-set default model for provider if not explicitly set
        if not self.llm_model:
            provider_info = LLM_PROVIDERS.get(self.llm_provider, {})
            self.llm_model = provider_info.get("default_model", "llama-3.3-70b-versatile")

    def get_llm_base_url(self) -> str:
        return LLM_PROVIDERS.get(self.llm_provider, {}).get("base_url", "https://api.groq.com/openai/v1")

    def get_llm_api_key(self) -> str:
        env_key = LLM_PROVIDERS.get(self.llm_provider, {}).get("env_key", "GROQ_API_KEY")
        return os.environ.get(env_key, "")

    def validate(self) -> dict:
        """Return startup configuration status without requiring optional LLM keys."""
        warnings = []
        errors = []
        has_any_key = any(
            os.environ.get(p["env_key"]) for p in LLM_PROVIDERS.values()
        )
        if not has_any_key:
            warnings.append(
                "No LLM API key found. Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY in your .env file."
            )
        if not self.rules_dir.exists():
            errors.append(f"Rules directory not found: {self.rules_dir}")
        return {
            "ok": not errors,
            "warnings": warnings,
            "errors": errors,
            "provider": self.llm_provider,
            "model": self.llm_model,
        }


# Global config singleton
config = AgentConfig()
