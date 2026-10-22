(function() {
  document.addEventListener("DOMContentLoaded", function() {
    const form = document.getElementById("changelist-form");
    if (!form) return;

    const totalFormsInput = form.querySelector('input[name="form-TOTAL_FORMS"]');
    if (!totalFormsInput) return;

    const saveButtons = form.querySelectorAll('input[type="submit"][name="_save"]');
    saveButtons.forEach(function(btn) {
      btn.style.display = "none";
    });

    let indicator = document.querySelector(".admin-ajax-indicator");
    if (!indicator) {
      indicator = document.createElement("div");
      indicator.className = "admin-ajax-indicator";
      document.body.appendChild(indicator);
    }

    let hideTimer = null;
    function showStatus(text, type, duration) {
      if (hideTimer) clearTimeout(hideTimer);
      indicator.textContent = text;
      indicator.className = "admin-ajax-indicator visible " + type;
      if (duration) {
        hideTimer = setTimeout(function() {
          indicator.className = "admin-ajax-indicator " + type;
        }, duration);
      }
    }

    const ajaxQueue = [];
    let isSending = false;

    function processQueue() {
      if (isSending || ajaxQueue.length === 0) return;
      const task = ajaxQueue.shift();
      isSending = true;
      showStatus("Сохранение...", "loading");

      const formData = new FormData(form);
      formData.set("_save", "Save");

      fetch(form.action || window.location.href, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest"
        },
        body: formData
      })
      .then(function(res) {
        if (!res.ok) {
          throw new Error("Ошибка HTTP " + res.status);
        }
        const contentType = res.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          return res.json();
        }
        return res.text().then(function(html) {
          if (html.includes("errornote") || html.includes("errorlist")) {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, "text/html");
            const errElem = doc.querySelector(".errornote, .errorlist");
            const errMsg = errElem ? errElem.textContent.trim() : "Ошибка валидации";
            throw new Error(errMsg);
          }
          return { status: "ok" };
        });
      })
      .then(function(data) {
        showStatus("✓ Сохранено", "success", 2000);
        if (task.row) {
          task.row.classList.remove("ajax-saved");
          void task.row.offsetWidth;
          task.row.classList.add("ajax-saved");
        }
        if (task.onSuccess) task.onSuccess(data);
      })
      .catch(function(err) {
        console.error("Admin auto-save error:", err);
        showStatus(err.message || "Ошибка сохранения", "error", 4000);
        if (task.onError) task.onError(err);
      })
      .finally(function() {
        isSending = false;
        processQueue();
      });
    }

    function queueSave(targetInput) {
      const row = targetInput.closest("tr");
      const isCheckbox = targetInput.type === "checkbox";
      const previousState = isCheckbox ? !targetInput.checked : targetInput.defaultValue;

      ajaxQueue.push({
        target: targetInput,
        row: row,
        onSuccess: function() {
          if (!isCheckbox) {
            targetInput.defaultValue = targetInput.value;
          }
        },
        onError: function() {
          if (isCheckbox) {
            targetInput.checked = previousState;
          } else {
            targetInput.value = previousState;
          }
        }
      });

      processQueue();
    }

    const resultList = document.getElementById("result_list");
    if (!resultList) return;

    resultList.addEventListener("change", function(evt) {
      const target = evt.target;
      if (
        target.classList.contains("action-select") ||
        target.id === "action-toggle" ||
        target.name === "_selected_action"
      ) {
        return;
      }
      if (target.name && target.name.startsWith("form-")) {
        queueSave(target);
      }
    });
  });
})();
