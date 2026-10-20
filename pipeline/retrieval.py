"""KB indexing and top-k retrieval (DESIGN §6.2, SPEC §7.7).

Two retrievers share one contract:

* ``EmbeddingRetriever`` (default): OpenAI embeddings via LiteLLM, cosine similarity. Works across
  languages (an es/fr/de/pt ticket matches the English KB). Every vector is cached by content hash,
  so reruns are byte-identical, and only PII-masked text is ever sent (rule P-EXT).
* ``TfidfRetriever``: pure-Python TF-IDF, fully offline. Used with the ``stub`` provider and in tests.

Both report, per candidate, the lexical terms that overlap with the query and the best-matching
KB sentence, so ``retrieval_debug.json`` explains every ranking.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipeline import pii
from pipeline.cache import JsonCache
from pipeline.io_utils import sha256_canonical, sha256_text
from pipeline.schemas import KBArticle, NormalisedTicket, RetrievalResult, RetrievedArticle

RETRIEVAL_VERSION = "retrieval.v1"

FIELD_WEIGHTS = {"title": 3, "category": 2, "content": 1}
SUBJECT_WEIGHT = 2
TOP_TERMS = 5

_STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be because been before being both but by can
    cannot could did do does doesn doing don each for from had has have having he her here hers him his how
    i if in into is it its just me more most my myself no nor not now of off on once only or other our ours
    out over own please same she should so some such than that the their them then there these they this
    those through to too under until up very was we were what when where which while who whom why will with
    would you your yours yourself yesterday today now one""".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class EmbeddingError(RuntimeError):
    """The embedding API failed after retries (auth, network, quota). Fatal (exit 2)."""


class PIILeakError(RuntimeError):
    """Raw PII reached a component that sends text to an external API (P-EXT). Always a bug."""


# --- Text processing ------------------------------------------------------------------------------


