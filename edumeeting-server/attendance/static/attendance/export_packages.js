(function () {
  var controller = new AbortController();
  window.addEventListener("pagehide", function () { controller.abort(); }, { once: true });

  async function request(url, options) {
    var response = await fetch(url, Object.assign({
      credentials: "same-origin", signal: controller.signal,
      headers: {
        "Accept": "application/json", "Content-Type": "application/json",
        "X-CSRFToken": document.querySelector('[name="csrfmiddlewaretoken"]').value,
      },
    }, options));
    var payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "No se pudo consultar la exportación (HTTP " + response.status + ").");
    return payload;
  }

  document.querySelectorAll("[data-export-url]").forEach(function (button) {
    button.addEventListener("click", async function () {
      var status = button.parentElement.querySelector("[data-export-status]");
      button.disabled = true;
      status.textContent = "Solicitando exportación...";
      try {
        var job = await request(button.dataset.exportUrl, { method: "POST", body: "{}" });
        var attempts = 0;
        while (job.status === "pending" || job.status === "running") {
          status.textContent = "Generando paquete en segundo plano...";
          if (attempts++ >= 450) {
            status.textContent = "La exportación sigue pendiente. Consulta su estado: ";
            var link = document.createElement("a");
            link.href = job.status_url;
            link.textContent = "Ver estado";
            status.append(link);
            return;
          }
          await new Promise(function (resolve) { window.setTimeout(resolve, 2000); });
          job = await request(job.status_url);
        }
        if (job.status !== "succeeded") throw new Error(job.error || "La exportación falló.");
        status.textContent = "";
        var download = document.createElement("a");
        download.href = job.download_url;
        download.textContent = "Descargar paquete (disponible 24 h)";
        status.append(download);
      } catch (error) {
        if (error.name !== "AbortError") status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
})();
