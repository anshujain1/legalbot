"""FastAPI app. Run with:  uvicorn legalbot.api:create_app --factory"""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import __version__
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


def create_app(bot: LegalBot | None = None) -> FastAPI:
    app = FastAPI(title="LegalBot", version=__version__)
    app.state.bot = bot

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

    @app.get("/acts")
    def acts() -> list[dict]:
        return [
            {"act_id": a.act_id, "name": a.name, "short": a.short, "year": a.year, "status": a.status.value}
            for a in get_bot().registry.all()
        ]

    @app.post("/search", response_model=SearchResponse)
    def search(req: SearchRequest) -> SearchResponse:
        plan, hits = get_bot().search(req.query, req.filters, req.k, req.mode)
        return SearchResponse(plan=plan, results=[to_source(h) for h in hits])

    @app.post("/ask", response_model=Answer)
    def ask(req: AskRequest) -> Answer:
        try:
            return get_bot().ask(req.question, req.filters, req.k)
        except LLMNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/sections/{act_id}/{section_no}", response_model=list[Source])
    def section(act_id: str, section_no: str) -> list[Source]:
        bot = get_bot()
        if act_id not in bot.registry:
            raise HTTPException(status_code=404, detail=f"Unknown act '{act_id}'")
        hits = bot.store.lookup(act_id, section_no)
        if not hits:
            raise HTTPException(status_code=404, detail=f"{act_id.upper()} section {section_no} not found in corpus")
        return [to_source(h) for h in hits]

    return app
