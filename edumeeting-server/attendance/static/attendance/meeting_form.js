(function () {
  document.querySelectorAll("[data-schedules]").forEach(function (fieldset) {
    var prefix = fieldset.getAttribute("data-prefix");
    var total = fieldset.querySelector("#id_" + prefix + "-TOTAL_FORMS");
    var rows = fieldset.querySelector("[data-schedule-rows]");
    var template = fieldset.querySelector("[data-schedule-template]");
    var add = fieldset.querySelector("[data-add-schedule]");
    if (!total || !rows || !template || !add) return;

    add.addEventListener("click", function () {
      var index = parseInt(total.value, 10);
      var html = template.innerHTML.replace(/__prefix__/g, String(index));
      rows.insertAdjacentHTML("beforeend", html);
      total.value = String(index + 1);
      var inserted = rows.lastElementChild;
      var first = inserted && inserted.querySelector("input[type=date]");
      if (first) first.focus();
    });

    // Las filas nuevas se quitan sin más (el formset las trata como vacías); las guardadas usan «Eliminar».
    rows.addEventListener("click", function (event) {
      var button = event.target.closest("[data-remove-schedule]");
      if (button) button.closest("[data-schedule-row]").remove();
    });
  });
})();
