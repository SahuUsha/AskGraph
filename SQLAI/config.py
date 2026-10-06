import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


class Settings:
    NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b")
    # Set CACHE_DB_URL in a repo-root `.env` file (never commit credentials).
    CACHE_DB_URL = os.getenv("CACHE_DB_URL", "")


settings = Settings()
