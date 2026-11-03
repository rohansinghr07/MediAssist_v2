import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Row } from "react-bootstrap";
import { api } from "../api.js";
import { BannerArt } from "../components/Art.jsx";
import AppointmentsTable from "../components/AppointmentsTable.jsx";
import BookModal from "../components/BookModal.jsx";
import { BarList, ColumnChart, SERIES } from "../components/Charts.jsx";
import { Avatar, Empty, Loading, PriorityBadge, StatCard } from "../components/common.jsx";
import { ago, dayLabel, fmtTime, todayISO } from "../utils.js";

const FEED = {
  booking: { icon: "calendar2-plus", bg: "var(--primary-50)", fg: "var(--primary)" },
  cancel: { icon: "calendar2-x", bg: "#f1f2f6", fg: "#8c94a8" },
  issue: { icon: "tools", bg: "var(--amber-50)", fg: "#c98a00" },
  complaint: { icon: "chat-square-text", bg: "var(--blue-50)", fg: "var(--blue)" },
  alert: { icon: "exclamation-octagon", bg: "var(--red-50)", fg: "var(--red)" },
};

function greeting() {
  const h = Number(new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", hour12: false }));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function fmtRange(r) {
  // "10:00-13:00,16:00-19:00" -> "10–1, 4–7"
  const h = (t) => { const [hh, mm] = t.split(":").map(Number); const x = hh % 12 || 12; return mm ? `${x}:${String(mm).padStart(2, "0")}` : `${x}`; };
  return (r || "").split(",").filter(Boolean).map((p) => { const [a, b] = p.split("-"); return `${h(a)}–${h(b)}`; }).join(", ");
}

export default function Overview({ tick, refresh, notify, stats, go }) {
  const [today, setToday] = useState(null);
  const [ov, setOv] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [booking, setBooking] = useState(false);

  useEffect(() => {
    api("/appointments", { params: { day: todayISO() } }).then(setToday).catch(() => setToday([]));
    api("/overview").then(setOv).catch(() => setOv({ days: [], by_department: [], doctors_today: [], activity: [] }));
    api("/alerts", { params: { status: "new" } }).then(setAlerts).catch(() => {});
  }, [tick]);

  const activeToday = (today || []).filter((a) => a.status !== "cancelled");
  const onDuty = ov ? ov.doctors_today.filter((d) => d.today).length : 0;
  const next = ov?.next_patient;
  const chartData = (ov?.days || []).map((d, i) => ({
    label: i === 0 ? "Today" : dayLabel(d.date).split(",")[0],
    full: dayLabel(d.date),
    values: { booked: d.booked, cancelled: d.cancelled },
  }));

  return (
    <>
      {alerts.length > 0 && (
        <Alert variant="danger" className="d-flex align-items-center border-0" style={{ borderRadius: 10 }}>
          <i className="bi bi-exclamation-octagon-fill fs-4 me-3" />
          <div className="flex-grow-1">
            <strong>{alerts.length} new emergency alert{alerts.length > 1 ? "s" : ""}</strong> – latest from {alerts[0].name || "a patient"} ({ago(alerts[0].created_at)}): “{alerts[0].text}”
          </div>
          <Button variant="danger" size="sm" onClick={() => go("alerts")}>Open alerts</Button>
        </Alert>
      )}

      <Row className="g-4">
        <Col xl={8}>
          <div className="welcome mb-4">
            <BannerArt />
            <div className="flex-grow-1">
              <h2>{greeting()}, Admin</h2>
              <p>
                Today at City Clinic, Kota: <b>{activeToday.length}</b> appointment{activeToday.length === 1 ? "" : "s"} and <b>{onDuty}</b> doctor{onDuty === 1 ? "" : "s"} on duty.
                {next ? <> Next patient: <b>{next.patient_name}</b> at <b>{fmtTime(next.start)}</b> with {next.doctor_name}.</> : " No more patients waiting today."}
              </p>
            </div>
            <div className="d-flex flex-column gap-2 flex-shrink-0">
              <Button onClick={() => setBooking(true)}><i className="bi bi-plus-lg me-1" />New appointment</Button>
              <Button variant="soft" className="btn-soft" onClick={() => go("appointments")}>View schedule</Button>
            </div>
          </div>

          <div className="stat-grid mb-4">
            <StatCard label="Today's visits" value={stats?.appointments_today} icon="calendar2-check" tone="primary" onClick={() => go("appointments")} />
            <StatCard label="Upcoming" value={stats?.upcoming} icon="calendar2-week" tone="blue" onClick={() => go("appointments")} hint={stats ? `${stats.booked_today_via_bot} new today` : ""} />
            <StatCard label="Open tickets" value={stats ? stats.open_issues + stats.open_complaints : null} icon="chat-square-text" tone="orange" onClick={() => go("tickets")} />
            <StatCard label="Active doctors" value={stats?.doctors_active} icon="heart-pulse" tone="green" onClick={() => go("doctors")} hint={`${onDuty} on duty today`} />
          </div>

          <Row className="g-4 mb-4">
            <Col md={7}>
              <Card className="h-100">
                <Card.Header><span className="title">Appointments – next 7 days</span></Card.Header>
                <Card.Body>
                  {ov === null ? <Loading /> : (
                    <ColumnChart height={210} ariaLabel="Appointments per day for the next 7 days" data={chartData}
                      series={[{ key: "booked", name: "Booked", color: SERIES.primary }, { key: "cancelled", name: "Cancelled", color: SERIES.secondary }]} />
                  )}
                </Card.Body>
              </Card>
            </Col>
            <Col md={5}>
              <Card className="h-100">
                <Card.Header><span className="title">Upcoming by department</span></Card.Header>
                <Card.Body>
                  {ov === null ? <Loading /> : <BarList data={ov.by_department.map((d) => ({ label: d.department, value: d.count }))} />}
                </Card.Body>
              </Card>
            </Col>
          </Row>

          <Card>
            <Card.Header className="d-flex align-items-center">
              <span className="title">Today's appointments</span>
              <span className="text-muted small ms-2">{activeToday.length} active</span>
              <Button size="sm" variant="link" className="ms-auto text-decoration-none" onClick={() => go("appointments")}>All appointments <i className="bi bi-chevron-right" /></Button>
            </Card.Header>
            <Card.Body className="p-0">
              {today === null ? <Loading /> : <AppointmentsTable rows={today} refresh={refresh} notify={notify} showDate={false} compact />}
            </Card.Body>
          </Card>
        </Col>

        <Col xl={4}>
          <Card className="mb-4">
            <Card.Header className="d-flex align-items-center">
              <span className="title">Doctors today</span>
              <Button size="sm" variant="link" className="ms-auto text-decoration-none" onClick={() => go("doctors")}>All doctors <i className="bi bi-chevron-right" /></Button>
            </Card.Header>
            <Card.Body className="py-2">
              {ov === null ? <Loading /> : ov.doctors_today.length === 0 ? <Empty icon="person-badge" text="No active doctors." /> : (
                [...ov.doctors_today].sort((a, b) => (b.on_duty - a.on_duty) || (!!b.today - !!a.today)).map((d) => (
                  <div className="doctor-row" key={d._id}>
                    <Avatar name={d.name} round />
                    <div className="flex-grow-1 min-w-0">
                      <div className="fw-semibold text-truncate">{d.name}</div>
                      <div className="small text-muted text-truncate">{d.department} · {d.today ? fmtRange(d.today) : "not today"}</div>
                    </div>
                    <div className="text-end">
                      <span className={`duty ${d.on_duty ? "on" : d.today ? "later" : "off"}`}>{d.on_duty ? "On duty" : d.today ? "Today" : "Off"}</span>
                      {d.booked_today > 0 && <div className="small text-muted mt-1">{d.booked_today} booked</div>}
                    </div>
                  </div>
                ))
              )}
            </Card.Body>
          </Card>

          <Card>
            <Card.Header><span className="title">Recent activity</span></Card.Header>
            <Card.Body>
              {ov === null ? <Loading /> : ov.activity.length === 0 ? <Empty icon="activity" text="Nothing yet." /> : (
                <div className="feed">
                  {ov.activity.slice(0, 7).map((a, i) => {
                    const f = FEED[a.kind] || FEED.booking;
                    return (
                      <div className="feed-item" key={a.kind + a.id + i}>
                        <span className="feed-ic" style={{ background: f.bg, color: f.fg }}><i className={`bi bi-${f.icon}`} /></span>
                        <div className="min-w-0">
                          <div className="tx">{a.text}</div>
                          <div className="tm"><span className="font-monospace">{a.id}</span> · {ago(a.at)} {a.priority && <PriorityBadge priority={a.priority} />}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>
      {booking && <BookModal notify={notify} onClose={() => setBooking(false)} onDone={() => { setBooking(false); refresh(); }} />}
    </>
  );
}
