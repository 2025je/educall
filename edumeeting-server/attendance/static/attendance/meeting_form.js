(function () {
  var preview = document.getElementById("code-preview");
  if (!preview) return;
  var number = document.getElementById("id_number");
  var day = document.getElementById("id_starts_date");
  var output = preview.querySelector("[data-code]");
  var parts = preview.querySelector("[data-parts]");

  function render() {
    var n = parseInt(number.value, 10);
    var nn = n >= 1 && n <= 99 ? String(n).padStart(2, "0") : "NN";
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.value || "");
    var date = match ? match[3] + match[2] + match[1].slice(2) : "DDMMAA";
    output.textContent = "JU-" + date + "-" + nn + "-001";
    parts.textContent = "JU = iniciales del operador · " + date + " = fecha (día, mes, año) · " + nn +
      " = número de reunión · 001 = orden del invitado";
  }

  [number, day].forEach(function (field) {
    if (field) { field.addEventListener("input", render); field.addEventListener("change", render); }
  });
  render();
})();
