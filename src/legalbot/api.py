"""FastAPI app. Run with:  uvicorn legalbot.api:create_app --factory"""
from __future__ import annotations

import hmac
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings, get_settings
from .pipeline import Answer, LegalBot, LLMNotConfigured, Source, build_bot, to_source
from .query import QueryPlan
from .schema import SearchFilters


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    k: int = Field(default=8, ge=1, le=30)
    mode: Literal["hybrid", "dense", "sparse"] = "hybrid"
    filters: SearchFilters | None = None


class SearchResponse(BaseModel):
    plan: QueryPlan
    results: list[Source]


class AskRequest(BaseModel):
    question: str = Field(min_length=2)
    k: int = Field(default=8, ge=1, le=30)
    filters: SearchFilters | None = None


def create_app(bot: LegalBot | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="LegalBot", version=__version__)
    app.state.bot = bot

    # Browser frontends need CORS. Origins come from LEGALBOT_CORS_ORIGINS (comma-separated, exact origins).
    allow_all = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
        max_age=600,
    )

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        """If LEGALBOT_API_KEY is set, every route except /health needs a matching X-API-Key header."""
        if settings.api_key and not hmac.compare_digest((x_api_key or "").encode(), settings.api_key.encode()):
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")

    guarded = [Depends(require_key)]

    def get_bot() -> LegalBot:
        if app.state.bot is None:
            app.state.bot = build_bot()
        return app.state.bot

    @app.get("/health")
    def health() -> dict:
        info: dict = {"status": "ok", "version": __version__}
        if app.state.bot is not None:
            info["chunks"] = app.state.bot.store.count()
        return info

    @app.get("/acts", dependencies=guarded)
    def acts() -> list[dict]:
        return [
            {"act_id": a.act_id, "name": a.name, "short": a.short, "year": a.year, "status": a.status.value}
            for a in get_bot().registry.all()
        ]

    @app.post("/search", response_model=SearchResponse, dependencies=guarded)
    def search(req: SearchRequest) -> SearchResponse:
        plan, hits = get_bot().search(req.query, req.filters, req.k, req.mode)
        return SearchResponse(plan=plan, results=[to_source(h) for h in hits])

    @app.post("/ask", response_model=Answer, dependencies=guarded)
    def ask(req: AskRequest) -> Answer:
        try:
            return get_bot().ask(req.question, req.filters, req.k)
        except LLMNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/sections/{act_id}/{section_no}", response_model=list[Source], dependencies=guarded)
    def section(act_id: str, section_no: str) -> list[Source]:
        bot = get_bot()
        if act_id not in bot.registry:
            raise HTTPException(status_code=404, detail=f"Unknown act '{act_id}'")
        hits = bot.store.lookup(act_id, section_no)
        if not hits:
            raise HTTPException(status_code=404, detail=f"{act_id.upper()} section {section_no} not found in corpus")
        return [to_source(h) for h in hits]

    return app
