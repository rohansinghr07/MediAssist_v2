import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Dropdown, Toast, ToastContainer } from "react-bootstrap";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api.js";
import { Logo, PhoneArt } from "./components/Art.jsx";
import { Avatar, PageHead } from "./components/common.jsx";
import { ago, fmtDateTime } from "./utils.js";
import Login from "./pages/Login.jsx";
import Overview from "./pages/Overview.jsx";
import Appointments from "./pages/Appointments.jsx";
import Doctors from "./pages/Doctors.jsx";
import Tickets from "./pages/Tickets.jsx";
import Alerts from "./pages/Alerts.jsx";

const PAGES = [
  { key: "overview", label: "Dashboard", icon: "grid-1x2" },
  { key: "appointments", label: "Appointments", icon: "calendar2-week" },
  { key: "doctors", label: "Doctors & Slots", icon: "heart-pulse" },
  { key: "tickets", label: "Issues & Complaints", icon: "chat-square-text" },
  { key: "alerts", label: "Emergency Alerts", icon: "exclamation-octagon" },
];

const REFRESH_MS = 20000; // auto refresh so new bot bookings appear on their own

function TopSearch({ go }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    if (q.trim().length < 2) { setRows([]); return; }
    const id = setTimeout(() => api("/search", { params: { q } }).then(setRows).catch(() => setRows([])), 250);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function pick(r) {
    go(r.type === "appointment" ? "appointments" : "tickets", r.id);
    setOpen(false);
    setQ("");
  }

  return (
    <div className="search-box" ref={box}>
      <input className="form-control" placeholder="Search patient, phone or ID…" value={q}
             onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} />
      <i className="bi bi-search" />
      {open && q.trim().length >= 2 && (
        <div className="search-results">
          {rows.length === 0 && <div className="small text-muted p-2">No matches</div>}
          {rows.map((r) => (
            <button key={r.type + r.id} onClick={() => pick(r)}>
              <Avatar name={r.title} size="sm" />
              <span className="flex-grow-1 min-w-0">
                <span className="d-block fw-semibold">{r.title} <span className="font-monospace small text-muted">{r.id}</span></span>
                <span className="d-block small text-muted text-truncate">{r.sub}</span>
              </span>
              <i className={`bi bi-${r.type === "appointment" ? "calendar2-week" : "chat-square-text"} text-muted`} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(!!getToken());
  const [page, setPage] = useState("overview");
  const [seed, setSeed] = useState(null); // {page, q} - search text handed to a page
  const [tick, setTick] = useState(0);
  const [stats, setStats] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [lastSync, setLastSync] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);  // small screens: slide-in sidebar
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("ma-sidebar") === "mini"; } catch { return false; } });
  function toggleMenu() {
    if (window.matchMedia("(min-width: 1200px)").matches) {  // desktop: icons-only sidebar
      setCollapsed((c) => { try { localStorage.setItem("ma-sidebar", c ? "full" : "mini"); } catch { /* ignore */ } return !c; });
    } else {
      setMenuOpen((o) => !o);
    }
  }

  const logout = useCallback(() => {
    setToken(null);
    setLoggedIn(false);
  }, []);

  useEffect(() => setUnauthorizedHandler(logout), [logout]);

  const notify = useCallback((text, variant = "success") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, text, variant }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  const go = useCallback((key, q) => {
    setPage(key);
    setSeed(q ? { page: key, q, n: Date.now() } : null);
    setMenuOpen(false);
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
  }, [loggedIn, refresh]);

  useEffect(() => {
    if (!loggedIn) return;
    api("/stats").then((s) => { setStats(s); setLastSync(new Date()); }).catch(() => {});
    api("/alerts", { params: { status: "new" } }).then(setAlerts).catch(() => {});
  }, [loggedIn, tick]);

  if (!loggedIn) return <Login onLogin={() => setLoggedIn(true)} />;

  const openTickets = stats ? stats.open_issues + stats.open_complaints : 0;
  const bell = (stats?.new_alerts || 0) + openTickets;
  const current = PAGES.find((p) => p.key === page);
  const props = { tick, refresh, notify, stats, go, seed: seed && seed.page === page ? seed : null };

  return (
    <div className={"app-shell" + (collapsed ? " collapsed" : "")}>
      {menuOpen && <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />}
      <aside className={"sidebar" + (menuOpen ? " open" : "")}>
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">MediAssist</div>
            <div className="brand-sub">City Clinic, Kota</div>
          </div>
        </div>
        <nav>
          {PAGES.map((p) => (
            <button key={p.key} className={"nav-item" + (page === p.key ? " active" : "")} onClick={() => { go(p.key); setMenuOpen(false); }} title={p.label}>
              <i className={`bi bi-${p.icon}`} />
              <span>{p.label}</span>
              {p.key === "tickets" && openTickets > 0 && <Badge bg="warning" text="dark" pill>{openTickets}</Badge>}
              {p.key === "alerts" && stats?.new_alerts > 0 && <Badge bg="danger" pill>{stats.new_alerts}</Badge>}
            </button>
          ))}
        </nav>
        <div className="nav-label">Clinic</div>
        <nav>
          <div className="nav-item" style={{ cursor: "default" }} title="Aerodrome, Kota"><i className="bi bi-geo-alt" /><span className="small">Aerodrome, Kota</span></div>
          <div className="nav-item" style={{ cursor: "default" }} title="09:00 – 20:00 · Mon–Sat"><i className="bi bi-clock" /><span className="small">09:00 – 20:00 · Mon–Sat</span></div>
        </nav>
        <div className="sidebar-card">
          <PhoneArt />
          <div className="t">Patients book on Telegram &amp; web</div>
          <div className="s">Bookings, issues and alerts from the bot appear here live.</div>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <button className="icon-btn" onClick={toggleMenu} aria-label="Show or hide the menu" title="Show / hide menu"><i className="bi bi-list" /></button>
          <TopSearch go={go} />
          <div className="ms-auto d-flex align-items-center gap-2">
            <span className="live d-none d-lg-flex"><span className="live-dot" />Live · {lastSync ? lastSync.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", second: "2-digit" }) : "…"}</span>
            <button className="icon-btn orange" onClick={refresh} title="Refresh now"><i className="bi bi-arrow-clockwise" /></button>
            <Dropdown align="end">
              <Dropdown.Toggle as="button" className="icon-btn blue" bsPrefix="x" aria-label="Notifications">
                <i className="bi bi-bell" />
                {bell > 0 && <span className="dot">{bell > 99 ? "99+" : bell}</span>}
              </Dropdown.Toggle>
              <Dropdown.Menu style={{ width: 320 }}>
                <Dropdown.Header>Notifications</Dropdown.Header>
                {alerts.slice(0, 3).map((a) => (
                  <Dropdown.Item key={a._id} onClick={() => go("alerts")} className="text-wrap">
                    <i className="bi bi-exclamation-octagon-fill text-danger me-2" />
                    <b>Emergency</b> – {a.name || "patient"}: “{a.text}” <span className="text-muted small">· {ago(a.created_at)}</span>
                  </Dropdown.Item>
                ))}
                <Dropdown.Item onClick={() => go("tickets")}>
                  <i className="bi bi-chat-square-text text-warning me-2" />{openTickets} open issue{openTickets === 1 ? "" : "s"} / complaint{openTickets === 1 ? "" : "s"}
                </Dropdown.Item>
                <Dropdown.Item onClick={() => go("appointments")}>
                  <i className="bi bi-calendar2-check me-2" style={{ color: "var(--primary)" }} />{stats?.appointments_today ?? 0} appointment(s) today
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>
            <Dropdown align="end">
              <Dropdown.Toggle as="div" bsPrefix="x" className="user-chip ms-1" role="button">
                <span className="txt text-end">
                  <span className="n d-block">Admin</span>
                  <span className="r d-block">Clinic staff</span>
                </span>
                <Avatar name="Admin Staff" />
              </Dropdown.Toggle>
              <Dropdown.Menu>
                <Dropdown.ItemText className="small text-muted">Signed in · {fmtDateTime(new Date().toISOString())}</Dropdown.ItemText>
                <Dropdown.Divider />
                <Dropdown.Item onClick={logout}><i className="bi bi-box-arrow-right me-2" />Log out</Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>
          </div>
        </header>

        <div className="page-body">
          <PageHead title={current.label} />
          {page === "overview" && <Overview {...props} />}
          {page === "appointments" && <Appointments {...props} />}
          {page === "doctors" && <Doctors {...props} />}
          {page === "tickets" && <Tickets {...props} />}
          {page === "alerts" && <Alerts {...props} />}
        </div>
      </main>

      <ToastContainer position="bottom-end" className="p-3" style={{ zIndex: 2000 }}>
        {toasts.map((t) => (
          <Toast key={t.id} bg={t.variant} onClose={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
            <Toast.Body className={t.variant === "warning" || t.variant === "light" ? "" : "text-white"}>{t.text}</Toast.Body>
          </Toast>
        ))}
      </ToastContainer>
    </div>
  );
}
