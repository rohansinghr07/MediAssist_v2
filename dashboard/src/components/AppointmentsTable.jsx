import { useState } from "react";
import { createPortal } from "react-dom";
import { Dropdown, Table } from "react-bootstrap";
import { api } from "../api.js";
import { ago, fmtDate, fmtTime } from "../utils.js";
import { CancelModal, RescheduleModal } from "./AppointmentModals.jsx";
import { ApptBadge, Avatar, Empty } from "./common.jsx";

export default function AppointmentsTable({ rows, refresh, notify, showDate = true, compact = false }) {
  const [cancelling, setCancelling] = useState(null);
  const [moving, setMoving] = useState(null);

  async function mark(appt, status) {
    try {
      await api(`/appointments/${appt._id}`, { method: "PATCH", body: { status } });
      notify(`${appt._id} marked as ${status === "no_show" ? "no-show" : "completed"}`);
      refresh();
    } catch (e) {
      notify(e.message, "danger");
    }
  }

  if (!rows.length) return <Empty icon="calendar-x" text="No appointments here." />;

  const isPast = (a) => new Date(a.start) < new Date();

  return (
    <>
      <div className="table-responsive">
        <Table hover className="align-middle mb-0 appt-table">
          <thead>
            <tr>
              <th>{showDate ? "Date & time" : "Time"}</th>
              <th>Patient</th>
              <th>Doctor</th>
              {!compact && <th>Reason</th>}
              <th>Status</th>
              {!compact && <th>Booked</th>}
              <th className="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a._id} className={a.status !== "booked" ? "row-muted" : ""}>
                <td className="text-nowrap">
                  {showDate && <div className="fw-semibold">{fmtDate(a.start)}</div>}
                  <div className={showDate ? "text-muted small" : "fw-semibold"}>{fmtTime(a.start)}</div>
                </td>
                <td>
                  <div className="d-flex align-items-center gap-2">
                    <Avatar name={a.patient_name} size="sm" />
                    <div>
                      <div className="fw-semibold">{a.patient_name}</div>
                      <div className="text-muted small">{a.phone} · <span className="font-monospace">{a._id}</span></div>
                    </div>
                  </div>
                </td>
                <td>
                  <div>{a.doctor_name}</div>
                  <div className="text-muted small text-capitalize">{(a.department || "").replace(/_/g, " ")}</div>
                </td>
                {!compact && (
                  <td className="reason-cell">
                    {a.reason || "–"}
                    {a.symptoms && a.symptoms !== a.reason && <div className="text-muted small">Symptoms: {a.symptoms}</div>}
                  </td>
                )}
                <td>
                  <ApptBadge status={a.status} />
                  {a.status === "booked" && a.attendance_confirmed && <div className="small text-success mt-1"><i className="bi bi-check2-circle" /> Confirmed</div>}
                  {a.status === "cancelled" && <div className="small text-muted mt-1">{{ patient: "by patient", clinic: "by clinic", calcom: "via Cal.com / email" }[a.cancelled_by] || ""}</div>}
                  {a.history && a.history.length > 0 && <div className="small text-muted mt-1"><i className="bi bi-arrow-repeat" /> moved {a.history.length}×</div>}
                </td>
                {!compact && (
                  <td className="small text-muted text-nowrap">
                    {a.source === "reception"
                      ? <span title={`Booked at reception by ${a.booked_by || "staff"}`}><i className="bi bi-building" style={{ color: "var(--primary)" }} /> Reception</span>
                      : a.source === "website"
                        ? <span title="Booked by the patient in the website chat"><i className="bi bi-globe2" style={{ color: "var(--primary)" }} /> Website</span>
                        : <span title="Booked by the patient on Telegram"><i className="bi bi-telegram text-info" /> Telegram</span>}
                    <div>{ago(a.created_at)}</div>
                  </td>
                )}
                <td className="text-end">
                  {a.status === "booked" ? (
                    <Dropdown align="end">
                      <Dropdown.Toggle size="sm" variant="outline-secondary">Actions</Dropdown.Toggle>
                      {createPortal(<Dropdown.Menu popperConfig={{ strategy: "fixed" }} className="shadow">
                        {!isPast(a) && <Dropdown.Item onClick={() => setMoving(a)}><i className="bi bi-arrow-repeat me-2" />Reschedule</Dropdown.Item>}
                        {!isPast(a) && <Dropdown.Item className="text-danger" onClick={() => setCancelling(a)}><i className="bi bi-x-circle me-2" />Cancel</Dropdown.Item>}
                        {!isPast(a) && <Dropdown.Divider />}
                        <Dropdown.Item onClick={() => mark(a, "completed")}><i className="bi bi-check2-all me-2" />Mark completed</Dropdown.Item>
                        <Dropdown.Item onClick={() => mark(a, "no_show")}><i className="bi bi-person-x me-2" />Mark no-show</Dropdown.Item>
                      </Dropdown.Menu>, document.body)}
                    </Dropdown>
                  ) : (
                    <span className="text-muted small">–</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      {cancelling && <CancelModal appt={cancelling} notify={notify} onClose={() => setCancelling(null)} onDone={() => { setCancelling(null); refresh(); }} />}
      {moving && <RescheduleModal appt={moving} notify={notify} onClose={() => setMoving(null)} onDone={() => { setMoving(null); refresh(); }} />}
    </>
  );
}
