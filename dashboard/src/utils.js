// Formatting helpers - all times shown in the clinic's time zone.
export const TZ = "Asia/Kolkata";

export function fmtDate(iso, opts = {}) {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString("en-IN", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", ...opts });
}

export function fmtTime(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString("en-IN", { timeZone: TZ, hour: "numeric", minute: "2-digit", hour12: true });
}

export function fmtDateTime(iso) {
  if (!iso) return "–";
  return `${fmtDate(iso)}, ${fmtTime(iso)}`;
}

export function ago(iso) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export function todayISO() {
  // YYYY-MM-DD in clinic time
  return new Date().toLocaleDateString("en-CA", { timeZone: TZ });
}

export function dayLabel(dateStr) {
  // "2026-10-27" -> "Tue, 27 Oct"
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 6)).toLocaleDateString("en-IN", { timeZone: TZ, weekday: "short", day: "numeric", month: "short" });
}

export const APPT_STATUS = {
  booked: { bg: "primary", label: "Booked" },
  cancelled: { bg: "secondary", label: "Cancelled" },
  completed: { bg: "success", label: "Completed" },
  no_show: { bg: "warning", label: "No-show" },
};

export const TICKET_STATUS = {
  pending: { bg: "danger", label: "Pending" },
  in_progress: { bg: "warning", label: "In Progress" },
  resolved: { bg: "success", label: "Resolved" },
};
