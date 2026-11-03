import { useEffect, useState } from "react";
import { Alert, Badge, Card, Col, OverlayTrigger, Row, Tooltip } from "react-bootstrap";
import { api } from "../api.js";
import { Avatar, Empty, Loading } from "../components/common.jsx";
import BookModal from "../components/BookModal.jsx";
import { TZ, dayLabel, fmtTime } from "../utils.js";

function localDay(iso) {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: TZ });
}

export default function Doctors({ tick, refresh, notify }) {
  const [booking, setBooking] = useState(false);
  const [doctors, setDoctors] = useState(null);
  const [departments, setDepartments] = useState({});
  const [selected, setSelected] = useState(null);
  const [board, setBoard] = useState(null);

  useEffect(() => {
    api("/doctors").then((d) => {
      setDoctors(d);
      setSelected((cur) => cur || (d.find((x) => x.active) || d[0] || {})._id || null);
    });
    api("/departments").then((list) => setDepartments(Object.fromEntries(list.map((x) => [x._id, x.name_en]))));
  }, [tick]);

  useEffect(() => {
    if (!selected) return;
    setBoard((b) => (b && b.doctor._id === selected ? b : null));
    api(`/doctors/${selected}/slots`).then(setBoard).catch((e) => setBoard({ error: e.message, free: {}, booked: [], doctor: { _id: selected } }));
  }, [selected, tick]);

  if (doctors === null) return <Loading />;
  if (!doctors.length) return <Empty icon="person-badge" text="No doctors yet. Run python scripts/seed.py in the backend folder." />;

  // Build day columns: free slots from Cal.com + booked appointments from our database
  let days = [];
  if (board && board.doctor) {
    const byDay = {};
    Object.entries(board.free || {}).forEach(([d, list]) => {
      byDay[d] = byDay[d] || [];
      list.forEach((iso) => byDay[d].push({ iso, kind: "free" }));
    });
    (board.booked || []).forEach((a) => {
      const d = localDay(a.start);
      byDay[d] = byDay[d] || [];
      byDay[d].push({ iso: a.start, kind: "booked", appt: a });
    });
    days = Object.keys(byDay).sort().map((d) => ({
      day: d,
      items: byDay[d].sort((x, y) => new Date(x.iso) - new Date(y.iso)),
    }));
  }

  const totalFree = board ? Object.values(board.free || {}).reduce((n, l) => n + l.length, 0) : 0;
  const totalBooked = board ? (board.booked || []).length : 0;

  return (
    <Row className="g-4">
      <Col lg={4} xl={3}>
        <div className="d-grid gap-2">
          {doctors.map((d) => (
            <button key={d._id} className={"doctor-card" + (selected === d._id ? " selected" : "")} onClick={() => setSelected(d._id)}>
              <div className="d-flex align-items-start">
                <span className="me-3"><Avatar name={d.name} round /></span>
                <div className="flex-grow-1 text-start">
                  <div className="fw-semibold">{d.name}</div>
                  <div className="small mt-1"><span className="dept-chip">{departments[d.department] || d.department}</span> <span className="text-muted ms-1">{d.experience_years} yrs</span></div>
                  <div className="mt-1">
                    {d.active ? <Badge bg="success">Active</Badge> : <Badge bg="secondary">Inactive</Badge>}
                    {d.cal_event_type_id ? <span className="small text-muted ms-2">Cal.com #{d.cal_event_type_id}</span> : <span className="small text-danger ms-2">No Cal.com link</span>}
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
        <div className="small text-muted mt-3">
          To add or change a doctor: edit <code>backend/data/seed_data.json</code> (name, department, weekly timings), then run <code>python scripts/setup_calcom_doctors.py</code> and <code>python scripts/seed.py</code>.
        </div>
      </Col>

      <Col lg={8} xl={9}>
        <Card>
          <Card.Header className="d-flex flex-wrap align-items-center gap-3">
            <strong>{board?.doctor?.name || "…"}</strong>
            {board && !board.error && (
              <>
                <span className="legend"><span className="slot-chip free sm" /> Free ({totalFree})</span>
                <span className="legend"><span className="slot-chip booked sm" /> Booked ({totalBooked})</span>
              </>
            )}
            <span className="ms-auto small text-muted d-none d-xl-inline">Next {board?.days_ahead || 7} days · live from Cal.com</span>
            <button className="btn btn-sm btn-primary" onClick={() => setBooking(true)} disabled={!board || !!board.error}><i className="bi bi-plus-lg me-1" />Book with this doctor</button>
          </Card.Header>
          <Card.Body>
            {(() => {
              const doc = doctors.find((x) => x._id === selected);
              if (!doc || !doc.slots) return null;
              const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]];
              return (
                <div className="weekly mb-3">
                  <div className="small fw-semibold mb-1"><i className="bi bi-clock me-1" />Weekly timings</div>
                  <div className="weekly-grid">
                    {DAYS.map(([k, label]) => (
                      <div key={k} className={"weekly-day" + (doc.slots[k] ? "" : " off") + (k === ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][new Date().getDay()] ? " today" : "")}>
                        <div className="weekly-label">{label}</div>
                        <div>{doc.slots[k] ? doc.slots[k].split(",").map((r) => <div key={r}>{r.replace("-", " – ")}</div>) : "Off"}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
            {!board && <Loading text="Loading slots from Cal.com…" />}
            {board && board.error && <Alert variant="warning" className="small">{board.error}</Alert>}
            {board && !board.error && days.length === 0 && <Empty icon="calendar-x" text="No free or booked slots in this period." />}
            <div className="day-board">
              {days.map(({ day, items }) => {
                const free = items.filter((i) => i.kind === "free").length;
                const booked = items.length - free;
                return (
                  <div key={day} className="day-col">
                    <div className="day-head">
                      <div className="fw-semibold">{dayLabel(day)}</div>
                      <div className="small text-muted">{free} free · {booked} booked</div>
                    </div>
                    <div className="slot-grid">
                      {items.map((it) =>
                        it.kind === "free" ? (
                          <span key={it.iso} className="slot-chip free">{fmtTime(it.iso)}</span>
                        ) : (
                          <OverlayTrigger key={it.appt._id} placement="top" overlay={
                            <Tooltip>{it.appt._id} · {it.appt.patient_name}<br />{it.appt.phone}<br />{it.appt.reason}</Tooltip>
                          }>
                            <span className="slot-chip booked">{fmtTime(it.iso)} · {it.appt.patient_name.split(" ")[0]}</span>
                          </OverlayTrigger>
                        )
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card.Body>
        </Card>
      </Col>
      {booking && <BookModal doctorId={selected} notify={notify} onClose={() => setBooking(false)} onDone={() => { setBooking(false); refresh(); }} />}
    </Row>
  );
}
