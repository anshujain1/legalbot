"""End-to-end pipeline: analyse query -> retrieve -> generate -> verify citations."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .concordance import Concordance
from .context import ContextExpander, ExpansionConfig
from .config import Settings, get_settings
from .embeddings import get_embedder
from .generate import INSUFFICIENT, LLM, SYSTEM_PROMPT, build_prompt, get_llm
from .query import QueryAnalyzer, QueryPlan
from .registry import ActRegistry
from .rerank import CrossEncoderReranker
from .retrieval import Mode, Retriever
from .schema import Hit, SearchFilters
from .store import QdrantStore
from .verify import normalize_citations, verify

DISCLAIMER = "This is general legal information from the indexed texts, not legal advice. Check the current official text and consult a lawyer."


class LLMNotConfigured(RuntimeError):
    pass


class Source(BaseModel):
    chunk_id: str  # stable id: use as a React key
    label: str  # citation label, e.g. "BNS §103"
    act_id: str  # e.g. "bns": pass to GET /sections/{act_id}/{section_no}
    act: str  # full act name
    status: str  # "in_force" | "repealed" | ...
    year: int | None
    section_no: str | None
    section_title: str | None
    chapter: str | None
    clause_range: str | None  # set when a long section was split, e.g. "(1)–(3)"
    part: str  # "1/3": which part of a split section this chunk is
    text: str
    source: str  # "dense" | "sparse" | "hybrid" | "lookup" (pinned: user named the section) | "sibling" | "xref" | "definition" (context added after ranking)
    via: str | None = None  # why a sibling/xref/definition is here, e.g. "BNS §103"
    score: float


class Answer(BaseModel):
    question: str
    answer: str
    insufficient: bool = False
    verified: bool
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


def to_source(hit: Hit) -> Source:
    c = hit.chunk
    chapter = None
    if c.chapter_no:
        chapter = f"Chapter {c.chapter_no}" + (f": {c.chapter_title}" if c.chapter_title else "")
    return Source(
        chunk_id=c.chunk_id,
        label=c.label,
        act_id=c.act_id,
        act=c.act_name,
        status=c.status.value,
        year=c.year,
        section_no=c.section_no,
        section_title=c.section_title,
        chapter=chapter,
        clause_range=c.clause_range,
        part=f"{c.part_index + 1}/{c.part_count}",
        text=c.text,
        source=hit.source,
        via=hit.via,
        score=round(hit.score, 5),
    )


class LegalBot:
    def __init__(
        self,
        store: QdrantStore,
        registry: ActRegistry,
        concordance: Concordance,
        llm: LLM | None = None,
        retriever: Retriever | None = None,
        settings: Settings | None = None,
        expander: ContextExpander | None = None,
    ):
        self.store = store
        self.registry = registry
        self.concordance = concordance
        self.llm = llm
        self.settings = settings or store.settings
        self.retriever = retriever or Retriever(store)
        self.analyzer = QueryAnalyzer(registry, concordance)
        self.expander = expander or ContextExpander(store, registry)

    def search(
        self,
        question: str,
        filters: SearchFilters | None = None,
        k: int | None = None,
        mode: Mode = "hybrid",
        use_lookup: bool = True,
    ) -> tuple[QueryPlan, list[Hit]]:
        plan = self.analyzer.plan(question)
        active = filters if filters is not None and not filters.is_empty() else plan.filters
        hits = self.retriever.search(
            plan.search_query,
            active,
            k or self.settings.top_k,
            mode,
            plan.explicit_sections if use_lookup else None,
        )
        return plan, hits

    def ask(
        self, question: str, filters: SearchFilters | None = None, k: int | None = None, expand: bool = True
    ) -> Answer:
        if self.llm is None:
            raise LLMNotConfigured("No LLM configured. Set GROQ_API_KEY (and install '.[llm]').")

        plan, hits = self.search(question, filters, k)
        only_deleted = bool(plan.removed_refs) and set(plan.explicit_sections) <= set(plan.removed_refs)
        if only_deleted:  # the question is about a deleted section: answer from the table, never let the model guess a successor
            return Answer(
                question=question,
                answer=" ".join(n.split(" Do not present")[0] for n in plan.notes if "has no equivalent" in n),  # drop the sentence meant for the model
                insufficient=False,
                verified=True,
                notes=plan.notes,
            )
        if not hits:
            return Answer(
                question=question,
                answer="No relevant provisions were found in the indexed corpus.",
                insufficient=True,
                verified=True,
                notes=plan.notes,
            )

        if expand:  # siblings, cross-references, definitions: context for the model, not part of the ranking
            hits = self.expander.expand(hits)
        prompt = build_prompt(question, hits, plan.notes)
        text = normalize_citations(self.llm.complete(SYSTEM_PROMPT, prompt), self.registry)
        check = verify(text, hits, self.registry, plan.mapped_refs)

        if not check.ok:  # one corrective retry, then surface the problem instead of hiding it
            problems = (
                "it cited sections that are not in the sources: "
                + ", ".join(f"{a.upper()} §{s}" for a, s in check.unsupported)
                if check.unsupported
                else "it contained no citations"
            )
            retry = (
                f"{prompt}\n\nYour previous answer was rejected because {problems}.\n"
                f"Previous answer:\n{text}\n\nRewrite it using only the sources and their exact labels."
            )
            text = normalize_citations(self.llm.complete(SYSTEM_PROMPT, retry), self.registry)
            check = verify(text, hits, self.registry, plan.mapped_refs)

        warnings: list[str] = []
        if check.unsupported:
            warnings.append(
                "Unverified citations: " + ", ".join(f"{a.upper()} §{s}" for a, s in check.unsupported)
            )
        elif not check.ok:
            warnings.append("The answer contains no citations to the retrieved sources.")
        if any(not m.verified for m in self.concordance.rows if (m.old_act, m.old_section) in plan.mapped_refs):
            warnings.append("An IPC<->BNS mapping used here is unverified; confirm against the official comparison table.")

        insufficient = check.insufficient
        answer_text = text.strip()[len(INSUFFICIENT):].strip() if insufficient else text.strip()
        return Answer(
            question=question,
            answer=answer_text,
            insufficient=insufficient,
            verified=check.ok,
            warnings=warnings,
            notes=plan.notes,
            sources=[to_source(h) for h in hits],
        )


def build_bot(settings: Settings | None = None) -> LegalBot:
    settings = settings or get_settings()
    registry = ActRegistry.load()
    store = QdrantStore(settings, get_embedder(settings))
    reranker = CrossEncoderReranker(settings.reranker_model) if settings.reranker_model else None
    return LegalBot(
        store=store,
        registry=registry,
        concordance=Concordance.load(),
        llm=get_llm(settings),
        retriever=Retriever(store, reranker),
        settings=settings,
    )