def fold(text: str) -> str:
    """Lower-case and strip accents: ``Contraseña`` -> ``contrasena``."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def stem(token: str) -> str:
    """Light, deterministic suffix stripping: charge/charges/charged/charging -> ``charg``."""
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    for suffix in ("ing", "ed"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)]
            break
    if len(token) > 3 and token.endswith("e"):
        token = token[:-1]
    return token


def tokens(text: str) -> list[str]:
    text = pii.PLACEHOLDER_RE.sub(" ", text)
    return [stem(tok) for tok in _TOKEN_RE.findall(fold(text)) if tok not in _STOPWORDS and len(tok) > 1]


def features(text: str) -> list[str]:
    """Unigrams plus adjacent bigrams of stemmed tokens."""
    toks = tokens(text)
    return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def article_lexical_text(article: KBArticle) -> str:
    category = article.category.replace("_", " ")
    return " ".join(
        [article.title] * FIELD_WEIGHTS["title"] + [category] * FIELD_WEIGHTS["category"] + [article.content]
    )


def article_embedding_text(article: KBArticle) -> str:
    return f"{article.title}. {article.category}. {article.content}"


def ticket_lexical_text(ticket: NormalisedTicket) -> str:
    return " ".join([ticket.subject] * SUBJECT_WEIGHT + [ticket.message])


def ticket_embedding_text(ticket: NormalisedTicket) -> str:
    return ". ".join(part for part in (ticket.subject, ticket.message) if part)


# --- TF-IDF ---------------------------------------------------------------------------------------


class TfidfIndex:
    """Sublinear-tf, smoothed-idf, L2-normalised TF-IDF over unigrams + bigrams."""

    def __init__(self, documents: dict[str, str]) -> None:
        self.doc_features = {doc_id: Counter(features(text)) for doc_id, text in documents.items()}
        df: Counter[str] = Counter()
        for counts in self.doc_features.values():
            df.update(counts.keys())
        n_docs = len(documents)
        self.idf = {term: math.log((1 + n_docs) / (1 + count)) + 1 for term, count in sorted(df.items())}
        self.doc_vectors = {doc_id: self._weigh(counts) for doc_id, counts in self.doc_features.items()}

    def _weigh(self, counts: Counter[str]) -> dict[str, float]:
        weights = {t: (1 + math.log(c)) * self.idf[t] for t, c in sorted(counts.items()) if t in self.idf}
        norm = math.sqrt(sum(w * w for w in weights.values()))
        return {t: w / norm for t, w in weights.items()} if norm else {}

    def query_vector(self, text: str) -> dict[str, float]:
        return self._weigh(Counter(features(text)))

    def score(self, query: dict[str, float], doc_id: str) -> tuple[float, list[tuple[str, float]]]:
        doc = self.doc_vectors.get(doc_id, {})
        contributions = sorted(
            ((term, weight * doc[term]) for term, weight in query.items() if term in doc),
            key=lambda item: (-item[1], item[0]),
        )
        return sum(c for _, c in contributions), contributions

    @property
    def vocabulary_size(self) -> int:
        return len(self.idf)


# --- Embeddings -----------------------------------------------------------------------------------


class Embedder(Protocol):
    provider: str
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LiteLLMEmbedder:
    """OpenAI embeddings through LiteLLM. Needs ``OPENAI_API_KEY`` in the environment."""

    provider = "openai"

    def __init__(self, model: str, timeout_s: int = 60) -> None:
        self.model = model
        self.timeout_s = timeout_s

    def embed(self, texts: list[str]) -> list[list[float]]:
        import litellm  # imported lazily: offline (tfidf) runs never load it

        try:
            response = litellm.embedding(model=self.model, input=texts, timeout=self.timeout_s, num_retries=3)
        except Exception as exc:  # LiteLLM raises provider-specific types; surface one clear error
            raise EmbeddingError(f"embedding call to {self.model} failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        rows = sorted(response.data, key=lambda row: row["index"] if isinstance(row, dict) else row.index)
        return [row["embedding"] if isinstance(row, dict) else row.embedding for row in rows]


@dataclass
class CachedEmbedder:
    """Content-addressed vector cache + call log around an ``Embedder``.

    Refuses any text containing raw PII, so masking can't be bypassed on the way to the API.
    Texts already embedded in this run are served from memory and logged only once.
    """

    inner: Embedder
    cache: JsonCache
    clock: Callable[[], str]
    log: list[dict[str, Any]] = field(default_factory=list)
    api_calls: int = 0
    _memo: dict[str, list[float]] = field(default_factory=dict, repr=False)

    def embed(self, texts: list[str], purpose: str) -> list[list[float]]:
        for text in texts:
            if pii.contains_pii(text):
                raise PIILeakError(f"refusing to embed text containing raw PII ({purpose})")
        keys = [sha256_text(text) for text in texts]
        vectors: dict[str, list[float]] = {k: self._memo[k] for k in keys if k in self._memo}
        already_logged = set(vectors)
        cached: set[str] = set()
        for key in keys:
            if key in vectors:
                continue
            hit = self.cache.get("embeddings", self.inner.model, key)
            if hit is not None:
                vectors[key] = hit
                cached.add(key)
        missing = list(dict.fromkeys(k for k in keys if k not in vectors))
        if missing:
            by_key = {key: text for key, text in zip(keys, texts)}
            self.api_calls += 1
            for key, vector in zip(missing, self.inner.embed([by_key[k] for k in missing])):
                vectors[key] = vector
                self.cache.put(vector, "embeddings", self.inner.model, key)
        self._memo.update(vectors)
        timestamp = self.clock()
        for key, text in dict(zip(keys, texts)).items():
            if key in already_logged:
                continue
            already_logged.add(key)
            self.log.append(
                {
                    "timestamp": timestamp,
                    "purpose": purpose,
                    "provider": self.inner.provider,
                    "model": self.inner.model,
                    "text_hash": "sha256:" + key,
                    "chars": len(text),
                    "cached": key in cached,
                }
            )
        return [vectors[key] for key in keys]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


# --- Retrievers -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    article_id: str
    title: str
    score: float
    lexical_score: float
    top_terms: list[tuple[str, float]]
    best_snippet: str


class Retriever(Protocol):
    method: str
    articles: list[KBArticle]

    def candidates(self, ticket: NormalisedTicket) -> list[Candidate]: ...

    def describe(self) -> dict[str, Any]: ...


def _best_lexical_sentence(article: KBArticle, query_features: set[str]) -> str:
    """Content sentence with the most query overlap; the title when only the title matched."""
    best, best_overlap = "", 0
    for sentence in [*split_sentences(article.content), article.title]:
        overlap = len(query_features & set(features(sentence)))
        if overlap > best_overlap:
            best, best_overlap = sentence, overlap
    return best


class TfidfRetriever:
    method = "tfidf"

    def __init__(self, articles: list[KBArticle]) -> None:
        self.articles = articles
        self.index = TfidfIndex({a.article_id: article_lexical_text(a) for a in articles})

    def candidates(self, ticket: NormalisedTicket) -> list[Candidate]:
        query_text = ticket_lexical_text(ticket)
        query = self.index.query_vector(query_text)
        query_features = set(features(query_text))
        found = []
        for article in self.articles:
            score, contributions = self.index.score(query, article.article_id)
            if score > 0:
                found.append(
                    Candidate(
                        article_id=article.article_id,
                        title=article.title,
                        score=round(min(score, 1.0), 4),
                        lexical_score=round(min(score, 1.0), 4),
                        top_terms=[(t, round(c, 4)) for t, c in contributions[:TOP_TERMS]],
                        best_snippet=_best_lexical_sentence(article, query_features),
                    )
                )
        return found

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "ngram_range": [1, 2],
            "field_weights": FIELD_WEIGHTS,
            "subject_weight": SUBJECT_WEIGHT,
            "vocabulary_size": self.index.vocabulary_size,
        }


class EmbeddingRetriever:
    method = "embedding"

    def __init__(self, articles: list[KBArticle], embedder: CachedEmbedder) -> None:
        self.articles = articles
        self.embedder = embedder
        self.lexical = TfidfRetriever(articles)  # explains rankings with overlapping terms
        self.article_vectors = dict(
            zip(
                [a.article_id for a in articles],
                embedder.embed([article_embedding_text(a) for a in articles], purpose="kb_article"),
            )
        )
        self.sentences = {a.article_id: split_sentences(a.content) for a in articles}
        flat = [s for a in articles for s in self.sentences[a.article_id]]
        vectors = iter(embedder.embed(flat, purpose="kb_sentence") if flat else [])
        self.sentence_vectors = {a.article_id: [next(vectors) for _ in self.sentences[a.article_id]] for a in articles}

    def prefetch(self, tickets: list[NormalisedTicket]) -> None:
        """Embed many ticket queries in one API call (results are memoised for ``candidates``)."""
        texts = [t for t in (ticket_embedding_text(ticket) for ticket in tickets) if t.strip()]
        if texts and self.articles:
            self.embedder.embed(texts, purpose="ticket")

    def candidates(self, ticket: NormalisedTicket) -> list[Candidate]:
        query_text = ticket_embedding_text(ticket)
        if not query_text.strip() or not self.articles:
            return []  # nothing to embed: an empty ticket matches nothing (and costs no API call)
        query = self.embedder.embed([query_text], purpose="ticket")[0]
        lexical = {c.article_id: c for c in self.lexical.candidates(ticket)}
        found = []
        for article in self.articles:
            score = round(max(0.0, min(cosine(query, self.article_vectors[article.article_id]), 1.0)), 4)
            if score <= 0:
                continue
            sentence_scores = [cosine(query, v) for v in self.sentence_vectors[article.article_id]]
            snippet = ""
            if sentence_scores:
                best = max(range(len(sentence_scores)), key=lambda i: (sentence_scores[i], -i))
                snippet = self.sentences[article.article_id][best]
            lex = lexical.get(article.article_id)
            found.append(
                Candidate(
                    article_id=article.article_id,
                    title=article.title,
                    score=score,
                    lexical_score=lex.lexical_score if lex else 0.0,
                    top_terms=lex.top_terms if lex else [],
                    best_snippet=snippet,
                )
            )
        return found

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "provider": self.embedder.inner.provider,
            "model": self.embedder.inner.model,
            "article_text": "title. category. content",
            "query_text": "subject. message (PII-masked)",
            "explanation": "top_terms = lexical TF-IDF overlap; best_snippet = KB sentence with the highest embedding similarity",
            "embedding_dims": len(next(iter(self.article_vectors.values()), [])),
        }


# --- Ranking --------------------------------------------------------------------------------------


def query_terms(ticket: NormalisedTicket) -> list[str]:
    return list(dict.fromkeys(tokens(ticket_lexical_text(ticket))))


def retrieve(
    retriever: Retriever, ticket: NormalisedTicket, top_k: int, min_score: float
) -> tuple[RetrievalResult, dict[str, Any]]:
    """Rank all candidates (score desc, article_id asc), keep the top_k at or above min_score."""
    ranked = sorted(retriever.candidates(ticket), key=lambda c: (-c.score, c.article_id))
    kept_ids = {c.article_id for c in ranked[:top_k] if c.score >= min_score}
    result = RetrievalResult(
        ticket_id=ticket.ticket_id,
        retrieved_articles=[
            RetrievedArticle(article_id=c.article_id, score=c.score, title=c.title)
            for c in ranked
            if c.article_id in kept_ids
        ],
    )
    debug: dict[str, Any] = {
        "ticket_id": ticket.ticket_id,
        "query_terms": query_terms(ticket),
        "candidates": [
            {
                "article_id": c.article_id,
                "rank": rank,
                "score": c.score,
                "lexical_score": c.lexical_score,
                "kept": c.article_id in kept_ids,
                "top_terms": [{"term": t, "contribution": w} for t, w in c.top_terms],
                "best_snippet": c.best_snippet,
            }
            for rank, c in enumerate(ranked, start=1)
        ],
    }
    if not kept_ids:
        debug["note"] = (
            "empty ticket: nothing to match"
            if ticket.insufficient_content
            else f"no article reached min_score {min_score}"
        )
    return result, debug


def kb_hash(articles: list[KBArticle]) -> str:
    return "sha256:" + sha256_canonical([a.model_dump(mode="json") for a in articles])


def build_retriever(
    method: str, articles: list[KBArticle], embedder: CachedEmbedder | None = None
) -> TfidfRetriever | EmbeddingRetriever:
    if method == "tfidf":
        return TfidfRetriever(articles)
    if method == "embedding":
        if embedder is None:
            raise ValueError("embedding retrieval needs an embedder")
        return EmbeddingRetriever(articles, embedder)
    raise ValueError(f"unknown retriever {method!r}")
