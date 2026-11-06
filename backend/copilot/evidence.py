"""Find the résumé bullets that best support each job requirement (BM25 with tech synonyms)."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .resume import Resume

STOP = set("a an and are as at be by for from has have in into is it its of on or that the this to was with using used we you your our will can across over via per".split())

# Words that mean the same thing in job posts and résumés
SYNONYMS = {
    "llm": ["llms", "gemini", "genai", "rag", "agent"], "genai": ["llm", "llms", "rag"], "agentic": ["agent", "agents"],
    "ml": ["machine", "learning", "pytorch", "tensorflow"], "ai": ["llm", "rag", "agent", "ml"],
    "backend": ["api", "apis", "spring", "fastapi", "microservices", "kafka"], "frontend": ["react", "redux", "angular", "typescript"],
    "distributed": ["kafka", "microservices", "event-driven", "high-throughput"], "streaming": ["kafka", "event-driven"],
    "observability": ["elasticsearch", "kibana", "logging", "monitoring", "debugging"], "monitoring": ["observability", "elasticsearch"],
    "cloud": ["gcp", "aws"], "devops": ["ci/cd", "gitlab", "jenkins", "docker"], "ci": ["ci/cd", "gitlab", "pipelines"],
    "containers": ["docker"], "kubernetes": ["docker", "containerized"], "vector": ["faiss", "embeddings", "retrieval"],
    "search": ["retrieval", "elasticsearch", "faiss"], "nlp": ["ner", "bert", "transformers", "summarization"],
    "sql": ["mysql", "postgresql", "sqlite"], "database": ["mysql", "postgresql", "sql"], "payments": ["stripe"],
    "reliability": ["fault-tolerant", "zero-downtime", "sre"], "latency": ["ms", "performance"], "performance": ["latency", "caching", "redis"],
}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9+#/.-]+", text.lower().replace("’", "'")) if t not in STOP and len(t) > 1]


@dataclass(frozen=True)
class Match:
    bullet_id: str
    score: float


class EvidenceIndex:
    def __init__(self, resume: Resume, k1: float = 1.4, b: float = 0.75):
        self.resume = resume
        self.k1, self.b = k1, b
        self.docs: dict[str, list[str]] = {}
        for bid, bullet in resume.bullets.items():
            section = resume.section(bullet.section_id) or {}
            self.docs[bid] = tokens(bullet.text + " " + " ".join(section.get("tech", [])))
        self.avg = sum(map(len, self.docs.values())) / max(1, len(self.docs))
        df = Counter(t for d in self.docs.values() for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def expand(self, query: str) -> list[str]:
        q = tokens(query)
        return q + [s for t in q for s in SYNONYMS.get(t, [])]

    def search(self, query: str, k: int = 3) -> list[Match]:
        q = self.expand(query)
        scores = []
        for bid, doc in self.docs.items():
            tf = Counter(doc)
            s = 0.0
            for t in set(q):
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / self.avg))
            if s > 0:
                scores.append(Match(bid, round(s, 3)))
        return sorted(scores, key=lambda m: m.score, reverse=True)[:k]
