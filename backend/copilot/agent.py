"""The tailoring agent.

    read job ─▶ extract requirements ─▶ find evidence per requirement
                                           │
                     ┌──── draft tailored résumé ◀────┐
                     ▼                                 │ problems found
                truth checks (code) ── problems? ──────┘ (up to MAX_REVISIONS)
                     │ none
                     ▼
              coverage report + export

Every step emits an event so the UI can show what the agent is doing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from .checks import Problem, check_draft, make_safe, tech_in
from .evidence import EvidenceIndex
from .llm import LLM
from .resume import Resume

MAX_REVISIONS = 2
Emit = Callable[[dict], None]

EXTRACT_PROMPT = """STEP: extract_requirements
You read job descriptions for a software engineer. Return JSON:
{{"title": str, "company": str or null,
  "requirements": [{{"text": short requirement, "importance": "must" or "nice", "keywords": [2-5 lowercase terms]}}]}}
List 5 to 12 concrete requirements (skills, experience, responsibilities). Skip benefits and boilerplate.

JOB DESCRIPTION:
{job}
"""

DRAFT_PROMPT = """STEP: draft
You tailor a real résumé to a job. You may REORDER, SELECT and REWORD. You must NEVER add facts.
Rules:
- Every bullet cites the résumé bullet ids it is based on in "source_ids" (same role or project only).
- Use only numbers, tools and technologies that appear in the cited bullets. Do not invent metrics.
- Use the job's wording where it truthfully describes the same work.
- Put the most relevant bullets first in each section and the most relevant sections first.
- Keep each bullet under 240 characters. Include 1-3 bullets per section; drop irrelevant sections.
- "skills": pick and order up to 14 skills, only from the résumé's skill list.
- "summary": 2 sentences for this job, using only facts from the résumé.
Return JSON: {{"summary": str, "skills": [str], "sections": [{{"id": section id, "bullets": [{{"text": str, "source_ids": [str]}}]}}]}}

JOB: {title} at {company}
REQUIREMENTS AND THE RÉSUMÉ EVIDENCE FOUND FOR EACH:
{evidence}

