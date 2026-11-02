"""The FastAPI app: `uvicorn api.main:create_app --factory`.

create_app() wires the store and the sign-in verifier from the environment
(GCP_PROJECT_ID, BIGQUERY_DATASET, SEASON, OIDC_ISSUER / OIDC_AUDIENCE or
DEV_AUTH_EMAIL locally); tests pass their own.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import auth
from api import store as store_module
from api.routes import account, leagues, trades


def create_app(store=None, verifier=None, env=os.environ) -> FastAPI:
    app = FastAPI(title="League Lab API", version="0.1.0",
                  description="League Lab's API for the React app.")  # fmt: skip
    app.state.store = store if store is not None else store_module.from_env(env)
    app.state.verifier = verifier if verifier is not None else auth.from_env(env)
    origins = [o for o in env.get("WEB_ORIGINS", "").split(",") if o]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"],
                           allow_headers=["authorization", "content-type"])  # fmt: skip
    for router in (account.router, leagues.router, trades.router):
        app.include_router(router, prefix="/api")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    return app
