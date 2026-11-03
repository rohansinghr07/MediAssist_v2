import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Col, Form, Modal, Row, Spinner } from "react-bootstrap";
import { api } from "../api.js";
import { dayLabel, fmtDateTime, fmtTime } from "../utils.js";
import { Avatar } from "./common.jsx";

const WEEK = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

/** Reception: book an appointment for a walk-in or phone-call patient. */
export default function BookModal({ onClose, onDone, notify, doctorId: presetDoctor }) {
  const [departments, setDepartments] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [phone, setPhone] = useState("");
  const [found, setFound] = useState(null); // lookup result
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [dept, setDept] = useState("");
  const [doctorId, setDoctorId] = useState(presetDoctor || "");
  const [slots, setSlots] = useState(null);
  const [day, setDay] = useState(null);
  const [slot, setSlot] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/departments").then(setDepartments).catch(() => {});
    api("/doctors").then((d) => {
      const active = d.filter((x) => x.active);
      setDoctors(active);
      if (presetDoctor) setDept((active.find((x) => x._id === presetDoctor) || {}).department || "");
    }).catch(() => {});
  }, [presetDoctor]);

  // look up the patient once 10 digits are typed
  useEffect(() => {
    const digits = phone.replace(/\D/g, "");
    if (digits.length < 10) { setFound(null); return; }
    const id = setTimeout(() => {
      api("/patients/lookup", { params: { phone } }).then((r) => {
        setFound(r);
        if (r.found) {
          setName((n) => n || r.name || "");
        }
      }).catch(() => setFound(null));
    }, 300);
    return () => clearTimeout(id);
  }, [phone]);

  // load free slots when a doctor is chosen
  useEffect(() => {
    setSlots(null); setDay(null); setSlot(null);
    if (!doctorId) return;
    api(`/doctors/${doctorId}/slots`).then((d) => {
      setSlots(d);
      const days = Object.keys(d.free || {});
      if (days.length) setDay(days[0]);
    }).catch((e) => setSlots({ error: e.message, free: {} }));
  }, [doctorId]);

  const deptDoctors = useMemo(() => doctors.filter((d) => !dept || d.department === dept), [doctors, dept]);
  const doctor = doctors.find((d) => d._id === doctorId);
  const days = slots ? Object.keys(slots.free || {}) : [];
  const ready = phone && name && doctorId && slot && reason.trim().length >= 3;

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const a = await api("/appointments", { method: "POST", body: { doctor_id: doctorId, start: slot, name, phone, email, reason } });
      notify(`${a._id} booked: ${a.patient_name} with ${a.doctor_name}, ${fmtDateTime(a.start)}${a.chat_id ? " – patient told on Telegram" : ""}`);
      onDone(a);
    } catch (e) {
      setError(e.message);
      if (e.status === 409 && doctorId) { // slot just taken -> reload slots
        api(`/doctors/${doctorId}/slots`).then(setSlots).catch(() => {});
        setSlot(null);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal show onHide={onClose} centered size="lg" scrollable>
      <Modal.Header closeButton>
        <Modal.Title as="h5"><i className="bi bi-calendar2-plus me-2" style={{ color: "var(--primary)" }} />New appointment <span className="text-muted fs-6">· walk-in / phone</span></Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {error && <Alert variant="danger" className="py-2 small">{error}</Alert>}

        <div className="small fw-semibold text-uppercase text-muted mb-2">1 · Patient</div>
        <Row className="g-2 mb-2">
          <Col md={4}>
            <Form.Label className="small mb-1">Mobile number *</Form.Label>
            <Form.Control value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="98765 43210" inputMode="tel" autoFocus />
          </Col>
          <Col md={4}>
            <Form.Label className="small mb-1">Full name *</Form.Label>
            <Form.Control value={name} onChange={(e) => setName(e.target.value)} placeholder="Patient name" />
          </Col>
          <Col md={4}>
            <Form.Label className="small mb-1">Email (optional)</Form.Label>
            <Form.Control type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="leave blank = no email" />
            {found && found.found && found.email && !email && (
              <button type="button" className="btn btn-link btn-sm p-0 small" onClick={() => setEmail(found.email)}>Use saved: {found.email}</button>
            )}
          </Col>
        </Row>
        {found && found.found && (
          <div className="ai-box small mb-3">
            <i className="bi bi-person-check me-1" /> Existing patient · {found.visits} earlier visit{found.visits === 1 ? "" : "s"}
            {found.telegram ? <> · <b>on Telegram</b> – will get a confirmation and reminders there</> : <> · <b>not on Telegram yet</b> – ask them to open the clinic bot and share this number; the booking links automatically and they get the confirmation + reminders</>}
          </div>
        )}
        {found && !found.found && <div className="small text-muted mb-3"><i className="bi bi-person-plus me-1" />New patient · not on Telegram yet – ask them to open the clinic bot and share this number to get the confirmation + reminders</div>}

        <div className="small fw-semibold text-uppercase text-muted mb-2 mt-3">2 · Doctor</div>
        <div className="d-flex flex-wrap gap-2 mb-2">
          <button className={"btn btn-sm " + (!dept ? "btn-primary" : "btn-soft")} onClick={() => setDept("")}>All</button>
          {departments.map((d) => (
            <button key={d._id} className={"btn btn-sm " + (dept === d._id ? "btn-primary" : "btn-soft")} onClick={() => setDept(d._id)}>{d.name_en}</button>
          ))}
        </div>
        <Row className="g-2 mb-3">
          {deptDoctors.map((d) => {
            const today = (d.slots || {})[WEEK[new Date().getDay()]];
            return (
              <Col md={6} key={d._id}>
                <button className={"doctor-card d-flex align-items-center gap-2" + (doctorId === d._id ? " selected" : "")} onClick={() => setDoctorId(d._id)}>
                  <Avatar name={d.name} round size="sm" />
                  <span className="flex-grow-1">
                    <span className="d-block fw-semibold">{d.name}</span>
                    <span className="d-block small text-muted">{(departments.find((x) => x._id === d.department) || {}).name_en} · today {today ? today.replace(/,/g, ", ") : "off"}</span>
                  </span>
                </button>
              </Col>
            );
          })}
        </Row>

        {doctorId && (
          <>
            <div className="small fw-semibold text-uppercase text-muted mb-2">3 · Date & time</div>
            {!slots && <div className="text-muted small mb-3"><Spinner size="sm" className="me-2" />Loading free slots from Cal.com…</div>}
            {slots && slots.error && <Alert variant="warning" className="py-2 small">{slots.error}</Alert>}
            {slots && !slots.error && days.length === 0 && <Alert variant="info" className="py-2 small">{doctor?.name} has no free slots in the next {slots.days_ahead} days.</Alert>}
            {days.length > 0 && (
              <>
                <div className="d-flex flex-wrap gap-2 mb-2">
                  {days.map((d) => (
                    <button key={d} className={"btn btn-sm " + (d === day ? "btn-primary" : "btn-soft")} onClick={() => { setDay(d); setSlot(null); }}>
                      {dayLabel(d)} <span className="opacity-75">({slots.free[d].length})</span>
                    </button>
                  ))}
                </div>
                <div className="slot-grid mb-3">
                  {(slots.free[day] || []).map((iso) => (
                    <button key={iso} className={"slot-chip free" + (iso === slot ? " selected" : "")} onClick={() => setSlot(iso)}>{fmtTime(iso)}</button>
                  ))}
                </div>
              </>
            )}
          </>
        )}

        <div className="small fw-semibold text-uppercase text-muted mb-2">4 · Reason for visit</div>
        <Form.Control as="textarea" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Fever for 2 days" />
      </Modal.Body>
      <Modal.Footer>
        <span className="me-auto small">
          {ready ? <><b>{name}</b> · {doctor?.name} · <b>{fmtDateTime(slot)}</b></> : <span className="text-muted">Fill in patient, doctor, time and reason</span>}
        </span>
        <Button variant="light" onClick={onClose}>Cancel</Button>
        <Button onClick={confirm} disabled={!ready || busy}>{busy ? <Spinner size="sm" /> : "Book appointment"}</Button>
      </Modal.Footer>
    </Modal>
  );
}
