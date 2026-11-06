"""Offline demo model: rule-based stand-in for Gemini so the app runs without an API key.

It reads requirement lines straight from the job post and keeps your original
bullet wording (no rewriting). The real tailoring needs GEMINI_API_KEY."""
from __future__ import annotations

import re

from .checks import tech_in
from .evidence import SYNONYMS, tokens
from .resume import Resume

NICE = re.compile(r"nice to have|bonus|plus|preferred", re.I)
HEADINGS = re.compile(r"^(requirements|qualifications|what you'?ll do|responsibilities|about|benefits)\b", re.I)


class DemoLLM:
    name = "Offline demo (no rewriting)"

    def __init__(self, resume: Resume):
        self.resume = resume

    def json(self, prompt: str) -> dict:
        step = prompt.split("\n", 1)[0].removeprefix("STEP:").strip()
        return self.extract(prompt) if step == "extract_requirements" else self.draft(prompt)

    def extract(self, prompt: str) -> dict:
        job = prompt.split("JOB DESCRIPTION:", 1)[1].strip()
        lines = [ln.strip() for ln in job.splitlines() if ln.strip()]
        title = lines[0] if lines else "this role"
        company = None
        if " - " in title or " at " in title:
            title, company = re.split(r" - | at ", title, maxsplit=1)
        reqs = []
        for ln in lines[1:]:
            if not re.match(r"^[-•*]\s+", ln) or HEADINGS.match(ln):
                continue
            text = re.sub(r"^[-•*]\s+", "", ln)
            kw = sorted(tech_in(text) | {t for t in tokens(text) if t in SYNONYMS})[:5]
            reqs.append({"text": NICE.sub("", text).strip(" :"), "importance": "nice" if NICE.search(text) else "must", "keywords": kw})
        return {"title": title.strip(), "company": company, "requirements": reqs[:12]}

    def draft(self, prompt: str) -> dict:
        block = prompt.split("FOR EACH:", 1)[1].split("RÉSUMÉ (", 1)[0]
        order: list[str] = []
        for ids in re.findall(r"-> (.+)", block):
            order += [i.strip() for i in ids.split(",") if i.strip() in self.resume.bullets and i.strip() not in order]
        sections: dict[str, list] = {}
        for bid in order:
            b = self.resume.bullets[bid]
            if len(sections.setdefault(b.section_id, [])) < 3:
                sections[b.section_id].append({"text": b.text, "source_ids": [bid]})
        wanted = block.lower()
        skills = sorted(self.resume.all_skills(), key=lambda s: s.lower() not in wanted)[:14]
        return {"summary": self.resume.raw.get("summary", ""), "skills": skills,
                "sections": [{"id": k, "bullets": v} for k, v in sections.items()]}
