from pathlib import Path

from omegaconf import OmegaConf
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmbeddingConfig(BaseModel):
    model_name: str = Field(default="gemini-embedding-001")
    dimension: int = Field(default=3072)
    task_type: str = Field(default="RETRIEVAL_DOCUMENT")

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
        use_enum_values=True,
        populate_by_name=True,
        extra="forbid",
    )

    def model_post_init(self, __context):
        config = OmegaConf.load(Path(__file__).parent / "embedding.yaml")
        self.model_name = config.model_name
        self.dimension = config.dimension
        self.task_type = config.task_type


class LLMConfig(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
        use_enum_values=True,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )

    provider: str = Field(..., description="The provider of the LLM model")
    base_url: str | None = Field(
        default=None, description="The base URL of the LLM model"
    )
    model_name: str = Field(..., description="The name of the LLM model to use")
    temperature: float = Field(
        ..., ge=0.0, description="The temperature of the LLM model"
    )
    max_tokens: int = Field(
        ..., ge=0, description="The maximum number of tokens to generate"
    )
    api_key: str | None = Field(
        default=None, description="The API key of the LLM model"
    )
    model_kwargs: dict | None = Field(
        default=None, description="Extra kwargs forwarded to the model (e.g. thinking mode)"
    )

    # Models served by DeepSeek's own API require a non-default base_url (the
    # OpenAI provider would otherwise route to api.openai.com and fail at
    # runtime). Scope the check to the OpenAI provider + DeepSeek model names so
    # local deployments (e.g. ollama/llama.cpp serving deepseek-* with their own
    # endpoints) aren't falsely blocked at config-load time.
    _DEEPSEEK_MODEL_PREFIX = "deepseek"
    _OPENAI_PROVIDER = "openai"

    @model_validator(mode="after")
    def _validate_provider_base_url(self) -> "LLMConfig":
        model_lower = (self.model_name or "").lower()
        provider_lower = (self.provider or "").lower()
        needs_deepseek_base = (
            provider_lower == self._OPENAI_PROVIDER
            and model_lower.startswith(self._DEEPSEEK_MODEL_PREFIX)
        )
        if needs_deepseek_base and not self.base_url:
            raise ValueError(
                f"LLM model '{self.model_name}' is a DeepSeek model served via "
                "the OpenAI provider but `base_url` is not set. Set the "
                "LLM_BASE_URL environment variable (e.g. https://api.deepseek.com) "
                "or change `model_name`/`provider` in src/configs/llm.yaml."
            )
        return self
