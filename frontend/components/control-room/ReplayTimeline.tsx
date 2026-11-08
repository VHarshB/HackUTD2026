import { Clock3, Pause, Play, SkipForward } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { timestamp } from "../../lib/operational-status";
import type { Dashboard } from "../../lib/types";

// Recorded readings to advance per frame. A week is ~2000 readings, so playing
// every one would take minutes; the faster speeds step over readings instead of
// rendering them quicker, which keeps each frame an honest recorded moment.
const SPEEDS = [1, 4, 12, 36];
// Wall-clock gap between frames. A frame costs ~10ms end to end on localhost,
// so this is pacing we can actually hold rather than a ceiling we hope for.
const FRAME_MS = 110;

/** "5 MIN" / "1 H" -- how much recorded time one frame covers. */
function span(seconds: number) {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} MIN`;
  const hours = minutes / 60;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} H`;
}

export default function ReplayTimeline({
  data,
  onChange,
  onPlayingChange,
  busy,
}: {
  data: Dashboard;
  onChange: (time: number | null) => void;
  onPlayingChange: (playing: boolean) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState(data.now);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const dragging = useRef(false);
  const stride = data.step * speed;
  const atEnd = data.now >= data.end;

  useEffect(() => {
    if (!dragging.current) setDraft(data.now);
  }, [data.now]);
  // The parent hides its loading chrome while we play, so every frame does not
  // flash a spinner and disable the scene for a request that lasts milliseconds.
  // The cleanup matters: switching dataset unmounts us mid-playback, and the
  // parent would otherwise keep suppressing the spinner for the next load.
  useEffect(() => {
    onPlayingChange(playing);
    return () => onPlayingChange(false);
  }, [playing, onPlayingChange]);

  // Commit a dragged position after a short pause, rather than issuing a
  // request for every slider pixel. Playback commits each frame directly.
  useEffect(() => {
    if (playing || draft === data.now) return;
    const timer = window.setTimeout(() => onChange(draft), 350);
    return () => window.clearTimeout(timer);
  }, [playing, draft, data.now, onChange]);

  // Playback is self-pacing: it only queues the next frame once the one it
  // asked for has arrived (draft === data.now). A slow machine or a cold
  // dataset therefore loses frame rate instead of piling up requests it can
  // never catch up with, and no frame is ever skipped or rendered out of order.
  useEffect(() => {
    if (!playing || draft !== data.now) return;
    if (atEnd) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => {
      const next = Math.min(data.end, data.now + stride);
      setDraft(next);
      onChange(next);
    }, FRAME_MS);
    return () => window.clearTimeout(timer);
  }, [playing, draft, data.now, data.end, atEnd, stride, onChange]);

  const stop = () => setPlaying(false);
  const toggle = () => {
    // Pressing play on a finished timeline rewinds rather than doing nothing.
    if (!playing && atEnd) {
      setDraft(data.start);
      onChange(data.start);
    }
    setPlaying((value) => !value);
  };

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
      <div className="timeline-transport">
        <button
          className={"transport-button " + (playing ? "active" : "")}
          onClick={toggle}
          aria-pressed={playing}
          aria-label={
            playing
              ? "Pause replay"
              : atEnd
                ? "Replay from the beginning"
                : "Play replay"
          }
          title={playing ? "Pause" : atEnd ? "Replay from start" : "Play"}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <select
          className="speed-select"
          aria-label="Replay speed, as recorded time covered per frame"
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        >
          {SPEEDS.map((value) => (
            <option key={value} value={value}>
              {span(data.step * value)}/frame
            </option>
          ))}
        </select>
      </div>
      <div className="timeline-slider">
        <div className="timeline-labels">
          <span>{timestamp(data.start)}</span>
          <span>
            {playing
              ? `PLAYING · ${span(stride)} PER FRAME`
              : busy
                ? "Loading selected reading…"
                : `RECORDED · ${span(data.step)} INTERVALS`}
          </span>
          <span>{timestamp(data.end)}</span>
        </div>
        <input
          aria-label="Recorded telemetry timestamp"
          aria-valuetext={timestamp(draft)}
          type="range"
          min={data.start}
          max={data.end}
          step={data.step}
          value={draft}
          style={{ "--progress": `${pct}%` } as React.CSSProperties}
          onPointerDown={() => {
            dragging.current = true;
            stop();
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
          stop();
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
