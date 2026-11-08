import { useId } from "react";
import type { TrendPoint } from "../../lib/types";
import { formatValue, timestamp } from "../../lib/operational-status";

export default function SensorTrend({
  points,
  unit,
  metric,
  thresholds,
  projected = false,
}: {
  points: TrendPoint[];
  unit: string;
  metric: string;
  thresholds?: { warning: number; shutdown: number };
  projected?: boolean;
}) {
  const gradient = useId().replaceAll(":", "");
  if (!points.length)
    return (
      <div className="empty-reading">
        No readings are available for this asset and metric.
      </div>
    );
  const values = points.map((p) => p.value);
  const rawMin = Math.min(...values),
    rawMax = Math.max(...values);
  const min = thresholds
    ? 0
    : Math.max(0, rawMin - Math.max(1, (rawMax - rawMin) * 0.2));
  const max = thresholds ? 100 : rawMax + Math.max(1, (rawMax - rawMin) * 0.2);
  const first = points[0].ts,
    last = points[points.length - 1].ts;
  const y = (v: number) => 120 - ((v - min) / Math.max(1, max - min)) * 100;
  const path = points
    .flatMap((p, i) => {
      const x = 30 + ((p.ts - first) / Math.max(1, last - first)) * 280;
      return metric === "status" && i > 0
        ? [`${x},${y(points[i - 1].value)}`, `${x},${y(p.value)}`]
        : [`${x},${y(p.value)}`];
    })
    .join(" ");
  return (
    <div className="sensor-chart">
      <div className="chart-value">
        <strong>
          {formatValue(values[values.length - 1], metric === "status" ? 0 : 2)}
        </strong>
        <span>{unit}</span>
        <small>
          {projected ? "Projected final level" : "Last recorded reading"}
        </small>
      </div>
      <svg
        viewBox="0 0 330 140"
        role="img"
        aria-label={`${metric} ${projected ? "projected" : "recorded"} trend, ${points.length} samples. Latest ${formatValue(values[values.length - 1])} ${unit}.`}
      >
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop stopColor="#7edfe9" stopOpacity=".16" />
            <stop offset="1" stopColor="#7edfe9" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line
              x1="30"
              x2="310"
              y1={20 + t * 100}
              y2={20 + t * 100}
              stroke="#24323f"
            />
            <text x="0" y={23 + t * 100} fill="#8194a5" fontSize="8">
              {formatValue(max - t * (max - min), 0)}
            </text>
          </g>
        ))}
        {thresholds &&
          [thresholds.warning, thresholds.shutdown].map((v, i) => (
            <g key={i}>
              <line
                x1="30"
                x2="310"
                y1={y(v)}
                y2={y(v)}
                stroke={i ? "#f16c68" : "#e7b568"}
                strokeDasharray="3 4"
                opacity=".65"
              />
              <text
                x="307"
                y={y(v) - 3}
                textAnchor="end"
                fontSize="7"
                fill={i ? "#f16c68" : "#e7b568"}
              >
                {v}% {i ? "STOP" : "WARN"}
              </text>
            </g>
          ))}
        <polygon points={`30,120 ${path} 310,120`} fill={`url(#${gradient})`} />
        <polyline
          points={path}
          fill="none"
          stroke="#7edfe9"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
      <div className="chart-dates">
        <span>{timestamp(first)}</span>
        <span>{timestamp(last)}</span>
      </div>
      <p className="fine-print">
        {projected
          ? "Deterministic simulation · not recorded sensor readings."
          : `${points.length} recorded samples · ${metric === "status" ? "Status codes are discrete states, not continuous measurements." : "Sensor noise is preserved."}`}
      </p>
    </div>
  );
}
