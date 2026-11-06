import { useEffect, useMemo, useState } from "react";
import { getResume, tailor } from "./api.js";
import Trace from "./Trace.jsx";

const SAMPLE = `Senior Software Engineer, AI Platform

We're building LLM-powered agents that help support teams resolve issues faster.

What you'll do
- Design and build distributed backend services in Java or Python
- Build retrieval-augmented generation (RAG) pipelines with vector search
- Integrate event streaming with Kafka
- Own observability: logging, search and debugging tools
- Ship React front ends for internal tools

Requirements
- 4+ years of backend engineering experience
- Experience with LLMs, RAG or AI agents
- CI/CD and Docker
- Nice to have: Kubernetes, Go`;

export default function App() {
  const [mode, setMode] = useState("text");
  const [jobText, setJobText] = useState("");
  const [jobUrl, setJobUrl] = useState("");
  const [events, setEvents] = useState([]);
  const [result, setResult] = useState(null);
  const [runId, setRunId] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [resume, setResume] = useState(null);
  const [tab, setTab] = useState("resume");

  useEffect(() => { getResume().then(setResume).catch(() => {}); }, []);

  async function run(e) {
    e.preventDefault();
    setEvents([]); setResult(null); setError(""); setRunning(true); setTab("resume");
    try {
      await tailor(mode === "text" ? { job_text: jobText } : { job_url: jobUrl }, (ev) => {
        if (ev.step === "result") { setResult(ev.result); setRunId(ev.run_id); }
        else if (ev.step === "error") setError(ev.message);
        else setEvents((list) => [...list, ev]);
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  const ready = mode === "text" ? jobText.trim().length > 40 : /^https?:\/\//.test(jobUrl);

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo">JC</span>
          <div>
            <h1>Job Copilot</h1>
            <p>Tailors a real résumé to a job, then checks every line against the original.</p>
          </div>
        </div>
      </header>

      <main className="grid">
        <section className="panel input">
          <form onSubmit={run}>
            <div className="seg">
              <button type="button" className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Paste description</button>
              <button type="button" className={mode === "url" ? "on" : ""} onClick={() => setMode("url")}>Job link</button>
            </div>
            {mode === "text" ? (
              <>
                <textarea value={jobText} onChange={(e) => setJobText(e.target.value)} placeholder="Paste the job description here…" />
                <button type="button" className="link" onClick={() => setJobText(SAMPLE)}>Use a sample job</button>
              </>
            ) : (
              <input value={jobUrl} onChange={(e) => setJobUrl(e.target.value)} placeholder="https://company.com/careers/role" />
            )}
            <button className="primary" disabled={!ready || running}>{running ? "Working…" : "Tailor my résumé"}</button>
          </form>
          <Trace events={events} running={running} error={error} />
        </section>

        <section className="panel output">
          {!result ? (
            <Empty running={running} />
          ) : (
            <>
              <div className="out-head">
                <div>
                  <h2>{result.title}</h2>
                  {result.company && <span className="muted">{result.company}</span>}
                </div>
                <div className="downloads">
                  <a className="btn" href={`/api/runs/${runId}/resume.docx`}>Word</a>
                  <a className="btn" href={`/api/runs/${runId}/resume.pdf`}>PDF</a>
                </div>
              </div>
              <Stats result={result} />
              <div className="tabs">
                <button className={tab === "resume" ? "on" : ""} onClick={() => setTab("resume")}>Tailored résumé</button>
                <button className={tab === "coverage" ? "on" : ""} onClick={() => setTab("coverage")}>Requirements</button>
              </div>
              {tab === "resume" ? <Draft result={result} resume={resume} /> : <Coverage result={result} />}
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function Empty({ running }) {
  return (
    <div className="empty">
      <div className="steps-preview">
        {["Read the job", "Find your evidence", "Draft", "Check every line", "Revise if needed"].map((s, i) => (
          <div key={s} className={`pill ${running ? "pulse" : ""}`} style={{ animationDelay: `${i * 0.15}s` }}>{s}</div>
        ))}
      </div>
      <p>{running ? "The agent is working. Each step appears on the left as it happens." : "Paste a job description to start."}</p>
    </div>
  );
}

function Stats({ result }) {
  const c = result.coverage;
  return (
    <div className="stats">
      <div><b>{c.with_evidence}/{c.requirements}</b><span>requirements backed by your résumé</span></div>
      <div><b>{c.must_have_gaps.length}</b><span>must-have gaps</span></div>
      <div><b>{result.revisions}</b><span>revision{result.revisions === 1 ? "" : "s"} after self-check</span></div>
    </div>
  );
}

function Draft({ result, resume }) {
  const [showSource, setShowSource] = useState(false);
  const sections = useMemo(() => {
    if (!resume) return [];
    const all = [...resume.experience, ...resume.projects];
    const byId = Object.fromEntries(all.map((s) => [s.id, s]));
    const bullets = Object.fromEntries(all.flatMap((s) => s.bullets.map((b) => [b.id, b.text])));
    return result.draft.sections.filter((s) => byId[s.id]).map((s) => ({ ...s, src: byId[s.id], bullets: s.bullets.map((b) => ({ ...b, original: b.source_ids.map((id) => bullets[id]) })) }));
  }, [result, resume]);

  return (
    <div className="draft">
      <label className="toggle"><input type="checkbox" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} /> Show the original line behind each bullet</label>
      {result.notes.length > 0 && <div className="note">{result.notes.join(" ")}</div>}
      <p className="summary">{result.draft.summary}</p>
      {sections.map((s) => (
        <div key={s.id} className="sec">
          <div className="sec-head">
            <b>{s.src.company || s.src.name}</b>
            <span>{s.src.title || s.src.subtitle}</span>
            <span className="muted right">{s.src.dates || ""}</span>
          </div>
          <ul>
            {s.bullets.map((b, i) => (
              <li key={i}>
                {b.text}
                {showSource && (
                  <div className="source">
                    <span className="mono">{b.source_ids.join(", ")}</span> {b.original.join(" ")}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <div className="sec">
        <div className="sec-head"><b>Skills</b></div>
        <div className="chips">{result.draft.skills.map((s) => <span key={s} className="chip">{s}</span>)}</div>
      </div>
    </div>
  );
}

function Coverage({ result }) {
  return (
    <div className="coverage">
      {result.requirements.map((r, i) => (
        <div key={i} className={`req ${r.met ? "met" : "gap"}`}>
          <div className="req-head">
            <span className="dot" />
            <b>{r.text}</b>
            <span className={`tag ${r.importance}`}>{r.importance === "must" ? "must-have" : "nice to have"}</span>
          </div>
          {r.met ? (
            <ul>{r.evidence.map((e) => <li key={e.bullet_id}><span className="mono">{e.bullet_id}</span> {e.text}</li>)}</ul>
          ) : (
            <>
              <p className="muted">Not on your résumé, so the agent didn't claim it.{r.related?.length > 0 && " Closest related experience:"}</p>
              {r.related?.length > 0 && <ul>{r.related.map((e) => <li key={e.bullet_id}><span className="mono">{e.bullet_id}</span> {e.text}</li>)}</ul>}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
