export default function ConfidenceBadge({ score, label }) {
  if (score == null) return null;
  const cls = label === "High" ? "badge-high" : label === "Medium" ? "badge-medium" : "badge-low";
  return (
    <span className={`badge ${cls}`}>
      {label} confidence · {Math.round(score * 100)}%
    </span>
  );
}
