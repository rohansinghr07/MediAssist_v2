import { Badge, Spinner } from "react-bootstrap";
import { APPT_STATUS, TICKET_STATUS } from "../utils.js";

export function ApptBadge({ status }) {
  const s = APPT_STATUS[status] || { bg: "light", label: status };
  return <Badge bg={s.bg} text={s.bg === "warning" ? "dark" : undefined}>{s.label}</Badge>;
}

export function TicketBadge({ status }) {
  const s = TICKET_STATUS[status] || { bg: "light", label: status };
  return <Badge bg={s.bg} text={s.bg === "warning" ? "dark" : undefined}>{s.label}</Badge>;
}

export function Loading({ text = "Loading…" }) {
  return (
    <div className="text-center text-muted py-5">
      <Spinner size="sm" className="me-2" />
      {text}
    </div>
  );
}

export function Empty({ icon = "inbox", text }) {
  return (
    <div className="text-center text-muted py-5">
      <i className={`bi bi-${icon} fs-2 d-block mb-2`} />
      {text}
    </div>
  );
}

export function StatCard({ label, value, icon, tone = "primary", onClick, hint }) {
  return (
    <div className={`stat-card tone-${tone}` + (onClick ? " clickable" : "")} onClick={onClick}>
      <div className="stat-icon">
        <i className={`bi bi-${icon}`} />
      </div>
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value ?? "–"}</div>
        {hint && <div className="stat-hint">{hint}</div>}
      </div>
    </div>
  );
}

const PRIORITY = { high: { bg: "danger", label: "High" }, medium: { bg: "warning", label: "Medium" }, low: { bg: "secondary", label: "Low" } };

export function PriorityBadge({ priority }) {
  if (!priority) return <span className="text-muted small">–</span>;
  const p = PRIORITY[priority] || PRIORITY.medium;
  return <Badge bg={p.bg} text={p.bg === "warning" ? "dark" : undefined} title="Set by AI">{p.label}</Badge>;
}

export const PRIORITY_ORDER = { high: 0, medium: 1, low: 2 };

// Coloured initials avatar (no stock photos)
const AV = [["#f3f3ff", "#5156be"], ["#fff6e0", "#b97900"], ["#e6f6f0", "#05825f"], ["#e8f3fe", "#2f7fd6"],
            ["#fdecf0", "#d42a4e"], ["#f4ecff", "#7c3aed"]];

export function Avatar({ name = "", size = "", round = false }) {
  const clean = name.replace(/^Dr\.?\s+/i, "").trim();
  const initials = clean.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
  let h = 0;
  for (const ch of clean) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const [bg, fg] = AV[h % AV.length];
  return <span className={`avatar ${size} ${round ? "round" : ""}`} style={{ background: bg, color: fg }}>{initials}</span>;
}

export function PageHead({ title, crumb, children }) {
  return (
    <div className="page-head">
      <h2 className="page-title">{title}</h2>
      <span className="crumb"><i className="bi bi-house-door" /> &nbsp;-&nbsp; {crumb || title}</span>
      <div className="ms-auto d-flex gap-2 align-items-center">{children}</div>
    </div>
  );
}
