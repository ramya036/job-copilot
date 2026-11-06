"""Résumé data model. Every bullet has a stable id so tailored bullets can cite their source."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_RESUME = Path(__file__).parent / "resume_ramya.json"


@dataclass(frozen=True)
class Bullet:
    id: str
    text: str
    section_id: str  # experience or project id


@dataclass
class Resume:
    raw: dict
    bullets: dict[str, Bullet] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_RESUME) -> "Resume":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict) -> "Resume":
        r = cls(raw=data)
        seen = set()
        for section in data.get("experience", []) + data.get("projects", []):
            for b in section["bullets"]:
                if b["id"] in seen:
                    raise ValueError(f"Duplicate bullet id {b['id']}")
                seen.add(b["id"])
                r.bullets[b["id"]] = Bullet(b["id"], b["text"], section["id"])
        return r

    @property
    def name(self) -> str:
        return self.raw["name"]

    def sections(self) -> list[dict]:
        return self.raw.get("experience", []) + self.raw.get("projects", [])

    def section(self, section_id: str) -> dict | None:
        return next((s for s in self.sections() if s["id"] == section_id), None)

    def all_skills(self) -> list[str]:
        return [s for group in self.raw.get("skills", {}).values() for s in group]

    def corpus(self) -> str:
        """All the text the résumé contains, used to check that tailored text adds nothing new."""
        parts = [self.raw.get("summary", ""), self.raw.get("headline", "")] + self.all_skills()
        for s in self.sections():
            parts += [s.get("company", s.get("name", "")), s.get("title", ""), s.get("subtitle", "")] + s.get("tech", [])
            parts += [b["text"] for b in s["bullets"]]
        return " \n".join(parts)

    def outline(self) -> str:
        """Compact text the model sees: every section and bullet with its id."""
        lines = []
        for s in self.sections():
            head = f"{s.get('company', s.get('name'))} — {s.get('title', s.get('subtitle', ''))} [{s['id']}]"
            lines.append(head)
            lines += [f"  ({b['id']}) {b['text']}" for b in s["bullets"]]
        lines.append("Skills: " + ", ".join(self.all_skills()))
        return "\n".join(lines)
