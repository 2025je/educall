(() => {
  const csrfToken =
    document.cookie.split("; ").find((item) => item.startsWith("csrftoken="))?.split("=")[1] ||
    document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
  const state = { taskId: null, messageId: null, campaign: [] };
  const toast = document.getElementById("toast");
  const showToast = (message) => {
    toast.textContent = message;
    toast.style.display = "block";
    window.setTimeout(() => { toast.style.display = "none"; }, 4000);
  };
  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
        ...options.headers,
      },
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) throw new Error(payload?.error || `Error HTTP ${response.status}`);
    return payload;
  }

  const nextButton = document.getElementById("next-call");
  nextButton.addEventListener("click", async () => {
    nextButton.disabled = true;
    try {
      const data = await request("/api/v1/calls/next/", { method: "POST", body: "{}" });
      const card = document.getElementById("active-call");
      if (!data.task) {
        state.taskId = null;
        card.hidden = true;
        document.getElementById("call-message").textContent = "No hay llamadas elegibles en este momento.";
        return;
      }
      state.taskId = data.task.id;
      document.querySelectorAll("[data-outcome]").forEach((item) => { item.disabled = false; });
      document.getElementById("participant-name").textContent = data.task.participant.name;
      const origin = data.task.participant.origin_meeting?.name || "Sin reunión de origen";
      document.getElementById("participant-details").textContent =
        `${data.task.participant.phone || "Sin teléfono"} · Llamada para: ${data.task.meeting.name} · Origen: ${origin} · Invitación: ${data.task.participant.invitation_status}`;
      document.getElementById("call-notes").value = "";
      const history = document.getElementById("call-history");
      history.replaceChildren();
      for (const attempt of data.task.history) {
        const entry = document.createElement("li");
        entry.textContent = `${attempt.created_at} · ${attempt.operator} · ${attempt.outcome}${attempt.notes ? ` · ${attempt.notes}` : ""}`;
        history.append(entry);
      }
      document.getElementById("call-message").textContent = "Llamada asignada. Registra el resultado al terminar.";
      card.hidden = false;
    } catch (error) { showToast(error.message); }
    finally { nextButton.disabled = !!state.taskId; }
  });

  document.querySelectorAll("[data-outcome]").forEach((button) => button.addEventListener("click", async () => {
    if (!state.taskId || button.disabled) return;
    const outcomeButtons = [...document.querySelectorAll("[data-outcome]")];
    outcomeButtons.forEach((item) => { item.disabled = true; });
    try {
      const data = await request(`/api/v1/calls/${state.taskId}/result/`, {
        method: "POST",
        body: JSON.stringify({ outcome: button.dataset.outcome, notes: document.getElementById("call-notes").value }),
      });
      showToast(data.code ? `Aceptación registrada. Código: ${data.code}` : "Resultado registrado.");
      state.taskId = null;
      document.getElementById("active-call").hidden = true;
      nextButton.disabled = false;
    } catch (error) {
      showToast(error.message);
      if (error.message.includes("venció")) {
        state.taskId = null;
        document.getElementById("active-call").hidden = true;
        nextButton.disabled = false;
        document.getElementById("call-message").textContent = "La asignación venció; solicita de nuevo la siguiente llamada.";
      }
    } finally { outcomeButtons.forEach((item) => { item.disabled = !state.taskId; }); }
  }));

  document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = document.getElementById("search-query").value.trim();
    const list = document.getElementById("search-results");
    list.replaceChildren();
    try {
      const data = await request(`/api/v1/participants/search/?q=${encodeURIComponent(query)}`);
      for (const person of data.results) {
        const item = document.createElement("li");
        const title = document.createElement("span");
        title.textContent = `${person.name} · ${person.phone || "Sin teléfono"}${person.do_not_contact ? " · NO CONTACTAR" : ""}`;
        const inboundOutcome = document.createElement("select");
        for (const [value, label] of [["contacted", "Contactado"], ["accepted", "Aceptó"], ["declined", "Rechazó"], ["do_not_contact", "No volver a contactar"], ["follow_up", "Seguimiento"], ["other", "Otro"]]) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          inboundOutcome.append(option);
        }
        const inbound = document.createElement("button");
        inbound.textContent = "Contacto entrante";
        inbound.disabled = !person.origin_meeting;
        inbound.addEventListener("click", async () => {
          inbound.disabled = true;
          try {
            const data = await request("/api/v1/calls/inbound/", {
              method: "POST",
              body: JSON.stringify({ participant_id: person.id, outcome: inboundOutcome.value }),
            });
            showToast(data.code ? `Contacto registrado. Código: ${data.code}` : "Contacto entrante registrado.");
          } catch (error) { showToast(error.message); }
          finally { inbound.disabled = false; }
        });
        const select = document.createElement("button");
        select.textContent = "Usar plantilla";
        select.disabled = person.do_not_contact || !person.contact_authorized || !person.phone;
        select.addEventListener("click", () => {
          document.getElementById("message-participant-id").value = person.id;
          document.getElementById("prepare-message").disabled = false;
        });
        const messageTemplate = document.createElement("select");
        messageTemplate.setAttribute("aria-label", `Plantilla para ${person.name}`);
        for (const option of document.getElementById("template-id").options) {
          if (!option.value) continue;
          messageTemplate.add(option.cloneNode(true));
        }
        const addCampaign = document.createElement("button");
        addCampaign.textContent = "Añadir a campaña";
        addCampaign.disabled = person.do_not_contact || !person.contact_authorized || !person.phone || messageTemplate.options.length === 0;
        addCampaign.addEventListener("click", () => {
          if (state.campaign.some((item) => item.participant_id === person.id)) {
            showToast("Ese participante ya está en la campaña.");
            return;
          }
          state.campaign.push({
            participant_id: person.id,
            participant_name: person.name,
            template_id: messageTemplate.value,
            template_name: messageTemplate.selectedOptions[0]?.textContent || "",
          });
          renderCampaignSelection();
        });
        item.append(title, inboundOutcome, inbound, select, messageTemplate, addCampaign);
        list.append(item);
      }
      if (!data.results.length) showToast("No se encontraron participantes.");
    } catch (error) { showToast(error.message); }
  });

  function renderCampaignSelection() {
    const list = document.getElementById("campaign-selection");
    list.replaceChildren();
    for (const [index, recipient] of state.campaign.entries()) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${recipient.participant_name} · ${recipient.template_name}`;
      const remove = document.createElement("button");
      remove.className = "secondary";
      remove.textContent = "Quitar";
      remove.addEventListener("click", () => {
        state.campaign.splice(index, 1);
        renderCampaignSelection();
      });
      item.append(label, remove);
      list.append(item);
    }
    document.getElementById("campaign-count").textContent = `${state.campaign.length} destinatarios`;
    document.getElementById("prepare-campaign").disabled = state.campaign.length === 0;
  }

  document.getElementById("prepare-campaign").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const data = await request("/api/v1/whatsapp/campaigns/prepare/", {
        method: "POST",
        body: JSON.stringify({
          name: document.getElementById("campaign-name").value,
          recipients: state.campaign.map(({ participant_id, template_id }) => ({ participant_id, template_id })),
        }),
      });
      const list = document.getElementById("campaign-message-list");
      list.replaceChildren();
      for (const message of data.messages) {
        const item = document.createElement("li");
        const text = document.createElement("span");
        text.textContent = `${message.participant_name} · ${message.template}: ${message.message}`;
        const open = document.createElement("a");
        open.href = message.whatsapp_url;
        open.target = "_blank";
        open.rel = "noopener noreferrer";
        open.textContent = "Abrir WhatsApp";
        open.addEventListener("click", () => request(`/api/v1/whatsapp/${message.log_id}/status/`, {
          method: "POST", body: JSON.stringify({ status: "link_opened" }),
        }).catch((error) => showToast(error.message)));
        item.append(text, open);
        if (message.qr_url) {
          const qr = document.createElement("a");
          qr.href = message.qr_url;
          qr.download = "";
          qr.textContent = "Descargar QR";
          item.append(qr);
        }
        for (const [status, label] of [["sent", "Confirmar envío"], ["failed", "Fallido"], ["cancelled", "Cancelar"]]) {
          const action = document.createElement("button");
          action.textContent = label;
          action.className = status === "sent" ? "" : "secondary";
          action.addEventListener("click", async () => {
            action.disabled = true;
            try {
              await request(`/api/v1/whatsapp/${message.log_id}/status/`, {
                method: "POST", body: JSON.stringify({ status }),
              });
              action.textContent = "Registrado";
            } catch (error) { showToast(error.message); action.disabled = false; }
          });
          item.append(action);
        }
        list.append(item);
      }
      document.getElementById("campaign-results").hidden = false;
      state.campaign = [];
      renderCampaignSelection();
      showToast(`${data.messages.length} mensajes preparados; WhatsApp aún requiere confirmación manual.`);
    } catch (error) { showToast(error.message); }
    finally { button.disabled = state.campaign.length === 0; }
  });

  document.getElementById("prepare-message").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const data = await request("/api/v1/whatsapp/prepare/", {
        method: "POST",
        body: JSON.stringify({
          participant_id: document.getElementById("message-participant-id").value,
          template_id: document.getElementById("template-id").value,
        }),
      });
      state.messageId = data.log_id;
      document.getElementById("message-content").textContent = data.message;
      const link = document.getElementById("whatsapp-link");
      link.href = data.whatsapp_url;
      link.onclick = () => request(`/api/v1/whatsapp/${state.messageId}/status/`, {
        method: "POST", body: JSON.stringify({ status: "link_opened" }),
      }).catch((error) => showToast(error.message));
      document.getElementById("message-preview").hidden = false;
      const oldQr = document.getElementById("qr-download");
      if (data.qr_url) {
        oldQr.href = data.qr_url;
        oldQr.hidden = false;
      } else {
        oldQr.hidden = true;
      }
    } catch (error) { showToast(error.message); }
    finally { button.disabled = false; }
  });

  document.querySelectorAll("[data-message-status]").forEach((button) => button.addEventListener("click", async () => {
    if (!state.messageId) return;
    try {
      await request(`/api/v1/whatsapp/${state.messageId}/status/`, {
        method: "POST", body: JSON.stringify({ status: button.dataset.messageStatus }),
      });
      showToast("Resultado de comunicación guardado.");
      document.getElementById("message-preview").hidden = true;
      state.messageId = null;
    } catch (error) { showToast(error.message); }
  }));

  try {
    const stream = new EventSource("/api/v1/attendance/stream/");
    stream.addEventListener("calls", () => {
      document.getElementById("call-message").textContent = "La cola tuvo cambios recientes. El servidor confirma cada asignación.";
    });
    stream.addEventListener("attendance", () => showToast("Se actualizaron los registros de asistencia."));
    stream.onerror = () => {
      document.getElementById("call-message").textContent = "Actualización en tiempo real desconectada; las acciones siguen consultando al servidor.";
    };
  } catch { /* The API actions remain available without event streaming. */ }
})();
