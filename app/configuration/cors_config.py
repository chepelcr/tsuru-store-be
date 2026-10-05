"""SSM-controlled origin list with the store API's existing first-party policy."""
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from app.configuration.app_config import AppConfig


def configure_cors(app: FastAPI) -> None:
    raw = AppConfig.get_key("cors.allowed-origins", "*,https://uploads.tsuru.jcampos.dev")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r"^https://([a-z0-9-]+\.)*jcampos\.dev$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=600,
    )
