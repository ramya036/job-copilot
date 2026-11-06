"""Truth checks: a tailored résumé may reword and reorder, but must never claim anything new.

Each tailored bullet must cite résumé bullets, and may only use numbers and
technologies that appear in those sources (or elsewhere in the résumé).
These checks are plain code, not a model, so they can't be talked out of a failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .resume import Resume

# Technologies a model might add to sound like a better fit. If one appears in a
# tailored line but nowhere in the résumé, that line is making something up.
TECH_TERMS = """
python java javascript typescript golang rust c++ c# scala kotlin ruby php sql
react redux angular vue svelte next.js node.js django flask fastapi spring
kafka rabbitmq redis mysql postgresql mongodb cassandra dynamodb elasticsearch snowflake bigquery hadoop airflow
aws gcp azure kubernetes docker terraform ansible jenkins gitlab github helm istio
pytorch tensorflow keras scikit-learn langchain llamaindex faiss pinecone hugging transformers bert gpt openai gemini
graphql grpc rest microservices kibana grafana prometheus datadog splunk opencv
""".split()
MAX_BULLET_CHARS = 260


@dataclass(frozen=True)
class Problem:
    where: str   # e.g. "google bullet 2" or "summary"
    kind: str    # unknown-source | new-number | new-technology | too-long | unknown-section | unknown-skill
    detail: str

    def to_dict(self) -> dict:
        return {"where": self.where, "kind": self.kind, "detail": self.detail}


NUMBER = re.compile(r"(?<![\w.])[~$]?\d[\d,.]*\s?(?:%|k\+?|m\+?|ms|x|hours?|days?|zones?|records?)?", re.I)


def numbers_in(text: str) -> set[str]:
    """Normalized numbers: '~80%' -> '80', '120K+' -> '120k', '0.72' -> '0.72'."""
    out = set()
    for m in NUMBER.finditer(text):
        v = re.sub(r"[~$,\s]", "", m.group(0).lower()).rstrip("+")
        v = re.sub(r"(%|ms|x|hours?|days?|zones?|records?)$", "", v)
        if v and v[0].isdigit():
            out.add(v.rstrip("."))
    return out


def tech_in(text: str) -> set[str]:
    low = " " + text.lower() + " "
    return {t for t in TECH_TERMS if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)}


def check_text(text: str, allowed_text: str, where: str, resume_corpus: str) -> list[Problem]:
    problems = []
    new_numbers = numbers_in(text) - numbers_in(allowed_text)
    if new_numbers:
        problems.append(Problem(where, "new-number", f"uses {', '.join(sorted(new_numbers))}, which its sources don't contain"))
    new_tech = tech_in(text) - tech_in(resume_corpus)
    if new_tech:
        problems.append(Problem(where, "new-technology", f"mentions {', '.join(sorted(new_tech))}, which isn't in the résumé"))
    return problems


def check_draft(draft: dict, resume: Resume) -> list[Problem]:
    corpus = resume.corpus()
    problems: list[Problem] = []

    problems += check_text(draft.get("summary", ""), corpus, "summary", corpus)

    known_skills = {s.lower() for s in resume.all_skills()}
    for s in draft.get("skills", []):
        if s.lower() not in known_skills:
            problems.append(Problem("skills", "unknown-skill", f"'{s}' isn't in the résumé's skills"))

    for section in draft.get("sections", []):
        src_section = resume.section(section.get("id", ""))
        if not src_section:
            problems.append(Problem(str(section.get("id")), "unknown-section", "this role or project isn't in the résumé"))
            continue
        for i, b in enumerate(section.get("bullets", []), 1):
            where = f"{section['id']} bullet {i}"
            ids = b.get("source_ids") or []
            sources = [resume.bullets[x] for x in ids if x in resume.bullets]
            if not ids or len(sources) != len(ids):
                problems.append(Problem(where, "unknown-source", f"cites {ids or 'nothing'}; every line must cite real résumé bullets"))
                continue
            if any(s.section_id != section["id"] for s in sources):
                problems.append(Problem(where, "unknown-source", "cites a bullet from a different role or project"))
            allowed = " ".join(s.text for s in sources) + " " + " ".join(src_section.get("tech", []))
            problems += check_text(b.get("text", ""), allowed, where, corpus)
            if len(b.get("text", "")) > MAX_BULLET_CHARS:
                problems.append(Problem(where, "too-long", f"{len(b['text'])} characters, keep it under {MAX_BULLET_CHARS}"))
    return problems


def make_safe(draft: dict, resume: Resume) -> tuple[dict, list[str]]:
    """Last resort after the revision rounds: swap any bullet that still fails for its original text,
    and drop anything that can't be traced. Returns the safe draft and notes on what was replaced."""
    notes = []
    corpus = resume.corpus()
    safe = {"summary": draft.get("summary", ""), "skills": [], "sections": []}
    if check_text(safe["summary"], corpus, "summary", corpus):
        safe["summary"] = resume.raw.get("summary", "")
        notes.append("Kept your original summary because the tailored one added claims.")
    known = {s.lower(): s for s in resume.all_skills()}
    safe["skills"] = [known[s.lower()] for s in draft.get("skills", []) if s.lower() in known]
    for section in draft.get("sections", []):
        src = resume.section(section.get("id", ""))
        if not src:
            continue
        bullets = []
        for b in section.get("bullets", []):
            ids = [x for x in (b.get("source_ids") or []) if x in resume.bullets and resume.bullets[x].section_id == src["id"]]
            if not ids:
                continue
            allowed = " ".join(resume.bullets[x].text for x in ids) + " " + " ".join(src.get("tech", []))
            if check_text(b.get("text", ""), allowed, "", corpus) or len(b.get("text", "")) > MAX_BULLET_CHARS:
                bullets.append({"text": resume.bullets[ids[0]].text, "source_ids": ids[:1]})
                notes.append(f"Used your original wording for a {src.get('company', src.get('name'))} bullet.")
            else:
                bullets.append({"text": b["text"], "source_ids": ids})
        safe["sections"].append({"id": src["id"], "bullets": bullets})
    return safe, notes
