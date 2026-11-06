// The agent's steps, live. Running steps are replaced by their result when it arrives.
const ICON = { running: "", done: "✓", failed: "!" };

function collapse(events) {
  const rows = [];
  for (const ev of events) {
    const last = rows[rows.length - 1];
    if (last && last.step === ev.step && last.status === "running") rows[rows.length - 1] = ev;
    else rows.push(ev);
  }
  return rows;
}

export default function Trace({ events, running, error }) {
  if (!events.length && !error) return null;
  const rows = collapse(events);
  return (
    <div className="trace">
      <h3>Agent steps</h3>
      <ol>
        {rows.map((ev, i) => (
          <li key={i} className={`ev ${ev.status}`}>
            <span className="ic">{ev.status === "running" && running ? <span className="spin" /> : ICON[ev.status]}</span>
            <div>
              <div className="msg">{ev.message}</div>
              {ev.data?.problems && (
                <ul className="problems">
                  {ev.data.problems.map((p, j) => <li key={j}><span className="mono">{p.where}</span> {p.detail}</li>)}
                </ul>
              )}
              {ev.data?.gaps?.length > 0 && <div className="sub">No evidence for: {ev.data.gaps.join("; ")}</div>}
            </div>
          </li>
        ))}
        {error && (
          <li className="ev failed"><span className="ic">!</span><div className="msg">{error}</div></li>
        )}
      </ol>
    </div>
  );
}
