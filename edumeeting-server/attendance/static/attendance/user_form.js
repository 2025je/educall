(function () {
  var initials = document.querySelector("[data-operator-group]");
  if (!initials) return;
  var groups = initials.form.querySelectorAll('input[name="groups"]');

  function updateInitials() {
    var isOperator = Array.from(groups).some(function (group) {
      return group.value === initials.dataset.operatorGroup && group.checked;
    });
    initials.disabled = !isOperator;
  }

  groups.forEach(function (group) {
    group.addEventListener("change", updateInitials);
  });
  updateInitials();
})();
