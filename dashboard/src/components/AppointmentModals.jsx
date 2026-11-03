import { useEffect, useState } from "react";
import { Alert, Button, Form, Modal, Spinner } from "react-bootstrap";
import { api } from "../api.js";
import { dayLabel, fmtDateTime, fmtTime } from "../utils.js";

export function CancelModal({ appt, onClose, onDone, notify }) {
  const [reason, setReason] = useState("");
  const [tell, setTell] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api(`/appointments/${appt._id}/cancel`, { method: "POST", body: { reason, notify_patient: tell } });
      notify(`${appt._id} cancelled${tell ? " – patient informed on Telegram" : ""}`);
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal show onHide={onClose} centered>
      <Modal.Header closeButton>
        <Modal.Title as="h5">Cancel appointment {appt._id}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p className="mb-3">
          <strong>{appt.patient_name}</strong> with {appt.doctor_name}
          <br />
          <span className="text-muted">{fmtDateTime(appt.start)}</span>
        </p>
        {error && <Alert variant="danger" className="py-2 small">{error}</Alert>}
        <Form.Group className="mb-3">
          <Form.Label className="small">Reason (optional)</Form.Label>
          <Form.Control as="textarea" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Doctor on leave" />
        </Form.Group>
        <Form.Check id="tell-cancel" checked={tell} onChange={(e) => setTell(e.target.checked)} label="Send the patient a Telegram message" />
      </Modal.Body>
      <Modal.Footer>
        <Button variant="light" onClick={onClose}>Keep it</Button>
        <Button variant="danger" onClick={confirm} disabled={busy}>
          {busy ? <Spinner size="sm" /> : "Cancel appointment"}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}

export function RescheduleModal({ appt, onClose, onDone, notify }) {
  const [data, setData] = useState(null);
  const [day, setDay] = useState(null);
  const [slot, setSlot] = useState(null);
  const [tell, setTell] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/doctors/${appt.doctor_id}/slots`)
      .then((d) => {
        setData(d);
        const days = Object.keys(d.free || {});
        if (days.length) setDay(days[0]);
      })
      .catch((e) => setError(e.message));
  }, [appt.doctor_id]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await api(`/appointments/${appt._id}/reschedule`, { method: "POST", body: { start: slot, notify_patient: tell } });
      notify(`${appt._id} moved to ${fmtDateTime(slot)}${tell ? " – patient informed" : ""}`);
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const days = data ? Object.keys(data.free || {}) : [];

  return (
    <Modal show onHide={onClose} centered size="lg">
      <Modal.Header closeButton>
        <Modal.Title as="h5">Reschedule {appt._id}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p className="mb-3">
          <strong>{appt.patient_name}</strong> with {appt.doctor_name}
          <br />
          <span className="text-muted">Now: {fmtDateTime(appt.start)}</span>
        </p>
        {error && <Alert variant="danger" className="py-2 small">{error}</Alert>}
        {!data && !error && <div className="text-muted"><Spinner size="sm" className="me-2" />Loading free slots from Cal.com…</div>}
        {data && data.error && <Alert variant="warning" className="py-2 small">{data.error}</Alert>}
        {data && !days.length && !data.error && <Alert variant="info" className="py-2 small">No free slots in the next {data.days_ahead} days.</Alert>}
        {days.length > 0 && (
          <>
            <div className="small text-muted mb-1">1. Pick a date</div>
            <div className="d-flex flex-wrap gap-2 mb-3">
              {days.map((d) => (
                <Button key={d} size="sm" variant={d === day ? "primary" : "outline-primary"} onClick={() => { setDay(d); setSlot(null); }}>
                  {dayLabel(d)} <span className="opacity-75">({data.free[d].length})</span>
                </Button>
              ))}
            </div>
            <div className="small text-muted mb-1">2. Pick a time</div>
            <div className="slot-grid mb-3">
              {(data.free[day] || []).map((iso) => (
                <button key={iso} className={"slot-chip free" + (iso === slot ? " selected" : "")} onClick={() => setSlot(iso)}>
                  {fmtTime(iso)}
                </button>
              ))}
            </div>
            <Form.Check id="tell-resched" checked={tell} onChange={(e) => setTell(e.target.checked)} label="Send the patient a Telegram message" />
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        {slot && <span className="me-auto small">New time: <strong>{fmtDateTime(slot)}</strong></span>}
        <Button variant="light" onClick={onClose}>Close</Button>
        <Button onClick={confirm} disabled={!slot || busy}>
          {busy ? <Spinner size="sm" /> : "Confirm new time"}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
