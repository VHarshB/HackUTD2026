"use client";
import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Sparkles } from "lucide-react";
import { api } from "../../lib/api";
import type { Investigation } from "../../lib/types";

export default function NemotronInvestigation({
  dataset,
  facilityId,
  at,
  disabled,
}: {
  dataset: string;
  facilityId: string;
  at: number;
  disabled: boolean;
}) {
  const [result, setResult] = useState<Investigation | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    setResult(null);
    setError("");
    setBusy(false);
    return () => controller.current?.abort();
  }, [dataset, facilityId, at]);
  async function investigate() {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const value = await api.investigate(dataset, facilityId, at, c.signal);
      if (!c.signal.aborted) setResult(value);
    } catch (e) {
      if (!c.signal.aborted) setError((e as Error).message);
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="nemotron-section">
      <button
        className="investigate-button"
        disabled={busy || disabled}
        onClick={investigate}
      >
        {busy ? (
          <LoaderCircle size={16} className="spin" />
        ) : (
          <Sparkles size={16} />
        )}
        <span>
          {busy ? "Investigating with Nemotron…" : "Investigate with Nemotron"}
        </span>
        <span className="nvidia-mark">N</span>
      </button>
      <p className="fine-print">
        Live investigation · evidence, planning & verification tools
      </p>
      {error && (
        <div className="inline-error" role="alert">
          Investigation is not connected right now. You can still inspect sensor readings and the calculated response above.
          <details><summary>Connection details</summary>{error}</details>
        </div>
      )}
      {result && (
        <div className="investigation-answer" role="status">
          <span className="technical-label">NEMOTRON INVESTIGATION</span>
          <p>{result.answer}</p>
          <div className="executed-tools">
            <b>Tools actually executed</b>
            {result.tools_executed.map((tool, i) => (
              <code key={`${tool}:${i}`}>{tool}</code>
            ))}
          </div>
          <small>{result.model}</small>
        </div>
      )}
    </section>
  );
}
