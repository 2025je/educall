(function () {
  function isTextField(field) {
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)) return false;
    if (field.disabled || field.readOnly || field.dataset.preserveCase !== undefined) return false;
    if (field instanceof HTMLInputElement && !["text", "search", "tel"].includes(field.type)) return false;
    if (field.dataset.uppercase !== undefined) return true;
    var identity = [field.name, field.id, field.autocomplete].join(" ");
    return !/(username|email|password)/i.test(identity);
  }

  function uppercase(value) {
    return value.split(/({{[\s\S]*?}})/g).map(function (part) {
      return part.startsWith("{{") ? part : part.toUpperCase();
    }).join("");
  }

  function normalize(field) {
    if (!isTextField(field)) return;
    var value = field.value;
    var next = uppercase(value);
    if (value === next) return;
    var start = field.selectionStart;
    var end = field.selectionEnd;
    var direction = field.selectionDirection;
    field.value = next;
    if (start !== null && end !== null) {
      field.setSelectionRange(uppercase(value.slice(0, start)).length, uppercase(value.slice(0, end)).length, direction);
    }
  }

  function normalizeAll(root) {
    root.querySelectorAll("input, textarea").forEach(normalize);
  }

  document.addEventListener("input", function (event) {
    if (!event.isComposing) normalize(event.target);
  }, true);
  ["change", "compositionend"].forEach(function (type) {
    document.addEventListener(type, function (event) { normalize(event.target); }, true);
  });
  document.addEventListener("submit", function (event) { normalizeAll(event.target); }, true);
  document.addEventListener("click", function (event) {
    if (event.target.closest("button, input[type=submit]")) normalizeAll(document);
  }, true);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { normalizeAll(document); });
  } else {
    normalizeAll(document);
  }
})();
