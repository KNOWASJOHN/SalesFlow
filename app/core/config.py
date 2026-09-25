from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str

    # ------------------------------------------------------------------
    # WebRTC signaling (Module 4)
    # ------------------------------------------------------------------
    # Shared HS256 secret used to verify the `access_token` query parameter
    # presented during the /ws/signaling handshake. Tokens are minted by the
    # same identity layer that issues REST credentials; the payload carries
    # {"sub": "<customer_id|employee_id>", "role": "customer|employee",
    #  "aud": SIGNALING_JWT_AUDIENCE, "exp": <unix timestamp>}.
    # Optional so the app still boots when signaling is not configured — the
    # endpoint then refuses every socket with AUTH_FAILED.
    SIGNALING_JWT_SECRET: str | None = None
    SIGNALING_JWT_ALGORITHM: str = "HS256"
    SIGNALING_JWT_AUDIENCE: str = "sales-signaling"
    
    # Pydantic Settings V2 requires this config to load from .env
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
