const stages = [
  { title: "Evidence", lines: ["Notice", "Questionnaire", "HAR, SQLite, scripts"] },
  { title: "Extract", lines: ["Data elements", "Recipients", "Trackers"] },
  { title: "Classify", lines: ["Personal data taxonomy", "Special categories"] },
  { title: "Compare", lines: ["Rules first", "Findings with evidence"] },
  { title: "Record", lines: ["Article 30 draft", "Review and approval"] },
];

/** The onboarding pipeline as an inline SVG, with a text alternative. */
export function PipelineDiagram() {
  const w = 190;
  const gap = 36;
  const width = stages.length * w + (stages.length - 1) * gap;
  return (
    <svg
      viewBox={`0 0 ${width} 170`}
      className="h-auto w-full min-w-[920px]"
      role="img"
      aria-label="Pipeline: evidence, extract, classify, compare, record"
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0L10 5L0 10z" fill="#0F62FE" />
        </marker>
      </defs>
      {stages.map((s, i) => {
        const x = i * (w + gap);
        return (
          <g key={s.title}>
            <rect x={x} y={10} width={w} height={150} rx={14} fill="#fff" stroke="#D9E0EA" />
            <rect x={x} y={10} width={w} height={36} rx={14} fill="#0B1F3A" />
            <rect x={x} y={30} width={w} height={16} fill="#0B1F3A" />
            <text x={x + 14} y={34} fill="#fff" fontSize="15" fontWeight="600">
              {`${i + 1}. ${s.title}`}
            </text>
            {s.lines.map((line, j) => (
              <text key={line} x={x + 14} y={72 + j * 24} fill="#161E2D" fontSize="13.5">
                {line}
              </text>
            ))}
            {i < stages.length - 1 && (
              <line
                x1={x + w + 4}
                y1={85}
                x2={x + w + gap - 4}
                y2={85}
                stroke="#0F62FE"
                strokeWidth="2.5"
                markerEnd="url(#arrow)"
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}
