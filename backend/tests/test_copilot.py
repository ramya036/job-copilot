import io
import json

import pytest
from fastapi.testclient import TestClient

from copilot.agent import MAX_REVISIONS, TailorAgent
from copilot.api import create_app
from copilot.checks import check_draft, make_safe, numbers_in, tech_in
from copilot.evidence import EvidenceIndex
from copilot.export import to_docx, to_pdf
from copilot.jobpost import _is_public, html_to_text
from copilot.llm import ScriptedLLM, parse_json
from copilot.resume import Resume

JOB = """Senior Backend Engineer, AI Platform - Acme Health
We're building LLM agents that help clinicians. You will:
- Build distributed backend services with Kafka and Spring Boot
- Ship RAG pipelines with vector search
- Own observability and on-call debugging
- Nice to have: Kubernetes, Go
"""

REQS = {
    "title": "Senior Backend Engineer, AI Platform",
    "company": "Acme Health",
    "requirements": [
        {"text": "Distributed backend services with Kafka", "importance": "must", "keywords": ["kafka", "distributed", "backend"]},
        {"text": "RAG pipelines with vector search", "importance": "must", "keywords": ["rag", "faiss", "retrieval"]},
        {"text": "Observability and debugging", "importance": "must", "keywords": ["observability", "logging", "debugging"]},
        {"text": "Kubernetes", "importance": "nice", "keywords": ["kubernetes", "k8s"]},
        {"text": "Go programming", "importance": "nice", "keywords": ["golang"]},
    ],
}

GOOD = {
    "summary": "Software engineer who builds AI agents, RAG systems and distributed backend services.",
    "skills": ["Python", "Apache Kafka", "RAG", "FAISS", "Elasticsearch", "Spring Boot"],
    "sections": [
        {"id": "verizon", "bullets": [
            {"text": "Architected fault-tolerant, distributed event-driven backend services on Kafka, achieving 99% message delivery accuracy.", "source_ids": ["verizon-1"]},
            {"text": "Built an observability platform on Elasticsearch for real-time log search, saving ~4 hours per debugging cycle.", "source_ids": ["verizon-2"]},
        ]},
        {"id": "gsu", "bullets": [
            {"text": "Shipped a RAG pipeline with FAISS vector search over 120K+ clinical records, improving retrieval relevance by 45%.", "source_ids": ["gsu-1"]},
        ]},
    ],
}

INVENTED = json.loads(json.dumps(GOOD))
INVENTED["sections"][0]["bullets"][0] = {
    "text": "Ran Kafka on Kubernetes for 10M events/day with 99.99% uptime.", "source_ids": ["verizon-1"]}
INVENTED["skills"].append("Kubernetes")


@pytest.fixture
def resume():
    return Resume.load()


def run(script, resume):
    llm = ScriptedLLM(script)
    events = []
    result = TailorAgent(llm, resume, emit=events.append).run(JOB)
    return result, events, llm


# --- résumé + evidence --------------------------------------------------------
def test_resume_loads_with_unique_ids(resume):
    assert len(resume.bullets) >= 15
    assert all(b.section_id for b in resume.bullets.values())
    with pytest.raises(ValueError):
        Resume.from_dict({"experience": [{"id": "a", "bullets": [{"id": "x", "text": "1"}, {"id": "x", "text": "2"}]}]})


def test_no_phone_number_in_resume(resume):
    import re
    assert not re.search(r"\d{3}[-. ]\d{3}[-. ]\d{4}", json.dumps(resume.raw))


def test_evidence_finds_the_right_bullets(resume):
    idx = EvidenceIndex(resume)
    assert idx.search("kafka event-driven distributed")[0].bullet_id == "verizon-1"
    assert idx.search("vector search retrieval rag")[0].bullet_id in {"gsu-1", "askdb-1"}
    assert idx.search("react frontend")[0].bullet_id == "verizon-3"


# --- checks -------------------------------------------------------------------
def test_number_and_tech_extraction():
    assert numbers_in("cut time by ~80% across 130+ zones, 120K+ rows, F1 0.72") == {"80", "130", "120k", "0.72"}
    assert tech_in("Built on Kafka and Kubernetes with React") == {"kafka", "kubernetes", "react"}
    assert "go" not in tech_in("helped the team go faster")


def test_good_draft_passes(resume):
    assert check_draft(GOOD, resume) == []


def test_invented_claims_are_caught(resume):
    kinds = {p.kind for p in check_draft(INVENTED, resume)}
    assert {"new-number", "new-technology", "unknown-skill"} <= kinds


def test_citations_must_be_real_and_same_section(resume):
    bad = {"summary": "", "skills": [], "sections": [
        {"id": "google", "bullets": [{"text": "Did things", "source_ids": ["nope-1"]},
                                     {"text": "Built Kafka systems", "source_ids": ["verizon-1"]}]},
        {"id": "made-up-co", "bullets": [{"text": "x", "source_ids": []}]}]}
    kinds = [p.kind for p in check_draft(bad, resume)]
    assert kinds.count("unknown-source") == 2 and "unknown-section" in kinds


