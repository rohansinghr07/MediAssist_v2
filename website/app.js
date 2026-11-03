// City Clinic, Kota – public website. Loads live clinic data from the MediAssist backend (/api/public/*).
(function () {
  "use strict";
  const TZ = "Asia/Kolkata";
  const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"]];
  const DEPT_ICON = {
    general_medicine: ["bi-heart-pulse", "#f1f0fe", "#5156be"],
    pediatrics: ["bi-balloon-heart", "#fff6e0", "#b97900"],
    orthopedics: ["bi-person-walking", "#e8f3fe", "#2f7fd6"],
    dermatology: ["bi-droplet-half", "#e6f6f0", "#05825f"],
  };
  const AV = [["#f3f3ff", "#5156be"], ["#fff6e0", "#b97900"], ["#e6f6f0", "#05825f"], ["#e8f3fe", "#2f7fd6"], ["#fdecf0", "#d42a4e"], ["#f4ecff", "#7c3aed"]];
  let bot = null;
  let data = null;
  let filter = "all";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- helpers
  function todayKey() {
    const wd = new Date().toLocaleDateString("en-US", { weekday: "short", timeZone: TZ }).toLowerCase();
    return wd.slice(0, 3);
  }
  function hour12(hhmm) {
    let [h, m] = hhmm.split(":").map(Number);
    const ap = h >= 12 ? "pm" : "am";
    h = h % 12 || 12;
    return m ? `${h}:${String(m).padStart(2, "0")}` + ap : h + ap;
  }
  function ranges(text) {
    if (!text) return [];
    return text.split(",").map((r) => r.trim().split("-").map(hour12).join("–"));
  }
  function avatar(name) {
    const clean = name.replace(/^Dr\.?\s+/i, "").trim();
    const ini = clean.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
    let h = 0;
    for (const ch of clean) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    const [bg, fg] = AV[h % AV.length];
    return `<span class="avatar" style="background:${bg};color:${fg}">${esc(ini)}</span>`;
  }
  const fmtDate = (iso) => new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: TZ });
  const fmtTime = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: TZ });
  const fmtDT = (iso) => `${fmtDate(iso)}, ${fmtTime(iso)}`;

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast.id);
    toast.id = setTimeout(() => (t.hidden = true), 4500);
  }

  // ---------- Telegram deep links: data-tg="book" | "doc_DR001" | "appts" | "issue" | "complaint"
  function tgLink(action) {
    return bot ? `https://t.me/${bot}?start=${encodeURIComponent(action)}` : null;
  }
  function wireTelegram(root = document) {
    $$("[data-tg]", root).forEach((a) => {
      const href = tgLink(a.dataset.tg);
      if (href) {
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener";
      }
    });
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-tg]");
    if (a && !bot) {
      e.preventDefault();
      toast("Online booking opens soon. Please visit the clinic reception to book.");
    }
  });

  // ---------- clinic details
  function fillClinic(c) {
    $$('[data-clinic="name"]').forEach((el) => (el.textContent = c.name));
    $$('[data-clinic="address"]').forEach((el) => (el.textContent = c.address));
    $$('[data-clinic="phone-or-email"]').forEach((el) => (el.textContent = c.phone || c.email));
    $$('[data-clinic="email-link"]').forEach((el) => { el.textContent = c.email; el.href = "mailto:" + c.email; });
    if (c.phone) {
      $("#phoneRow").hidden = false;
      const a = $('[data-clinic="phone-link"]');
      a.textContent = c.phone;
      a.href = "tel:" + c.phone.replace(/[^\d+]/g, "");
    }
    const q = encodeURIComponent(c.map_query || c.address);
    $("#mapFrame").src = `https://www.google.com/maps?q=${q}&output=embed`;
    $("#directions").href = `https://www.google.com/maps/search/?api=1&query=${q}`;
  }

  // ---------- departments
  function renderDepartments() {
    $("#deptGrid").innerHTML = data.departments.map((d) => {
      const [icon, bg, fg] = DEPT_ICON[d.id] || ["bi-hospital", "#f1f0fe", "#5156be"];
      return `<button class="dept" data-dept="${esc(d.id)}" type="button">
        <i class="bi ${icon}" style="background:${bg};color:${fg}"></i>
        <h3>${esc(d.name)}</h3><span class="hi">${esc(d.name_hi || "")}</span>
        <span class="count">${d.doctors} doctor${d.doctors === 1 ? "" : "s"} →</span>
      </button>`;
    }).join("");
    $$(".dept").forEach((b) => b.addEventListener("click", () => {
      setFilter(b.dataset.dept);
      document.getElementById("doctors").scrollIntoView();
    }));
  }

  // ---------- doctors
  function renderFilters() {
    const items = [{ id: "all", name: "All doctors" }, ...data.departments.filter((d) => d.doctors)];
    $("#filters").innerHTML = items.map((d) =>
      `<button type="button" role="tab" data-f="${esc(d.id)}" aria-selected="${filter === d.id}">${esc(d.name)}</button>`).join("");
    $$("#filters button").forEach((b) => b.addEventListener("click", () => setFilter(b.dataset.f)));
  }
  function setFilter(f) {
    filter = f;
    renderFilters();
    renderDoctors();
  }
  function renderDoctors() {
    const deptName = Object.fromEntries(data.departments.map((d) => [d.id, d.name]));
    const today = todayKey();
    const list = data.doctors.filter((d) => filter === "all" || d.department === filter);
    $("#docGrid").innerHTML = list.map((d) => {
      const todayR = ranges(d.slots[today]);
      const todayHtml = todayR.length
        ? `<div class="today"><i class="bi bi-circle-fill" style="font-size:.5rem"></i> Available today · ${esc(todayR.join(", "))}</div>`
        : `<div class="today off"><i class="bi bi-moon"></i> Not available today</div>`;
      const week = DAYS.map(([k, label]) => {
        const r = ranges(d.slots[k]);
        return `<div class="${r.length ? "" : "off"} ${k === today ? "is-today" : ""}"><b>${label}</b>${r.length ? r.map(esc).join("<br>") : "–"}</div>`;
      }).join("");
      return `<article class="doc">
        <div class="doc-top">${avatar(d.name)}<div><h3>${esc(d.name)}</h3>
          <div class="meta">${esc(deptName[d.department] || d.department)}${d.experience_years ? ` · ${d.experience_years} yrs experience` : ""}</div></div></div>
        ${todayHtml}
        <div class="week" aria-label="Weekly timings">${week}</div>
        <a class="btn btn-soft" data-tg="doc_${esc(d.id)}" href="#how"><i class="bi bi-telegram"></i> Book with ${esc(d.name.replace(/^Dr\.?\s*/, "Dr. ").split(" ").slice(0, 2).join(" "))}</a>
      </article>`;
    }).join("") || `<p class="muted">No doctors in this department right now.</p>`;
    wireTelegram($("#docGrid"));
  }

  // ---------- track
  const APPT_STATUS = {
    booked: ["Confirmed", "green"], past: ["Visit time passed", "grey"], cancelled: ["Cancelled", "red"],
    completed: ["Visit completed", "blue"], no_show: ["Missed", "amber"],
  };
  const TICKET_STATUS = { pending: ["Pending", "amber"], in_progress: ["In progress", "blue"], resolved: ["Resolved", "green"] };
  const BY = { clinic: "by the clinic", calcom: "via email link", patient: "by you" };

  function itemHtml(r) {
    let html;
    if (r.kind === "appointment") {
      const [label, tone] = APPT_STATUS[r.status] || [r.status, "grey"];
      const timeline = [`<li>Booked on ${esc(fmtDT(r.booked_at))} · ${esc(r.booked_via)}</li>`]
        .concat(r.moves.map((m) => `<li>Moved ${esc(BY[m.by] || "")} to ${esc(fmtDT(m.to))}</li>`))
        .concat(r.status === "cancelled" ? [`<li>Cancelled ${esc(BY[r.cancelled_by] || "")}</li>`] : [])
        .concat(r.attendance_confirmed && r.status === "booked" ? ["<li>You confirmed you will come</li>"] : []);
      html = `<div class="result-head"><b>${esc(r.id)}</b><span class="badge ${tone}">${esc(label)}</span></div>
        <dl class="rows">
          <dt>Patient</dt><dd>${esc(r.patient)}</dd>
          <dt>Doctor</dt><dd>${esc(r.doctor)}</dd>
          <dt>Department</dt><dd>${esc(r.department)}</dd>
          <dt>Date</dt><dd>${esc(fmtDate(r.start))}</dd>
          <dt>Time</dt><dd>${esc(fmtTime(r.start))}</dd>
        </dl>
        <ul class="timeline">${timeline.join("")}</ul>
        ${r.status === "booked" ? `<p class="hint">To reschedule or cancel: <a data-tg="appts" href="#how">open My Appointments on Telegram</a> or ask at reception.</p>` : ""}`;
    } else {
      const [label, tone] = TICKET_STATUS[r.status] || [r.status, "grey"];
      const notes = r.notes.map((n) => `<li>${esc(fmtDate(n.at))}: ${esc(n.text)}</li>`).join("");
      html = `<div class="result-head"><b>${esc(r.id)}</b><span class="badge ${tone}">${esc(label)}</span></div>
        <dl class="rows">
          <dt>Type</dt><dd>${r.kind === "complaint" ? "Complaint" : "Issue"}</dd>
          <dt>Category</dt><dd>${esc(r.category || "–")}</dd>
          ${r.summary ? `<dt>About</dt><dd>${esc(r.summary)}</dd>` : ""}
          <dt>Raised</dt><dd>${esc(fmtDT(r.raised_at))}</dd>
          <dt>Last update</dt><dd>${esc(fmtDT(r.updated_at))}</dd>
        </dl>
        ${r.details_hidden ? `<p class="hint">For your privacy, details and the clinic's replies show when you search with your <b>mobile number</b>.</p>`
          : notes ? `<p class="hint" style="margin-bottom:.2rem"><b>Updates from the clinic</b></p><ul class="timeline">${notes}</ul>` : `<p class="hint">Our team replies within 24 hours.</p>`}`;
    }
    return `<div class="result">${html}</div>`;
  }

  function renderResults(items, byPhone) {
    const box = $("#trackResult");
    const head = byPhone
      ? `<p class="hint result-count">${items.length} result${items.length === 1 ? "" : "s"} for this number (last 60 days). Your tracking ID is shown on each.</p>`
      : "";
    box.innerHTML = head + items.map(itemHtml).join("");
    wireTelegram(box);
  }

  $("#trackForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button");
    const q = $("#tq").value.trim();
    const box = $("#trackResult");
    const isId = /(APT|ISS|CMP)\s*-?\s*\d+/i.test(q);
    if (!isId && q.replace(/\D/g, "").length < 10) {
      box.innerHTML = `<div class="error">Enter a tracking ID (e.g. APT-0001) or your 10-digit mobile number.</div>`;
      return;
    }
    btn.disabled = true;
    btn.innerHTML = `<i class="bi bi-hourglass-split"></i> Checking…`;
    try {
      const res = await fetch("/api/public/track", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not check right now. Please try again.");
      renderResults(body.items || [], !isId);
    } catch (err) {
      box.innerHTML = `<div class="error">${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<i class="bi bi-search"></i> Check status`;
    }
  });
  // ?track=APT-0001 in the URL pre-fills the ID
  const pre = new URLSearchParams(location.search).get("track");
  if (pre) $("#tq").value = pre;

  // ---------- mobile menu
  $("#menuBtn").addEventListener("click", () => {
    const open = $("#links").classList.toggle("open");
    $("#menuBtn").setAttribute("aria-expanded", open);
  });
  $$("#links a").forEach((a) => a.addEventListener("click", () => $("#links").classList.remove("open")));
  $("#year").textContent = new Date().getFullYear();

  // ---------- load
  fetch("/api/public/info")
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((d) => {
      data = d;
      bot = d.bot_username;
      fillClinic(d.clinic);
      $$('[data-count="doctors"]').forEach((el) => (el.textContent = d.doctors.length));
      $$('[data-count="departments"]').forEach((el) => (el.textContent = d.departments.filter((x) => x.doctors).length));
      renderDepartments();
      renderFilters();
      renderDoctors();
      wireTelegram();
    })
    .catch(() => {
      $("#docGrid").innerHTML = `<p class="muted">Doctor timings could not be loaded right now. Please refresh the page.</p>`;
    });
})();
