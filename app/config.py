from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (any OpenAI-compatible endpoint with tool calling)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_max_tool_rounds: int = 6

    # Hasura GraphQL endpoint (full URL including /v1/graphql)
    hasura_url: str = "http://localhost:8080/v1/graphql"
    hasura_admin_secret: str = "myadminsecret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
