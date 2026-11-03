import { useEffect, useState } from "react";
import { Alert, Button, ButtonGroup, Card, Form, Modal, Spinner, Table } from "react-bootstrap";
import { api } from "../api.js";
import { Avatar, Empty, Loading, PRIORITY_ORDER, PriorityBadge, TicketBadge } from "../components/common.jsx";
import { ago, fmtDateTime } from "../utils.js";

const TYPES = [
  { key: "", label: "All" },
  { key: "issue", label: "Issues" },
  { key: "complaint", label: "Complaints" },
];

function TicketModal({ ticket, onClose, onDone, notify }) {
  const [status, setStatus] = useState(ticket.status);
  const [note, setNote] = useState("");
  const [tell, setTell] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(`/tickets/${ticket._id}`, { method: "PATCH", body: { status, note: note || null, notify_patient: tell } });
      notify(`${ticket._id} updated${tell ? " – patient informed on Telegram" : ""}`);
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal show onHide={onClose} centered size="lg">
      <Modal.Header closeButton>
        <Modal.Title as="h5">
          {ticket._id} <span className="text-muted fs-6 text-capitalize">· {ticket.type}</span>
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {error && <Alert variant="danger" className="py-2 small">{error}</Alert>}
        <dl className="row small mb-3">
          <dt className="col-sm-3">Patient</dt><dd className="col-sm-9">{ticket.name} · {ticket.phone}{ticket.email ? ` · ${ticket.email}` : ""}</dd>
          <dt className="col-sm-3">Category</dt><dd className="col-sm-9">{ticket.category}</dd>
          <dt className="col-sm-3">Raised</dt><dd className="col-sm-9">{fmtDateTime(ticket.created_at)} ({ago(ticket.created_at)})</dd>
          <dt className="col-sm-3">Language</dt><dd className="col-sm-9">{ticket.language === "hi" ? "Hindi" : "English"}</dd>
        </dl>
        {ticket.ai_summary && (
          <div className="ai-box mb-2">
            <span className="ai-tag"><i className="bi bi-stars" /> AI</span> {ticket.ai_summary}
            <span className="ms-2"><PriorityBadge priority={ticket.priority} /></span>
          </div>
        )}
        <div className="ticket-desc mb-3">{ticket.description}</div>
        {ticket.notes && ticket.notes.length > 0 && (
          <div className="mb-3">
            <div className="small fw-semibold mb-1">History</div>
            {ticket.notes.map((n, i) => (
              <div key={i} className="small text-muted">
                • {fmtDateTime(n.at)} – {n.by}: {n.text}
                {n.translated && <div className="ms-3 fst-italic">→ sent in Hindi (AI): {n.translated}</div>}
              </div>
            ))}
          </div>
        )}
        <Form.Group className="mb-3">
          <Form.Label className="small">Status</Form.Label>
          <div>
            <ButtonGroup size="sm">
              {["pending", "in_progress", "resolved"].map((s) => (
                <Button key={s} variant={status === s ? "dark" : "outline-dark"} onClick={() => setStatus(s)}>
                  {s === "in_progress" ? "In Progress" : s[0].toUpperCase() + s.slice(1)}
                </Button>
              ))}
            </ButtonGroup>
          </div>
        </Form.Group>
        <Form.Group className="mb-3">
          <Form.Label className="small">Note to patient (optional)</Form.Label>
          <Form.Control as="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Medicine is now available at the clinic pharmacy" />
          {ticket.language === "hi" && <Form.Text><i className="bi bi-translate me-1" />Write in English – AI will translate it to Hindi for this patient.</Form.Text>}
        </Form.Group>
        <Form.Check id="tell-ticket" checked={tell} onChange={(e) => setTell(e.target.checked)} label="Send the patient a Telegram update" />
      </Modal.Body>
      <Modal.Footer>
        <Button variant="light" onClick={onClose}>Close</Button>
        <Button onClick={save} disabled={busy}>{busy ? <Spinner size="sm" /> : "Save"}</Button>
      </Modal.Footer>
    </Modal>
  );
}

export default function Tickets({ tick, refresh, notify, seed }) {
  const [type, setType] = useState("");
  const [status, setStatus] = useState("open");
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (seed) { setType(""); setStatus(""); setSearch(seed.q); }
  }, [seed]);

  useEffect(() => {
    api("/tickets", { params: { type, status: status === "open" ? "" : status } })
      .then((t) => setRows(status === "open" ? t.filter((x) => x.status !== "resolved") : t))
      .catch((e) => { notify(e.message, "danger"); setRows([]); });
  }, [tick, type, status, notify]);

  const q = search.trim().toLowerCase();
  const filteredRows = rows && (q ? rows.filter((t) => [t._id, t.name, t.phone, t.ai_summary].some((v) => (v || "").toLowerCase().includes(q))) : rows);
  const shown = filteredRows && [...filteredRows].sort((a, b) =>
    (a.status === "resolved") - (b.status === "resolved") ||
    (PRIORITY_ORDER[a.priority] ?? 1) - (PRIORITY_ORDER[b.priority] ?? 1) ||
    new Date(b.created_at) - new Date(a.created_at));

  return (
    <Card>
      <Card.Header className="d-flex flex-wrap gap-2 align-items-center">
        <div className="seg">
          {TYPES.map((t) => (
            <button key={t.key} className={type === t.key ? "on" : ""} onClick={() => setType(t.key)}>{t.label}</button>
          ))}
        </div>
        <Form.Select size="sm" style={{ width: "auto" }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Open (not resolved)</option>
          <option value="pending">Pending</option>
          <option value="in_progress">In Progress</option>
          <option value="resolved">Resolved</option>
          <option value="">Everything</option>
        </Form.Select>
        <Form.Control size="sm" style={{ maxWidth: 260 }} placeholder="Search ticket no., name or phone…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <span className="ms-auto small text-muted">{shown ? `${shown.length} shown` : ""} · click a row to update</span>
      </Card.Header>
      <Card.Body className="p-0">
        {shown === null ? (
          <Loading />
        ) : shown.length === 0 ? (
          <Empty icon="emoji-smile" text="No tickets here." />
        ) : (
          <div className="table-responsive">
            <Table hover className="align-middle mb-0">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type / Category</th>
                  <th>Patient</th>
                  <th>Description</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Raised</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => (
                  <tr key={t._id} className="clickable" onClick={() => setOpen(t)}>
                    <td className="font-monospace small">{t._id}</td>
                    <td>
                      <div className="text-capitalize fw-semibold">{t.type}</div>
                      <div className="small text-muted">{t.category}</div>
                    </td>
                    <td>
                      <div className="d-flex align-items-center gap-2">
                        <Avatar name={t.name} size="sm" />
                        <div><div className="fw-semibold">{t.name}</div><div className="small text-muted">{t.phone}</div></div>
                      </div>
                    </td>
                    <td className="desc-cell">
                      {t.ai_summary ? <div className="fw-semibold small"><i className="bi bi-stars ai-icon" title="Written by AI" /> {t.ai_summary}</div> : null}
                      <div className={t.ai_summary ? "small text-muted text-truncate" : ""}>{t.description}</div>
                    </td>
                    <td className="text-nowrap"><PriorityBadge priority={t.priority} /></td>
                    <td><TicketBadge status={t.status} /></td>
                    <td className="small text-muted text-nowrap">{ago(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card.Body>
      {open && <TicketModal ticket={open} notify={notify} onClose={() => setOpen(null)} onDone={() => { setOpen(null); refresh(); }} />}
    </Card>
  );
}
