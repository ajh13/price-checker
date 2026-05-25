from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    rapidapi_key: SecretStr
    rapidapi_host: str = "ebay-average-selling-price.p.rapidapi.com"
    ebay_max_results: int = 120
    ebay_concurrency_limit: int = 1
    ebay_rate_limit: float = 1.0  # max requests per second
    cache_ttl_hours: float = 24.0
    cache_dir: str = ".cache"
    low_data_threshold: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


def get_settings() -> Settings:
    return settings