def test_make_safe_falls_back_to_original_wording(resume):
    safe, notes = make_safe(INVENTED, resume)
    assert check_draft(safe, resume) == []
    assert safe["sections"][0]["bullets"][0]["text"] == resume.bullets["verizon-1"].text
    assert "Kubernetes" not in safe["skills"] and notes


# --- agent loop ---------------------------------------------------------------
def test_full_run_with_clean_draft(resume):
    result, events, llm = run({"extract_requirements": REQS, "draft": GOOD}, resume)
    assert result.revisions == 0 and result.notes == []
    cov = result.coverage()
    assert cov["requirements"] == 5 and cov["must_have_gaps"] == []
    gaps = [r.text for r in result.requirements if not r.met]
    assert "Go programming" in gaps and "Kubernetes" in gaps  # honest: not on the résumé
    k8s = next(r for r in result.requirements if r.text == "Kubernetes")
    assert any(e["bullet_id"] == "arcesium-2" for e in k8s.related)  # Docker shown as related, not as a match
    steps = [(e["step"], e["status"]) for e in events]
    assert steps[0] == ("extract", "running") and steps[-1] == ("done", "done")
    assert ("check", "failed") not in steps


def test_agent_revises_after_failed_check(resume):
    result, events, llm = run({"extract_requirements": REQS, "draft": [INVENTED, GOOD]}, resume)
    assert result.revisions == 1 and result.draft == GOOD
    assert result.problems_fixed
    revise_prompt = llm.prompts[-1]
    assert "FAILED THESE CHECKS" in revise_prompt and "kubernetes" in revise_prompt.lower()
    assert [e["status"] for e in events if e["step"] == "check"] == ["running", "failed", "running", "done"]


def test_agent_never_ships_unsupported_claims(resume):
    result, events, llm = run({"extract_requirements": REQS, "draft": INVENTED}, resume)
    assert len([p for p in llm.prompts if p.startswith("STEP: draft")]) == MAX_REVISIONS + 1
    assert check_draft(result.draft, resume) == []
    assert result.notes


def test_empty_requirements_is_an_error(resume):
    with pytest.raises(ValueError):
        run({"extract_requirements": {"title": "x", "requirements": []}, "draft": GOOD}, resume)


def test_parse_json_handles_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}


# --- export -------------------------------------------------------------------
def test_docx_export(resume):
    from docx import Document
    doc = Document(io.BytesIO(to_docx(GOOD, resume)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "RAMYA SREE NARRA" in text and "Verizon" in text and "120K+" in text
    assert text.index("Verizon") < text.index("Georgia State")  # draft order, not résumé order


def test_pdf_export(resume):
    pdf = to_pdf(GOOD, resume)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1500


# --- job posts ----------------------------------------------------------------
def test_html_to_text_drops_scripts_and_keeps_lists():
    text = html_to_text("<html><script>evil()</script><h1>Engineer</h1><ul><li>Kafka</li><li>RAG</li></ul></html>")
    assert "evil" not in text and "- Kafka" in text and "Engineer" in text


def test_private_addresses_are_refused():
    assert not _is_public("127.0.0.1") and not _is_public("10.0.0.5") and not _is_public("localhost")


# --- API ----------------------------------------------------------------------
def test_api_streams_steps_and_serves_downloads(resume):
    app = create_app(llm_factory=lambda: ScriptedLLM({"extract_requirements": REQS, "draft": [INVENTED, GOOD]}), resume=resume)
    client = TestClient(app)
    with client.stream("POST", "/api/tailor", json={"job_text": JOB}) as r:
        assert r.status_code == 200
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events[0]["step"] == "extract" and events[-1]["step"] == "result"
    run_id = events[-1]["run_id"]
    assert events[-1]["result"]["coverage"]["must_have_gaps"] == []

    d = client.get(f"/api/runs/{run_id}/resume.docx")
    assert d.status_code == 200 and "acme-health" in d.headers["content-disposition"]
    assert client.get(f"/api/runs/{run_id}/resume.pdf").content[:5] == b"%PDF-"
    assert client.get("/api/runs/missing/resume.pdf").status_code == 404


def test_api_rejects_empty_request(resume):
    client = TestClient(create_app(llm_factory=lambda: ScriptedLLM({}), resume=resume))
    assert client.post("/api/tailor", json={}).status_code == 400


def test_api_reports_agent_errors_in_stream(resume):
    def boom(_):
        raise RuntimeError("model unavailable")
    client = TestClient(create_app(llm_factory=lambda: ScriptedLLM({"extract_requirements": boom}), resume=resume))
    with client.stream("POST", "/api/tailor", json={"job_text": JOB}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events[-1] == {"step": "error", "status": "failed", "message": "model unavailable"}


def test_demo_model_runs_end_to_end_and_passes_checks(resume):
    from copilot.demo import DemoLLM
    events = []
    result = TailorAgent(DemoLLM(resume), resume, emit=events.append).run(JOB)
    assert result.title.startswith("Senior Backend Engineer") and result.company == "Acme Health"
    assert len(result.requirements) == 4 and result.revisions == 0
    assert check_draft(result.draft, resume) == []
    assert any(r.importance == "nice" for r in result.requirements)
