from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- database ---
    database_url: str = "postgresql+psycopg://peblo:peblo@localhost:5432/peblo"

    # --- auth ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # --- storage ---
    # "local" | "r2". Swapping backends is a one-line change here; see app/storage/.
    storage_backend: str = "local"
    storage_local_root: Path = Path("/data/storage")
    # Public base used to build browser-reachable URLs for locally stored objects.
    storage_public_base_url: str = "http://localhost:8000/media"

    # R2 / any S3-compatible endpoint. Unused when storage_backend == "local".
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_base_url: str = ""

    # --- content rules ---
    # reference.json is the single source of truth for sections/categories/languages
    # and artwork specs. It ships with the repo and is read at startup.
    reference_path: Path = Path("/seed/reference.json")
    seed_path: Path = Path("/seed/seed_shows.json")
    seed_assets_dir: Path = Path("/seed/assets")

    # --- catalogue ---
    catalog_key: str = "catalog/catalog.json"
    catalog_versions_prefix: str = "catalog/versions"

    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