RÉSUMÉ (ids in brackets and parentheses):
{resume}
{feedback}"""


@dataclass
class Requirement:
    text: str
    importance: str
    keywords: list[str]
    evidence: list[dict] = field(default_factory=list)  # [{bullet_id, score, text}]
    related: list[dict] = field(default_factory=list)   # close but not the named technology

    @property
    def met(self) -> bool:
        return bool(self.evidence)


@dataclass
class Result:
    title: str
    company: str | None
    requirements: list[Requirement]
    draft: dict
    revisions: int
    notes: list[str]
    problems_fixed: list[dict]

    def coverage(self) -> dict:
        must = [r for r in self.requirements if r.importance == "must"]
        used = {sid for s in self.draft["sections"] for b in s["bullets"] for sid in b["source_ids"]}
        shown = [r for r in self.requirements if any(e["bullet_id"] in used for e in r.evidence)]
        return {
            "requirements": len(self.requirements),
            "with_evidence": sum(r.met for r in self.requirements),
            "shown_in_resume": len(shown),
            "must_have_gaps": [r.text for r in must if not r.met],
        }

    def to_dict(self) -> dict:
        return {
            "title": self.title, "company": self.company,
            "requirements": [r.__dict__ | {"met": r.met} for r in self.requirements],
            "draft": self.draft, "revisions": self.revisions, "notes": self.notes,
            "problems_fixed": self.problems_fixed, "coverage": self.coverage(),
        }


class TailorAgent:
    def __init__(self, llm: LLM, resume: Resume, emit: Emit | None = None):
        self.llm, self.resume = llm, resume
        self.index = EvidenceIndex(resume)
        self.emit = emit or (lambda e: None)

    def step(self, name: str, status: str, message: str, **data) -> None:
        self.emit({"step": name, "status": status, "message": message, **({"data": data} if data else {})})

    # --- steps -------------------------------------------------------------
    def extract(self, job_text: str) -> tuple[str, str | None, list[Requirement]]:
        self.step("extract", "running", "Reading the job description")
        out = self.llm.json(EXTRACT_PROMPT.format(job=job_text[:12000]))
        reqs = [Requirement(r["text"], "must" if r.get("importance") == "must" else "nice", [k.lower() for k in r.get("keywords", [])])
                for r in out.get("requirements", []) if r.get("text")]
        if not reqs:
            raise ValueError("Couldn't find any requirements in that job description")
        must = sum(r.importance == "must" for r in reqs)
        self.step("extract", "done", f"Found {len(reqs)} requirements ({must} must-have)",
                  title=out.get("title"), company=out.get("company"), requirements=[r.text for r in reqs])
        return out.get("title") or "this role", out.get("company"), reqs

    def gather(self, reqs: list[Requirement]) -> None:
        self.step("evidence", "running", "Searching your résumé for evidence")
        known_tech = tech_in(self.resume.corpus())
        for r in reqs:
            matches = self.index.search(r.text + " " + " ".join(r.keywords), k=3)
            top = matches[0].score if matches else 0
            r.evidence = [{"bullet_id": m.bullet_id, "score": m.score, "text": self.resume.bullets[m.bullet_id].text}
                          for m in matches if m.score >= max(1.5, 0.5 * top)]
            missing = tech_in(r.text) - known_tech
            if missing and not (tech_in(r.text) & known_tech):
                r.related, r.evidence = r.evidence, []  # e.g. "Kubernetes" when the résumé only has Docker
        met = sum(r.met for r in reqs)
        self.step("evidence", "done", f"Found evidence for {met} of {len(reqs)} requirements",
                  gaps=[r.text for r in reqs if not r.met])

    def draft(self, title: str, company: str | None, reqs: list[Requirement], problems: list[Problem], previous: dict | None) -> dict:
        evidence = "\n".join(
            f"- [{r.importance}] {r.text} -> " + (", ".join(e["bullet_id"] for e in r.evidence) or "NO EVIDENCE (do not claim it)")
            for r in reqs)
        feedback = ""
        if problems:
            feedback = ("\nYOUR PREVIOUS DRAFT FAILED THESE CHECKS. Fix every one; if a claim can't be supported, remove it:\n"
                        + "\n".join(f"- {p.where}: {p.detail}" for p in problems)
                        + "\nPREVIOUS DRAFT:\n" + json.dumps(previous, ensure_ascii=False))
        out = self.llm.json(DRAFT_PROMPT.format(title=title, company=company or "the company", evidence=evidence,
                                                resume=self.resume.outline(), feedback=feedback))
        return {"summary": out.get("summary", ""), "skills": out.get("skills", []),
                "sections": [{"id": s.get("id"), "bullets": s.get("bullets", [])} for s in out.get("sections", [])]}

    # --- loop --------------------------------------------------------------
    def run(self, job_text: str) -> Result:
        title, company, reqs = self.extract(job_text)
        self.gather(reqs)

        problems: list[Problem] = []
        fixed: list[dict] = []
        draft: dict | None = None
        revisions = 0
        for attempt in range(MAX_REVISIONS + 1):
            label = "Drafting your tailored résumé" if attempt == 0 else f"Revising (round {attempt})"
            self.step("draft", "running", label)
            draft = self.draft(title, company, reqs, problems, draft)
            self.step("draft", "done", ("Draft ready" if attempt == 0 else f"Revised draft ready (round {attempt})") + f": {sum(len(s['bullets']) for s in draft['sections'])} bullets in {len(draft['sections'])} sections")

            self.step("check", "running", "Checking every line against your real résumé")
            problems = check_draft(draft, self.resume)
            if not problems:
                self.step("check", "done", "All lines trace back to your résumé")
                break
            fixed += [p.to_dict() for p in problems]
            self.step("check", "failed", f"Found {len(problems)} problem{'s' * (len(problems) != 1)}", problems=[p.to_dict() for p in problems])
            revisions = attempt + 1 if attempt < MAX_REVISIONS else revisions

        notes: list[str] = []
        if problems:
            draft, notes = make_safe(draft, self.resume)
            self.step("check", "done", "Replaced the remaining problem lines with your original wording", notes=notes)

        result = Result(title, company, reqs, draft, revisions, notes, fixed)
        cov = result.coverage()
        self.step("done", "done", f"Tailored for {title}" + (f" at {company}" if company else ""), coverage=cov)
        return result
