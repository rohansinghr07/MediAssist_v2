import { useEffect, useMemo, useState } from "react";
import { Button, Card, Col, Form, Row, Spinner } from "react-bootstrap";
import { api } from "../api.js";
import AppointmentsTable from "../components/AppointmentsTable.jsx";
import BookModal from "../components/BookModal.jsx";
import { Loading } from "../components/common.jsx";
import { todayISO } from "../utils.js";

const VIEWS = [
  { key: "upcoming", label: "Upcoming" },
  { key: "day", label: "By date" },
  { key: "all", label: "All" },
];

export default function Appointments({ tick, refresh, notify, seed }) {
  const [view, setView] = useState("upcoming");
  const [day, setDay] = useState(todayISO());
  const [doctor, setDoctor] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState(null);
  const [doctors, setDoctors] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [booking, setBooking] = useState(false);

  async function syncNow() {
    setSyncing(true);
    try {
      const r = await api("/sync/calcom", { method: "POST" });
      const changed = r.cancelled + r.rescheduled;
      notify(changed ? `Cal.com sync: ${r.cancelled} cancelled, ${r.rescheduled} moved` : `Cal.com sync: all ${r.checked} bookings match`, changed ? "warning" : "success");
      refresh();
    } catch (e) {
      notify(e.message, "danger");
    } finally {
      setSyncing(false);
    }
  }

  useEffect(() => {
    api("/doctors").then(setDoctors).catch(() => {});
  }, []);

  useEffect(() => {
    if (seed) { setView("all"); setStatus(""); setDoctor(""); setSearch(seed.q); }
  }, [seed]);

  useEffect(() => {
    const params = { doctor_id: doctor, status };
    if (view === "upcoming") params.upcoming = true;
    if (view === "day") params.day = day;
    api("/appointments", { params }).then(setRows).catch((e) => { notify(e.message, "danger"); setRows([]); });
  }, [tick, view, day, doctor, status, notify]);

  const filtered = useMemo(() => {
    if (!rows) return null;
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((a) => [a._id, a.patient_name, a.phone, a.reason].some((v) => (v || "").toLowerCase().includes(q)));
  }, [rows, search]);

  return (
    <Card>
      <Card.Header>
        <Row className="g-2 align-items-center">
          <Col xs="auto">
            <div className="seg">
              {VIEWS.map((v) => (
                <button key={v.key} className={view === v.key ? "on" : ""} onClick={() => setView(v.key)}>{v.label}</button>
              ))}
            </div>
          </Col>
          {view === "day" && (
            <Col xs="auto">
              <Form.Control size="sm" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
            </Col>
          )}
          <Col xs="auto">
            <Form.Select size="sm" value={doctor} onChange={(e) => setDoctor(e.target.value)}>
              <option value="">All doctors</option>
              {doctors.map((d) => <option key={d._id} value={d._id}>{d.name}</option>)}
            </Form.Select>
          </Col>
          <Col xs="auto">
            <Form.Select size="sm" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any status</option>
              <option value="booked">Booked</option>
              <option value="cancelled">Cancelled</option>
              <option value="completed">Completed</option>
              <option value="no_show">No-show</option>
            </Form.Select>
          </Col>
          <Col>
            <Form.Control size="sm" placeholder="Search name, phone or ID…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </Col>
          <Col xs="auto" className="small text-muted">{filtered ? `${filtered.length} shown` : ""}</Col>
          <Col xs="auto">
            <Button size="sm" onClick={() => setBooking(true)}><i className="bi bi-plus-lg me-1" />New appointment</Button>
          </Col>
          <Col xs="auto">
            <Button size="sm" variant="soft" className="btn-soft" onClick={syncNow} disabled={syncing} title="Check Cal.com for bookings changed from email links or the Cal.com app (also runs automatically every 5 minutes)">
              {syncing ? <Spinner size="sm" /> : <><i className="bi bi-arrow-left-right me-1" />Sync with Cal.com</>}
            </Button>
          </Col>
        </Row>
      </Card.Header>
      <Card.Body className="p-0">
        {filtered === null ? <Loading /> : <AppointmentsTable rows={filtered} refresh={refresh} notify={notify} />}
      </Card.Body>
      {booking && <BookModal notify={notify} onClose={() => setBooking(false)} onDone={() => { setBooking(false); refresh(); }} />}
    </Card>
  );
}
