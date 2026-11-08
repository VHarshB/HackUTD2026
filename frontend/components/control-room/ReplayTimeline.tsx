import { Clock3, SkipForward } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { timestamp } from "../../lib/operational-status";
import type { Dashboard } from "../../lib/types";

export default function ReplayTimeline({
  data,
  onChange,
  busy,
}: {
  data: Dashboard;
  onChange: (time: number | null) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState(data.now);
  const dragging = useRef(false);
  useEffect(() => {
    if (!dragging.current) setDraft(data.now);
  }, [data.now]);
  // Commit after a short pause, rather than issuing a request for every slider pixel.
  useEffect(() => {
    if (draft === data.now) return;
    const timer = window.setTimeout(() => onChange(draft), 350);
    return () => window.clearTimeout(timer);
  }, [draft, data.now, onChange]);
  const pct = ((draft - data.start) / Math.max(1, data.end - data.start)) * 100;
  return (
    <section
      className="replay-timeline glass"
      aria-label="Historical telemetry replay"
    >
      <div className="timeline-title">
        <Clock3 size={17} />
        <span>
          <b>SHIFT REPLAY</b>
          <time>{timestamp(draft)}</time>
        </span>
      </div>
      <div className="timeline-slider">
        <div className="timeline-labels">
          <span>{timestamp(data.start)}</span>
          <span>
            {busy ? "Loading selected reading…" : "RECORDED · 5 MIN INTERVALS"}
          </span>
          <span>{timestamp(data.end)}</span>
        </div>
        <input
          aria-label="Recorded telemetry timestamp"
          aria-valuetext={timestamp(draft)}
          type="range"
          min={data.start}
          max={data.end}
          step={300}
          value={draft}
          style={{ "--progress": `${pct}%` } as React.CSSProperties}
          onPointerDown={() => {
            dragging.current = true;
          }}
          onPointerUp={() => {
            dragging.current = false;
          }}
          onPointerCancel={() => {
            dragging.current = false;
          }}
          onChange={(e) => setDraft(Number(e.target.value))}
        />
      </div>
      <button
        className="latest-button"
        onClick={() => {
          setDraft(data.end);
          onChange(null);
        }}
      >
        <SkipForward size={15} />
        <span>Latest reading</span>
      </button>
    </section>
  );
}
