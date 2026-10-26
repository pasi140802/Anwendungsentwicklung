// CourtSlot: kleine Helfer für Tagesauswahl, Bestätigungsdialog und Meldungen.
(function () {
  "use strict";

  // --- Tagesauswahl im Kalender (Tabs ohne Server-Anfrage) -------------------
  function selectDay(tab, focus) {
    var list = tab.closest("[role=tablist]");
    if (!list) return;
    list.querySelectorAll("[role=tab]").forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(t.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    });
    if (focus) tab.focus();
    var url = new URL(window.location.href);
    url.searchParams.delete("start");
    url.searchParams.set("tag", tab.dataset.day);
    history.replaceState(history.state, "", url);
  }

  document.addEventListener("click", function (e) {
    var tab = e.target.closest(".daytab");
    if (tab) selectDay(tab, false);
  });

  document.addEventListener("keydown", function (e) {
    var tab = e.target.closest && e.target.closest(".daytab");
    if (!tab) return;
    var tabs = Array.prototype.slice.call(tab.parentElement.querySelectorAll(".daytab"));
    var i = tabs.indexOf(tab);
    var next = null;
    if (e.key === "ArrowRight") next = tabs[Math.min(i + 1, tabs.length - 1)];
    if (e.key === "ArrowLeft") next = tabs[Math.max(i - 1, 0)];
    if (e.key === "Home") next = tabs[0];
    if (e.key === "End") next = tabs[tabs.length - 1];
    if (next) {
      e.preventDefault();
      selectDay(next, true);
    }
  });

  function revealSelectedTab() {
    var tab = document.querySelector(".daytab[aria-selected=true]");
    if (tab) tab.scrollIntoView({ block: "nearest", inline: "center" });
  }

  // --- Bestätigungsdialog statt Browser-confirm -------------------------------
  function ask(el, onConfirm) {
    var dialog = document.getElementById("confirm");
    if (!dialog || typeof dialog.showModal !== "function") {
      if (window.confirm(el.dataset.confirmTitle || "Fortfahren?")) onConfirm();
      return;
    }
    document.getElementById("confirm-title").textContent = el.dataset.confirmTitle || "Fortfahren?";
    document.getElementById("confirm-text").textContent = el.dataset.confirmText || "";
    var ok = document.getElementById("confirm-ok");
    ok.textContent = el.dataset.confirmOk || "Bestätigen";
    ok.classList.toggle("btn-danger", el.hasAttribute("data-confirm-danger"));
    ok.classList.toggle("btn-primary", !el.hasAttribute("data-confirm-danger"));
    dialog.returnValue = "";
    dialog.onclose = function () {
      if (dialog.returnValue === "ok") onConfirm();
    };
    dialog.showModal();
    ok.focus();
  }

  document.addEventListener("htmx:confirm", function (e) {
    var el = e.detail.elt;
    if (!el.hasAttribute("hx-confirm")) return;
    e.preventDefault();
    ask(el, function () {
      lastSlot = el.closest("[data-slot]") && el.closest("[data-slot]").dataset.slot;
      e.detail.issueRequest(true);
    });
  });

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.hasAttribute("data-confirm-title")) return;
    e.preventDefault();
    ask(form, function () { form.submit(); });
  });

  // Klick neben den Dialog schließt ihn.
  document.addEventListener("click", function (e) {
    if (e.target.id === "confirm") e.target.close("cancel");
  });

  // --- Buchungsdialog: Dauer und Leihartikel wählen ---------------------------
  function updateTotal(form) {
    var total = 0;
    var dur = form.querySelector("input[name=duration]:checked");
    if (dur) total += parseInt(dur.dataset.price || "0", 10);
    form.querySelectorAll("select[data-price]").forEach(function (sel) {
      total += parseInt(sel.dataset.price || "0", 10) * parseInt(sel.value || "0", 10);
    });
    var out = form.querySelector("[data-total]");
    if (out) {
      var euros = (total / 100).toFixed(2).replace(".", ",").replace(",00", "");
      out.textContent = euros + "\u00a0€";
    }
  }

  document.addEventListener("change", function (e) {
    var form = e.target.closest && e.target.closest(".bookform");
    if (form) updateTotal(form);
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "booksheet-body") {
      var sheet = document.getElementById("booksheet");
      var form = sheet.querySelector(".bookform");
      if (form) updateTotal(form);
      if (!sheet.open) sheet.showModal();
      var first = sheet.querySelector("input[name=duration]:checked");
      if (first) first.focus();
    }
  });

  document.addEventListener("htmx:beforeRequest", function (e) {
    var form = e.detail.elt;
    if (form && form.hasAttribute && form.hasAttribute("data-close-sheet")) {
      var slot = form.querySelector("input[name=start]");
      var court = form.querySelector("input[name=court_id]");
      if (slot && court) lastSlot = court.value + "-" + slot.value;
      var sheet = document.getElementById("booksheet");
      if (sheet && sheet.open) sheet.close();
    }
  });

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-close]");
    if (!btn) return;
    var sheet = btn.closest("dialog");
    if (sheet) sheet.close(); else history.back();
  });

  document.addEventListener("click", function (e) {
    if (e.target.id === "booksheet") e.target.close();
  });

  // --- Rückmeldung nach dem Buchen -------------------------------------------
  var lastSlot = null;
  document.addEventListener("htmx:afterSettle", function () {
    revealSelectedTab();
    if (lastSlot) {
      var cell = document.querySelector('[data-slot="' + lastSlot + '"]');
      if (cell) cell.classList.add("just-changed");
      lastSlot = null;
    }
    armToasts();
  });

  // --- Meldungen blenden sich nach einigen Sekunden aus -----------------------
  function armToasts() {
    document.querySelectorAll(".toast:not([data-armed])").forEach(function (t) {
      t.dataset.armed = "1";
      var ms = t.classList.contains("toast-error") ? 7000 : 4500;
      setTimeout(function () {
        t.classList.add("is-leaving");
        setTimeout(function () { t.remove(); }, 300);
      }, ms);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    revealSelectedTab();
    armToasts();
  });

  // Auswahlfelder mit data-autosubmit senden ihr Formular sofort ab (z. B. Rolle).
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("select[data-autosubmit]")) {
      e.target.form.requestSubmit();
    }
  });

  // Benutzermenü schließt bei Klick außerhalb.
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.usermenu[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });
})();
