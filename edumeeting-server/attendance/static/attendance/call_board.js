(() => {
  const root = document.getElementById("call-board");
  if (!root) return;
  const rows = document.getElementById("call-board-rows");
  const status = document.getElementById("call-board-status");
  const POLL_MS = 15000;
  let board = null;
  let loading = false;
  let pending = false;
  let live = false;

  const cell = (...children) => {
    const td = document.createElement("td");
    children.forEach((child) => td.append(child));
    return td;
  };
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const timeOf = (value) => new Date(value).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  const elapsed = (value) => {
    const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
    const minutes = Math.floor(seconds / 60);
    return minutes ? `${minutes} min ${seconds % 60} s` : `${seconds} s`;
  };

  function render() {
    if (!board) return;
    root.querySelectorAll("[data-queue]").forEach((node) => {
      const key = node.dataset.queue;
      node.textContent = key === "on_call" ? `${board.on_call}/${board.operators.length}` : board.queue[key];
    });
    rows.replaceChildren();
    if (!board.operators.length) {
      const tr = document.createElement("tr");
      const td = cell("No hay operadores asignados a esta reunión. Asígnalos en ");
      const link = element("a", "Asignar usuarios");
      link.href = "#asignaciones";
      td.append(link, ".");
      td.colSpan = 6;
      tr.append(td);
      rows.append(tr);
      return;
    }
    board.operators.forEach((operator) => {
      const chipClass = { on_call: "md-chip md-chip--ok", idle: "md-chip", inactive: "md-chip md-chip--muted" }[operator.state];
      const name = element("strong", operator.username);
      const who = cell(name);
      if (operator.full_name) who.append(element("div", operator.full_name, "md-meta"));
      const current = operator.current_call;
      const call = current
        ? cell(element("strong", current.participant), element("div", `${current.status_label} · hace ${elapsed(current.since)}`, "md-meta"))
        : cell(element("span", "—", "md-meta"));
      const last = operator.last_attempt;
      const result = last
        ? cell(element("span", last.outcome_label), element("div", `${last.participant} · ${timeOf(last.at)}`, "md-meta"))
        : cell(element("span", "Sin intentos", "md-meta"));
      const tr = document.createElement("tr");
      tr.append(
        who,
        cell(element("span", operator.state_label, chipClass)),
        call,
        result,
        cell(`${operator.attempts_last_24h} (total ${operator.call_attempts})`),
        cell(String(operator.accepted)),
      );
      rows.append(tr);
    });
  }

  async function refresh() {
    if (loading) { pending = true; return; }
    loading = true;
    try {
      const response = await fetch(root.dataset.endpoint, { credentials: "same-origin", headers: { Accept: "application/json" } });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.error || `Error HTTP ${response.status}`);
      board = payload;
      render();
      if (!stream) openStream(board.last_event_id);
      const mode = live ? "En vivo" : "Actualización periódica";
      status.textContent = `${mode} · actualizado a las ${new Date().toLocaleTimeString("es")}`;
    } catch (error) {
      status.textContent = `No se pudo actualizar: ${error.message}`;
    } finally {
      loading = false;
      if (pending) { pending = false; refresh(); }
    }
  }

  let stream = null;
  function openStream(lastEventId) {
    stream = new EventSource(`${root.dataset.stream}?last_event_id=${encodeURIComponent(lastEventId || 0)}`);
    stream.onopen = () => { live = true; };
    stream.addEventListener("calls", refresh);
    stream.onerror = () => { live = false; };
    window.addEventListener("pagehide", () => stream.close(), { once: true });
  }

  refresh();
  window.setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
  window.setInterval(() => { if (!document.hidden && board?.on_call) render(); }, 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
})();
