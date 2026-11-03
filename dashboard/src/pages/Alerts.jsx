import { useEffect, useState } from "react";
import { Badge, Button, Card } from "react-bootstrap";
import { api } from "../api.js";
import { Empty, Loading } from "../components/common.jsx";
import { ago, fmtDateTime } from "../utils.js";

export default function Alerts({ tick, refresh, notify }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api("/alerts").then(setRows).catch(() => setRows([]));
  }, [tick]);

  async function seen(a) {
    try {
      await api(`/alerts/${a._id}`, { method: "PATCH" });
      notify(`${a._id} marked as seen`);
      refresh();
    } catch (e) {
      notify(e.message, "danger");
    }
  }

  if (rows === null) return <Loading />;
  if (!rows.length) return <Empty icon="shield-check" text="No emergency alerts." />;

  return (
    <div className="d-grid gap-3">
      <div className="small text-muted">
        Alerts are created when a patient's message looks like an emergency. The patient is told to call 108 immediately.
        Please call them back on the number shown.
      </div>
      {rows.map((a) => (
        <Card key={a._id} className={a.status === "new" ? "alert-card new" : "alert-card"}>
          <Card.Body className="d-flex flex-wrap gap-3 align-items-start">
            <i className={`bi bi-exclamation-octagon-fill fs-3 ${a.status === "new" ? "text-danger" : "text-secondary"}`} />
            <div className="flex-grow-1">
              <div className="d-flex gap-2 align-items-center mb-1">
                <span className="font-monospace small text-nowrap">{a._id}</span>
                {a.status === "new" ? <Badge bg="danger">New</Badge> : <Badge bg="secondary">Seen by {a.seen_by}</Badge>}
                <span className="small text-muted">{fmtDateTime(a.created_at)} · {ago(a.created_at)}</span>
              </div>
              <div className="fs-6 mb-1">“{a.text}”</div>
              <div className="small">
                <strong>{a.name || "Unknown patient"}</strong>
                {a.phone ? <> · <a href={`tel:${a.phone}`}>{a.phone}</a></> : " · no phone saved"}
              </div>
            </div>
            {a.status === "new" && <Button variant="outline-danger" size="sm" onClick={() => seen(a)}>Mark as seen</Button>}
          </Card.Body>
        </Card>
      ))}
    </div>
  );
}
