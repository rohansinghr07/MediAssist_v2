// "Chat with Bot" – the clinic assistant inside the website. Same engine as the Telegram bot (backend /api/chat).
(function () {
  "use strict";
  const KEY = "mediassist_chat_token";
  const $ = (s) => document.querySelector(s);
  const panel = $("#chatPanel"), log = $("#chatLog"), form = $("#chatForm"), input = $("#chatText");
  const launcher = $("#chatLauncher"), micBtn = $("#chatMic"), status = $("#chatStatus");
  let token = null, lastId = null, busy = false, pollTimer = null, started = false;
  const seen = new Set();

  // ---------- token (kept in this browser so the patient continues their conversation)
  function loadToken() { try { return localStorage.getItem(KEY); } catch { return null; } }
  function saveToken(t) { token = t; try { localStorage.setItem(KEY, t); } catch { /* private mode: keep in memory */ } }

  // ---------- safe rendering of bot messages (they use <b> / <i> like Telegram)
  const ALLOWED = new Set(["B", "STRONG", "I", "EM", "U", "CODE"]);
  function renderInto(el, html) {
    const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
    const walk = (src, dst) => {
      src.childNodes.forEach((n) => {
        if (n.nodeType === 3) {
          n.textContent.split("\n").forEach((part, i) => {
            if (i) dst.appendChild(document.createElement("br"));
            if (part) dst.appendChild(document.createTextNode(part));
          });
        } else if (n.nodeType === 1) {
          if (ALLOWED.has(n.tagName)) { const c = document.createElement(n.tagName.toLowerCase()); walk(n, c); dst.appendChild(c); }
          else walk(n, dst); // unknown tag: keep only its text
        }
      });
    };
    walk(doc.body.firstChild, el);
  }

  // ---------- messages
  function disableOldButtons() {
    log.querySelectorAll(".chat-btns:not(.used) button").forEach((b) => (b.disabled = true));
  }
  function addMessage(m) {
    if (m.id && seen.has(m.id)) return;
    if (m.id) { seen.add(m.id); lastId = m.id; }
    const row = document.createElement("div");
    row.className = "chat-msg " + (m.from === "user" ? "me" : "bot");
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (m.from === "user") bubble.textContent = m.text; else renderInto(bubble, m.text);
    row.appendChild(bubble);
    if (m.buttons && m.buttons.length) {
      disableOldButtons(); // only the newest buttons are active (older ones would be "expired" anyway)
      const box = document.createElement("div");
      box.className = "chat-btns";
      m.buttons.forEach((r) => {
        const line = document.createElement("div");
        line.className = "chat-btn-row";
        r.forEach(([label, data]) => {
          const b = document.createElement("button");
          b.type = "button"; b.textContent = label;
          b.addEventListener("click", () => tap(box, b, label, data));
          line.appendChild(b);
        });
        box.appendChild(line);
      });
      row.appendChild(box);
    }
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }
  function addAll(list) { (list || []).forEach(addMessage); }
  function typing(on) {
    let t = log.querySelector(".chat-typing");
    if (on && !t) {
      t = document.createElement("div"); t.className = "chat-msg bot chat-typing";
      t.innerHTML = '<div class="bubble"><span></span><span></span><span></span></div>';
      log.appendChild(t); log.scrollTop = log.scrollHeight;
    } else if (!on && t) t.remove();
  }
  function systemNote(text) {
    const n = document.createElement("div"); n.className = "chat-note"; n.textContent = text;
    log.appendChild(n); log.scrollTop = log.scrollHeight;
  }

  // ---------- server calls
  async function call(path, body, opts = {}) {
    const res = await fetch("/api/chat/" + path, {
      method: "POST",
      headers: opts.headers || { "Content-Type": "application/json" },
      body: opts.raw || JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.");
    return data;
  }
  async function start() {
    if (started) return;
    started = true;
    typing(true);
    try {
      const data = await call("start", { token: loadToken() });
      saveToken(data.token);
      typing(false);
      addAll(data.messages);
    } catch (e) {
      typing(false); started = false; systemNote(e.message);
    }
  }
  async function send(body, optimistic) {
    if (!token) await start();
    if (optimistic) addMessage({ from: "user", text: optimistic });
    busy = true; typing(true);
    try {
      const data = await call("message", { token, ...body });
      typing(false); addAll(data.messages);
    } catch (e) {
      typing(false); systemNote(e.message);
    } finally { busy = false; }
  }
  function tap(box, btn, label, data) {
    if (busy) return;
    box.classList.add("used");
    box.querySelectorAll("button").forEach((b) => (b.disabled = true));
    btn.classList.add("chosen");
    send({ button: data, label }, label);
  }
  async function poll() {
    if (!token || busy || panel.hidden) return;
    try { const data = await call("poll?after=" + encodeURIComponent(lastId || ""), { token }); addAll(data.messages); } catch { /* ignore */ }
  }

  // ---------- open / close
  function open() {
    panel.hidden = false; launcher.classList.add("hidden");
    document.body.classList.add("chat-open");
    start();
    clearInterval(pollTimer); pollTimer = setInterval(poll, 15000);
    setTimeout(() => input.focus(), 50);
  }
  function close() {
    panel.hidden = true; launcher.classList.remove("hidden");
    document.body.classList.remove("chat-open");
    clearInterval(pollTimer);
  }
  document.addEventListener("click", (e) => { if (e.target.closest('[data-chat="open"]')) { e.preventDefault(); open(); } });
  $("#chatClose").addEventListener("click", close);
  $("#chatMenu").addEventListener("click", () => { if (!busy) send({ text: "menu" }, "🏠 Main menu"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) close(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    send({ text }, text);
  });

  // ---------- voice messages (same as Telegram voice notes)
  let rec = null, chunks = [], recStart = 0, recTimer = null;
  const canRecord = !!(navigator.mediaDevices && window.MediaRecorder);
  if (!canRecord) micBtn.hidden = true;
  async function startRec() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) || "";
      rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      chunks = []; recStart = Date.now();
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        micBtn.classList.remove("rec"); status.textContent = "Online · Hindi & English";
        clearTimeout(recTimer);
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        const seconds = Math.round((Date.now() - recStart) / 1000);
        if (seconds < 1 || !blob.size) return;
        if (!token) await start();
        addMessage({ from: "user", text: "🎤 Voice message" });
        busy = true; typing(true);
        try {
          const data = await call("voice?duration=" + seconds, null,
            { raw: blob, headers: { "Content-Type": blob.type || "audio/webm", "X-Chat-Token": token } });
          typing(false); addAll(data.messages);
        } catch (e) { typing(false); systemNote(e.message); } finally { busy = false; }
      };
      rec.start();
      micBtn.classList.add("rec"); status.textContent = "Recording… tap the mic again to send";
      recTimer = setTimeout(() => rec && rec.state === "recording" && rec.stop(), 60000); // max 1 minute
    } catch {
      systemNote("Microphone not available. Please allow microphone access or type your message.");
    }
  }
  micBtn.addEventListener("click", () => {
    if (busy) return;
    if (rec && rec.state === "recording") rec.stop(); else startRec();
  });

  // remember an open conversation: show a small badge on the launcher if there is one
  if (loadToken()) launcher.classList.add("has-chat");
})();
