/* TrashTwitter – das bisschen JavaScript, das es braucht.
   Alles Wesentliche funktioniert auch ohne JS; das hier macht es angenehmer. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const body = document.body;
  const root = () => body.dataset.root || "";

  function csrf() {
    try { return JSON.parse(body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || ""; }
    catch (e) { return ""; }
  }

  // --- Toasts --------------------------------------------------------------
  function toast(message, kind = "ok") {
    const box = $("#toasts");
    if (!box || !message) return;
    const el = document.createElement("div");
    el.className = "toast " + (kind === "error" ? "error" : "");
    el.textContent = message;
    box.appendChild(el);
    autoclose(el);
  }
  function autoclose(el, ms = el.hasAttribute("data-undo-toast") ? 8000 : 2600) {
    let left = ms, started = Date.now(), timer = 0;
    const go = () => { el.classList.add("leaving"); setTimeout(() => el.remove(), 320); };
    const run = () => { started = Date.now(); timer = setTimeout(go, left); };
    // Mit Rueckgaengig-Knopf: beim Drueberfahren anhalten
    if (el.hasAttribute("data-undo-toast")) {
      el.addEventListener("mouseenter", () => { clearTimeout(timer); left -= Date.now() - started; });
      el.addEventListener("mouseleave", run);
    }
    run();
  }

  // --- Rueckgaengig statt Rueckfrage (0.23) ----------------------------------------------------
  // Loeschen passiert erst nach 8 Sekunden; bis dahin bringt "Rueckgaengig" alles zurueck.
  // Verlaesst man die Seite vorher, wird sofort (keepalive) abgeschickt.
  const csrfToken = () => { try { return JSON.parse(body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || ""; } catch (e) { return ""; } };
  const pending = new Set();
  function deferAction(message, commit, undo, ms = 8000) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast has-undo";
    el.setAttribute("data-undo-toast", "");
    const span = document.createElement("span"); span.textContent = message;
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "toast-undo"; btn.textContent = "Rückgängig";
    el.append(span, btn);
    const job = { done: false, run() { if (this.done) return; this.done = true; pending.delete(this); commit(); } };
    pending.add(job);
    btn.addEventListener("click", () => { job.done = true; pending.delete(job); undo(); el.remove(); toast("Zurückgenommen"); });
    box?.appendChild(el);
    let left = ms, started = Date.now(), timer = 0;
    const fire = () => { job.run(); el.classList.add("leaving"); setTimeout(() => el.remove(), 320); };
    const run = () => { started = Date.now(); timer = setTimeout(fire, left); };
    el.addEventListener("mouseenter", () => { clearTimeout(timer); left -= Date.now() - started; });
    el.addEventListener("mouseleave", run);
    run();
  }
  window.addEventListener("pagehide", () => pending.forEach((job) => job.run()));
  function postForm(url, fields) {
    const fd = new FormData();
    fd.append("csrf_token", csrfToken());
    Object.entries(fields).forEach(([k, v]) => (Array.isArray(v) ? v : [v]).forEach((x) => fd.append(k, x)));
    return fetch(url, { method: "POST", body: fd, credentials: "same-origin", keepalive: true, redirect: "manual",
                        headers: { "X-CSRF-Token": csrfToken() } });
  }
  function hideCards(ids) {
    ids.forEach((id) => { const c = $(`[data-post="${CSS.escape(String(id))}"]`); if (c) c.hidden = true; });
    if (typeof initMasonry === "function") initMasonry();
  }
  function showCards(ids) {
    ids.forEach((id) => { const c = $(`[data-post="${CSS.escape(String(id))}"]`); if (c) c.hidden = false; });
    if (typeof initMasonry === "function") initMasonry();
  }
  document.addEventListener("click", (ev) => {
    const one = ev.target.closest?.("[data-defer-delete]");
    if (!one) return;
    ev.preventDefault();
    ev.stopPropagation();
    const id = one.dataset.postId;
    hideCards([id]);
    deferAction(`${one.dataset.label || "Posting"} gelöscht`, () => postForm(one.dataset.deferDelete, {}), () => showCards([id]));
  }, true);
  // Toast aus dem Server-Header HX-Trigger: {"toast": {"message": "...", "kind": "ok"}}
  body.addEventListener("toast", (ev) => toast(ev.detail.message, ev.detail.kind));

  // --- Dialoge / Sheets ----------------------------------------------------
  function openDialog(id) {
    const dlg = document.getElementById(id);
    if (!dlg || dlg.open) return;
    $$("details.menu[open]").forEach((d) => d.removeAttribute("open"));
    dlg.showModal();
    const input = $("[data-url-input], [data-pal-input]", dlg);
    if (input) setTimeout(() => input.focus(), 60);
    if (id === "palette" && window.htmx) { const q = $("[data-pal-input]", dlg); q.value = ""; window.htmx.trigger(q, "pal-open"); }
  }
  document.addEventListener("click", (ev) => {
    const opener = ev.target.closest("[data-open]");
    if (opener) {
      ev.preventDefault();
      if (opener.hasAttribute("data-pal-close")) opener.closest("dialog")?.close();
      openDialog(opener.dataset.open);
      return;
    }
    const closer = ev.target.closest("[data-close]");
    if (closer) { closer.closest("dialog")?.close(); return; }
    // Klick auf den abgedunkelten Hintergrund schliesst das Sheet
    if (ev.target.tagName === "DIALOG") ev.target.close();
    // Offene Menues schliessen, wenn daneben geklickt wird
    $$("details.menu[open], details[data-nav-more][open], details[data-act-more][open]").forEach((d) => { if (!d.contains(ev.target)) d.removeAttribute("open"); });
    // Detailseite (0.23): Eintraege im "Mehr"-Menue
    const fold = ev.target.closest("[data-open-fold]");
    if (fold) {
      const target = document.getElementById(fold.dataset.openFold);
      const det = target?.closest("details");
      if (det) det.open = true;
      ev.target.closest("details[data-act-more]")?.removeAttribute("open");
    }
    if (ev.target.closest("[data-focus-comment]")) {
      setTimeout(() => $("#kommentare textarea")?.focus({ preventScroll: true }), 50);
    }
    if (ev.target.closest(".act-more-panel [data-edit], .act-more-panel [data-copy-text]")) {
      ev.target.closest("details[data-act-more]")?.removeAttribute("open");
    }
  });

  // --- Einfuegen aus der Zwischenablage (nur in sicherem Kontext moeglich) --
  if (window.isSecureContext && navigator.clipboard && navigator.clipboard.readText) {
    $$("[data-paste]").forEach((btn) => { btn.hidden = false; });
  }
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-paste]");
    if (!btn) return;
    try {
      const text = (await navigator.clipboard.readText()).trim();
      const input = $("[data-url-input]", btn.closest("form"));
      if (input && text) {
        input.value = text;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
      }
    } catch (e) { toast("Kein Zugriff auf die Zwischenablage – bitte selbst einfügen.", "error"); }
  });
  // Eingefuegte Links von Leerzeichen und "Schau mal: " befreien
  document.addEventListener("paste", (ev) => {
    const input = ev.target.closest && ev.target.closest("[data-url-input]");
    if (!input) return;
    const text = (ev.clipboardData || window.clipboardData).getData("text");
    const m = text && text.match(/https?:\/\/\S+/);
    if (m) { ev.preventDefault(); input.value = m[0]; input.dispatchEvent(new Event("input", { bubbles: true })); }
  });

  // --- Kopieren --------------------------------------------------------------
  async function copyText(text, btn) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      // Rueckfall fuer http:// im LAN (dort gibt es die Clipboard-API nicht)
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    toast("Kopiert");
    if (btn) { btn.classList.add("just"); setTimeout(() => btn.classList.remove("just"), 500); }
  }
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-copy]");
    if (a) {
      ev.preventDefault();
      const el = $(a.dataset.copy);
      if (el) copyText("value" in el ? el.value : el.textContent, a);
      return;
    }
    const b = ev.target.closest("[data-copy-text]");
    if (b) { ev.preventDefault(); copyText(b.dataset.copyText, b); }
  });

  // --- Screenshot teilen (iOS/Android: als Bild ins Teilen-Menue) ----------------
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-share-image]");
    if (!btn) return;
    ev.preventDefault();
    try {
      const blob = await (await fetch(btn.dataset.shareImage, { credentials: "same-origin" })).blob();
      const file = new File([blob], btn.dataset.shareName || "beleg.jpg", { type: blob.type || "image/jpeg" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: "Beleg", text: btn.dataset.shareUrl || "" });
        return;
      }
      if (navigator.share) { await navigator.share({ url: btn.dataset.shareUrl }); return; }
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = file.name; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
      if (e && e.name !== "AbortError") toast("Teilen hat nicht geklappt.", "error");
    }
  });

  // --- Lightbox fuer Screenshots ------------------------------------------------
  document.addEventListener("click", (ev) => {
    const img = ev.target.closest("[data-lightbox]");
    if (img) {
      const box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML = '<img alt="">';
      box.firstChild.src = img.src;
      box.addEventListener("click", () => box.remove());
      document.body.appendChild(box);
      return;
    }
  });

  // --- Bearbeiten-Umschalter (Text, Notiz) ----------------------------------------
  function setEdit(key, on) {
    const view = $(`[data-edit-view="${key}"]`);
    const form = $(`[data-edit-form="${key}"]`);
    if (!view || !form) return;
    view.hidden = on; form.hidden = !on;
    if (on) {
      const f = $("textarea, input:not([type=hidden])", form);
      if (f) { f.focus(); if (form.classList.contains("tag-rename")) f.select(); else f.setSelectionRange?.(f.value.length, f.value.length); }
    }
  }
  document.addEventListener("click", (ev) => {
    const e = ev.target.closest("[data-edit]");
    if (e) { setEdit(e.dataset.edit, true); return; }
    const c = ev.target.closest("[data-edit-cancel]");
    if (c) setEdit(c.dataset.editCancel, false);
  });

  // --- Filter-Bereich auf/zu ---------------------------------------------------------
  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-toggle]");
    if (!t) return;
    const panel = document.getElementById(t.dataset.toggle);
    if (!panel) return;
    panel.hidden = !panel.hidden;
    // Gruppe (z. B. Tags/Filter im Idiotarium): immer nur ein Fenster offen
    if (!panel.hidden && t.dataset.toggleGroup) {
      $$(`[data-toggle-group="${t.dataset.toggleGroup}"]`).forEach((other) => {
        if (other.dataset.toggle === t.dataset.toggle) return;
        const p = document.getElementById(other.dataset.toggle);
        if (p) p.hidden = true;
        other.setAttribute("aria-expanded", "false");
      });
    }
    if (!panel.hidden) $("[data-tb-search]", panel)?.focus({ preventScroll: true });
    document.querySelectorAll(`[data-toggle="${t.dataset.toggle}"][aria-expanded]`)
      .forEach((b) => b.setAttribute("aria-expanded", String(!panel.hidden)));
  });

  // --- Tag-Auswahl (0.14): Chips + Suche in vorhandenen Tags ---------------------------
  const pickerTags = (picker) => ($("[data-tag-value]", picker).value || "").split(",").map((t) => t.trim()).filter(Boolean);
  function setPickerTags(picker, tags) {
    const field = $("[data-tag-value]", picker);
    field.value = tags.join(", ");
    const chips = $("[data-tag-chips]", picker);
    chips.replaceChildren(...tags.map((t) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "tp-chip"; b.dataset.tagRemove = t; b.title = `#${t} entfernen`;
      b.textContent = "#" + t;
      const x = document.createElement("span"); x.setAttribute("aria-hidden", "true"); x.textContent = "×";
      b.appendChild(x);
      return b;
    }));
    const q = $("[data-tag-query]", picker);
    q.placeholder = tags.length ? "Weiteren Tag suchen …" : "Tag suchen …";
    syncQuick(picker);
    field.dispatchEvent(new Event("change", { bubbles: true }));
  }
  // Schnellauswahl (0.22): Chips zeigen, was schon gewaehlt ist
  function syncQuick(picker) {
    const tags = pickerTags(picker);
    $$("[data-tag-add][data-quick]", picker).forEach((b) => b.setAttribute("aria-pressed", String(tags.includes(b.dataset.tagAdd))));
  }
  document.addEventListener("htmx:load", (ev) => {
    const quick = ev.detail.elt.closest?.("[data-tag-picker]");
    if (quick && ev.detail.elt.matches?.("[data-tag-quick]")) syncQuick(quick);
  });
  function refreshSuggestions(picker) {
    const q = $("[data-tag-query]", picker);
    if (window.htmx) window.htmx.trigger(q, "focus");
  }
  document.addEventListener("click", (ev) => {
    const add = ev.target.closest("[data-tag-add]");
    if (add) {
      const picker = add.closest("[data-tag-picker]");
      if (!picker) return;
      const tags = pickerTags(picker);
      if (add.hasAttribute("data-quick")) {
        // Antippen schaltet um - ohne Tastatur aufzuklappen (Handy)
        setPickerTags(picker, tags.includes(add.dataset.tagAdd) ? tags.filter((t) => t !== add.dataset.tagAdd) : [...tags, add.dataset.tagAdd]);
        return;
      }
      if (!tags.includes(add.dataset.tagAdd)) tags.push(add.dataset.tagAdd);
      setPickerTags(picker, tags);
      const q = $("[data-tag-query]", picker);
      q.value = "";
      q.focus();
      refreshSuggestions(picker);
      return;
    }
    const rm = ev.target.closest("[data-tag-remove]");
    if (rm) {
      const picker = rm.closest("[data-tag-picker]");
      setPickerTags(picker, pickerTags(picker).filter((t) => t !== rm.dataset.tagRemove));
      return;
    }
    // Klick daneben: Vorschlaege zu
    $$("[data-tag-picker]").forEach((p) => { if (!p.contains(ev.target)) $("[data-tag-results]", p).replaceChildren(); });
    const box = ev.target.closest("[data-tag-box]");
    if (box) $("[data-tag-query]", box).focus();
  });
  document.addEventListener("keydown", (ev) => {
    const q = ev.target.closest && ev.target.closest("[data-tag-query]");
    if (!q) return;
    const picker = q.closest("[data-tag-picker]");
    if (ev.key === "Backspace" && !q.value) {
      const tags = pickerTags(picker);
      if (tags.length) { tags.pop(); setPickerTags(picker, tags); }
      return;
    }
    if (ev.key === "Escape") { $("[data-tag-results]", picker).replaceChildren(); return; }
    if (ev.key !== "Enter" && ev.key !== ",") return;
    ev.preventDefault();  // Enter soll nie das ganze Formular abschicken
    const typed = q.value.trim().toLowerCase().replace(/^#/, "");
    if (!typed) return;
    // Nur ein vorhandener Tag, der mit dem Eingetippten beginnt, wird per Enter uebernommen.
    // Neue Tags gibt es nur per Klick auf "+ Neuen Tag anlegen".
    const first = $$("[data-tag-results] [data-tag-add]:not([data-tag-new]):not([data-similar])", picker)
      .find((b) => b.dataset.tagAdd.startsWith(typed));
    if (first) first.click();
    else $("[data-tag-new]", picker)?.classList.add("is-nudged");
  });

  // Archiv: Tag-Leiste filtert sofort (mehrere = alle muessen passen)
  document.addEventListener("click", (ev) => {
    const more = ev.target.closest("[data-tag-more]");
    if (more) { more.closest("[data-tag-bar]").classList.add("is-open"); more.remove(); return; }
    const pill = ev.target.closest("[data-tag-toggle]");
    if (!pill) return;
    const form = pill.closest("form");
    const field = $("[data-tag-filter]", form);
    const name = pill.dataset.tagToggle;
    const on = pill.getAttribute("aria-pressed") !== "true";
    // Derselbe Tag kann in Leiste und "Alle Tags" stehen - beide gleich schalten
    $$(`[data-tag-toggle="${CSS.escape(name)}"]`, form).forEach((b) => b.setAttribute("aria-pressed", String(on)));
    const active = new Set($$("[data-tag-toggle][aria-pressed=true]", form).map((b) => b.dataset.tagToggle));
    field.value = [...active].join(",");
    field.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // --- Rueckfrage im eigenen Fenster (statt window.confirm) -----------------------------
  // <form data-confirm="...">, <button data-confirm="..."> (z. B. formaction) und htmx hx-confirm.
  function askConfirm(message, okLabel) {
    const dlg = document.getElementById("confirm-dialog");
    if (!dlg) return Promise.resolve(window.confirm(message));
    $("[data-confirm-text]", dlg).textContent = message;
    $("[data-confirm-ok]", dlg).textContent = okLabel || "Löschen";
    dlg.returnValue = "";
    dlg.showModal();
    setTimeout(() => $("[data-confirm-cancel]", dlg).focus(), 30);
    return new Promise((resolve) => {
      dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true });
    });
  }
  document.addEventListener("click", (ev) => {
    const dlg = ev.target.closest("#confirm-dialog");
    if (!dlg) return;
    if (ev.target.closest("[data-confirm-ok]")) dlg.close("ok");
    else if (ev.target.closest("[data-confirm-cancel]")) dlg.close("");
  });
  document.addEventListener("submit", (ev) => {
    const form = ev.target;
    const source = (ev.submitter && ev.submitter.dataset.confirm) ? ev.submitter : form;
    const message = source.dataset && source.dataset.confirm;
    if (!message) return;
    if (form.dataset.confirmed === "1") { delete form.dataset.confirmed; return; }
    ev.preventDefault();
    ev.stopImmediatePropagation();
    const submitter = ev.submitter;
    askConfirm(message, source.dataset.confirmOk).then((ok) => {
      if (!ok) return;
      form.dataset.confirmed = "1";
      form.requestSubmit(submitter || undefined);
    });
  }, true);
  document.addEventListener("htmx:confirm", (ev) => {
    if (!ev.detail.question) return;
    ev.preventDefault();
    askConfirm(ev.detail.question, ev.detail.elt.dataset.confirmOk).then((ok) => { if (ok) ev.detail.issueRequest(true); });
  });

  // --- Einstellungen sofort sichtbar machen (Design, Akzent, Dichte, Bewegung) ---------
  document.addEventListener("change", (ev) => {
    const input = ev.target.closest("[data-live]");
    if (input && input.checked) document.documentElement.dataset[input.dataset.live] = input.value;
  });

  // --- Suchgenerator: Felder je Plattform ein-/ausblenden -------------------------------
  function applyPlatform(platform) {
    $$("#gen-form [data-platforms], .gen-bottom [data-platforms]").forEach((el) => {
      // Werte bleiben im DOM erhalten - nur sichtbar/unsichtbar.
      el.hidden = !el.dataset.platforms.trim().split(/\s+/).includes(platform);
    });
  }
  document.addEventListener("change", (ev) => {
    if (!ev.target.matches("[data-platform-switch]")) return;
    applyPlatform(ev.target.value);
    const url = new URL(window.location.href);
    url.searchParams.set("platform", ev.target.value);
    url.searchParams.delete("preset");
    url.searchParams.delete("saved");
    history.replaceState(null, "", url);
  });

  // --- Listen-Auswahl (Fenster) ---------------------------------------------------------
  // Suchen = filtern; gibt es den Namen noch nicht, erscheint "als neue Liste anlegen".
  document.addEventListener("input", (ev) => {
    const input = ev.target.closest("[data-list-filter]");
    if (!input) return;
    const box = input.closest("[data-list-picker]");
    const q = input.value.trim().toLowerCase();
    let exact = false;
    $$("[data-list-title]", box).forEach((li) => {
      const t = li.dataset.listTitle;
      li.hidden = q !== "" && !t.includes(q);
      if (t === q) exact = true;
    });
    const create = $("[data-list-new]", box);
    create.hidden = q === "" || exact;
    $("[data-list-new-label]", box).textContent = input.value.trim();
    $("[data-list-new-title]", box).value = input.value.trim();
  });
  document.addEventListener("keydown", (ev) => {
    const input = ev.target.closest && ev.target.closest("[data-list-filter]");
    if (!input || ev.key !== "Enter") return;
    ev.preventDefault();
    const box = input.closest("[data-list-picker]");
    const visible = $$("[data-list-title]", box).filter((li) => !li.hidden);
    const create = $("[data-list-new]", box);
    if (!create.hidden) $("button", create).click();
    else if (visible.length === 1) $("button", visible[0]).click();
  });
  // Mehrfachauswahl: Liste antippen = alle markierten Postings dort ablegen
  document.addEventListener("click", (ev) => {
    const pick = ev.target.closest("[data-bulk-target], [data-bulk-new-list]");
    if (!pick) return;
    ev.preventDefault();
    const form = bulkBar();
    if (!form) return;
    $("[data-bulk-list-id]", form).value = pick.dataset.bulkTarget || "0";
    $("[data-bulk-new-name]", form).value = pick.dataset.bulkTarget ? "" : $("[data-list-new-title]", pick.closest("[data-list-picker]")).value;
    pick.closest("dialog")?.close();
    form.requestSubmit();
  });

  if (!/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) $$("[data-kbd-mod]").forEach((k) => { k.textContent = "Strg K"; });

  // --- Detailseite am Handy (0.23): wischen = naechstes / vorheriges Posting -----------------------
  (() => {
    const layout = $(".detail-layout");
    if (!layout) return;
    let x0 = 0, y0 = 0, t0 = 0, ok = false;
    layout.addEventListener("touchstart", (ev) => {
      const t = ev.target;
      ok = ev.touches.length === 1 && !t.closest("input, textarea, select, video, .media-grid, [contenteditable], dialog, .chips, .lead-actions");
      x0 = ev.touches[0].clientX; y0 = ev.touches[0].clientY; t0 = Date.now();
    }, { passive: true });
    layout.addEventListener("touchend", (ev) => {
      if (!ok) return;
      const dx = ev.changedTouches[0].clientX - x0, dy = ev.changedTouches[0].clientY - y0;
      if (Math.abs(dx) < 80 || Math.abs(dy) > 50 || Date.now() - t0 > 600) return;
      const link = $(`[data-nav="${dx < 0 ? "older" : "newer"}"][href]`);
      if (!link) return;
      layout.classList.add(dx < 0 ? "swipe-left" : "swipe-right");
      location.href = link.href;
    }, { passive: true });
  })();

  // --- Suche ueberall (0.23): Cmd/Strg+K, Pfeiltasten, Enter -------------------------------
  window.addEventListener("keydown", (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && ev.key.toLowerCase() === "k") {
      if (!document.getElementById("palette")) return;
      ev.preventDefault();
      $$("dialog[open]").forEach((d) => { if (d.id !== "palette") d.close(); });
      openDialog("palette");
      return;
    }
    if (ev.key === "Escape") $$("details[data-nav-more][open]").forEach((d) => d.removeAttribute("open"));
    const pal = ev.target.closest?.("#palette");
    if (!pal || !["ArrowDown", "ArrowUp", "Enter"].includes(ev.key)) return;
    const items = $$("[data-pal-item]", pal);
    if (!items.length) return;
    let i = items.findIndex((x) => x.classList.contains("is-active"));
    if (ev.key === "Enter") {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      const item = items[i] || items[0];
      if (item.href) location.href = item.href; else item.click();
      return;
    }
    ev.preventDefault();
    i = ev.key === "ArrowDown" ? Math.min(items.length - 1, i + 1) : Math.max(0, i - 1);
    items.forEach((x, k) => x.classList.toggle("is-active", k === i));
    items[i].scrollIntoView({ block: "nearest" });
  }, true);
  document.addEventListener("htmx:afterSwap", (ev) => {
    if (ev.detail.target.id !== "pal-results") return;
    $("[data-pal-item]", ev.detail.target)?.classList.add("is-active");
  });

  // --- Tastenkuerzel -----------------------------------------------------------------------
  let lastKey = "", lastKeyAt = 0;
  document.addEventListener("keydown", (ev) => {
    if (body.dataset.shortcuts !== "on" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const t = ev.target;
    if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    if ($("dialog[open]")) return;
    const k = ev.key;
    const now = Date.now();
    const combo = now - lastKeyAt < 800 ? lastKey + k : k;
    lastKey = k; lastKeyAt = now;

    if (k === "n") { ev.preventDefault(); openDialog(document.getElementById("gallery-upload") ? "gallery-upload" : "add-dialog"); }
    else if (k === "/") {
      ev.preventDefault();
      const s = $("[data-search]");
      if (s) s.focus(); else window.location.href = root() + "/";
    }
    else if (k === "?") { openDialog("keys-dialog"); }
    else if (combo === "ga") { window.location.href = root() + "/"; }
    else if (k === "ArrowLeft" || k === "ArrowRight") {
      const a = $(`[data-nav="${k === "ArrowLeft" ? "newer" : "older"}"][href]`);
      if (a) window.location.href = a.href;
    }
  });

  // --- Profilbild: Vorschau sofort nach der Auswahl ------------------------------------------
  document.addEventListener("change", (ev) => {
    const input = ev.target.closest("[data-avatar-input]");
    if (!input || !input.files || !input.files[0]) return;
    const box = $("[data-avatar-preview]", input.closest("form"));
    if (!box) return;
    const img = document.createElement("img");
    img.className = "avatar avatar-img";
    img.style.setProperty("--s", "88px");
    img.alt = "";
    img.src = URL.createObjectURL(input.files[0]);
    box.replaceChildren(img);
  });

  // --- Mehrfachauswahl im Archiv ----------------------------------------------------------------
  // Die Auswahl lebt in einem Set, damit sie Filterwechsel und "Mehr laden" (htmx) uebersteht.
  const selected = new Set();
  const bulkBar = () => $("[data-bulk-bar]");
  const selecting = () => body.classList.contains("selecting");

  function syncSelection(scope = document) {
    $$("[data-select-toggle]").forEach((b) => b.setAttribute("aria-pressed", String(selecting())));
    $$("[data-select-item]", scope).forEach((cb) => {
      cb.checked = selected.has(cb.value);
      cb.closest("[data-post]")?.classList.toggle("is-selected", cb.checked);
    });
    const bar = bulkBar();
    if (!bar) return;
    $$("[data-select-count]").forEach((el) => { el.textContent = selected.size; });
    // "Alle N Treffer": nur, wenn mehr Treffer existieren als geladen sind
    const res = $("#results"), allBtn = $("[data-select-results]", bar);
    if (res && allBtn) {
      const total = Number(res.dataset.total || 0), loaded = $$("[data-select-item]").length;
      allBtn.hidden = !(total > loaded && selected.size < total);
      $("[data-results-total]", allBtn).textContent = Math.min(total, 500);
    }
    $("[data-bulk-submit]", bar).disabled = selected.size === 0;
    const tagBtn = $("[data-bulk-tags]", bar);
    if (tagBtn) tagBtn.disabled = selected.size === 0;
    const colBtn = $("[data-bulk-collage]", bar);
    if (colBtn) colBtn.disabled = selected.size === 0;
    const del = $("[data-bulk-delete]", bar);
    if (del) del.disabled = selected.size === 0;
    // Die Formular-Felder "ids" kommen aus den Karten (form="bulk-form"). Nicht mehr sichtbare
    // Auswahl (nach Filterwechsel) geht als versteckte Felder mit.
    $$("input[data-hidden-id]", bar).forEach((i) => i.remove());
    const visible = new Set($$("[data-select-item]").map((cb) => cb.value));
    selected.forEach((id) => {
      if (visible.has(id)) return;
      const h = document.createElement("input");
      h.type = "hidden"; h.name = "ids"; h.value = id; h.dataset.hiddenId = "1";
      bar.appendChild(h);
    });
  }

  // Tags fuer die Auswahl (0.21): beim Absenden die markierten IDs anhaengen
  document.addEventListener("submit", (ev) => {
    const form = ev.target.closest?.("[data-bulk-tags-form]");
    if (!form) return;
    $$("input[name=ids]", form).forEach((i) => i.remove());
    selected.forEach((id) => {
      const h = document.createElement("input");
      h.type = "hidden"; h.name = "ids"; h.value = id;
      form.appendChild(h);
    });
    $("[data-bulk-back]", form).value = location.pathname.replace(root(), "") + location.search;
  }, true);

  // Loeschen aus der Auswahl (0.23): ohne Rueckfrage, mit Rueckgaengig
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest?.("[data-bulk-delete]");
    if (!btn || !selected.size) return;
    ev.preventDefault();
    const ids = [...selected];
    const back = location.pathname.replace(root(), "") + location.search;
    hideCards(ids);
    setSelecting(false);
    deferAction(`${ids.length} ${ids.length === 1 ? "Posting" : "Postings"} gelöscht`,
      () => postForm(btn.dataset.deleteUrl, { ids, back }), () => showCards(ids));
  });

  // Collage aus der Auswahl (0.22)
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest?.("[data-bulk-collage]");
    if (!btn || !selected.size) return;
    location.href = `${btn.dataset.collageUrl}?ids=${[...selected].slice(0, 80).join(",")}`;
  });

  function setSelecting(on) {
    body.classList.toggle("selecting", on);
    const bar = bulkBar();
    if (bar) bar.hidden = !on;
    $$("[data-select-toggle]").forEach((b) => b.setAttribute("aria-pressed", String(on)));
    if (!on) selected.clear();
    syncSelection();
  }

  document.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-select-toggle]")) { setSelecting(!selecting()); return; }
    if (ev.target.closest("[data-select-cancel]")) { setSelecting(false); return; }
    if (ev.target.closest("[data-select-results]")) {
      const res = $("#results");
      fetch(res.dataset.idsUrl, { credentials: "same-origin" }).then((r) => r.json()).then((data) => {
        data.ids.forEach((id) => selected.add(String(id)));
        syncSelection();
        toast(`${selected.size} Postings ausgewählt`, "ok");
      });
      return;
    }
    if (ev.target.closest("[data-select-all]")) {
      $$("[data-select-item]").forEach((cb) => selected.add(cb.value));
      syncSelection();
      return;
    }
    if (!selecting()) return;
    // Im Auswahlmodus: Tipp auf die Karte waehlt aus, statt sie zu oeffnen.
    const card = ev.target.closest("[data-post]");
    if (!card || ev.target.closest(".select-box")) return;
    ev.preventDefault();
    const cb = $("[data-select-item]", card);
    if (!cb) return;
    selected.has(cb.value) ? selected.delete(cb.value) : selected.add(cb.value);
    syncSelection();
  }, true);

  document.addEventListener("change", (ev) => {
    const cb = ev.target.closest("[data-select-item]");
    if (cb) { cb.checked ? selected.add(cb.value) : selected.delete(cb.value); syncSelection(); return; }
  });
  document.addEventListener("submit", (ev) => {
    const form = ev.target.closest("[data-bulk-bar]");
    // Nach dem Ablegen zurueck auf genau diese Archivansicht (inkl. Filter)
    if (form) $("[data-bulk-back]", form).value = location.pathname.replace(root(), "") + location.search;
  });
  document.addEventListener("htmx:afterSwap", (ev) => { if (selecting()) syncSelection(ev.target); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && selecting() && !$("dialog[open]")) setSelecting(false); });

  // --- Hinzufuegen: Reiter "Link" / "Screenshot" ------------------------------------------------
  function showAddTab(root, mode) {
    $$("[data-add-tab]", root).forEach((t) => t.toggleAttribute("aria-current", t.dataset.addTab === mode));
    $$("[data-add-panel]", root).forEach((p) => { p.hidden = p.dataset.addPanel !== mode; });
  }
  document.addEventListener("click", (ev) => {
    const tab = ev.target.closest("[data-add-tab]");
    if (!tab) return;
    ev.preventDefault();
    const root = tab.closest("[data-add-tabs]");
    // "Als Thread hinzufuegen": schon eingefuegten Link als ersten Teil mitnehmen
    if (tab.hasAttribute("data-carry-url")) {
      const url = $("[data-url-input]", root)?.value.trim();
      const first = $("[data-thread-url]", root);
      if (url && first && !first.value) first.value = url;
    }
    showAddTab(root, tab.dataset.addTab);
    if (tab.dataset.addTab === "thread") {
      const empty = $$("[data-thread-url]", root).find((i) => !i.value);
      (empty || $("[data-thread-url]", root))?.focus();
    }
  });

  // --- Thread-Teile (0.14): Felder hinzufuegen/entfernen, mehrere Links verteilen ----------------
  function threadRenumber(list) {
    $$(".thread-link", list).forEach((li, i) => {
      $(".tl-no", li).textContent = i + 1;
      const input = $("[data-thread-url]", li);
      input.placeholder = i === 0 ? "Link zum ersten Teil (Anfang)" : `Link zu Teil ${i + 1}`;
      input.setAttribute("aria-label", `Link zu Teil ${i + 1}`);
    });
  }
  function threadAddRow(list, value = "") {
    const rows = $$(".thread-link", list);
    if (rows.length >= 25) return null;
    const li = rows[rows.length - 1].cloneNode(true);
    const input = $("[data-thread-url]", li);
    input.value = value;
    list.appendChild(li);
    threadRenumber(list);
    return input;
  }
  document.addEventListener("click", (ev) => {
    const add = ev.target.closest("[data-thread-add]");
    if (add) {
      const list = $("[data-thread-links]", add.closest("form"));
      threadAddRow(list)?.focus();
      return;
    }
    const rm = ev.target.closest("[data-thread-remove]");
    if (rm) {
      const list = rm.closest("[data-thread-links]");
      const li = rm.closest(".thread-link");
      if ($$(".thread-link", list).length > 2) li.remove();
      else $("[data-thread-url]", li).value = "";
      threadRenumber(list);
    }
  });
  document.addEventListener("input", (ev) => {
    const input = ev.target.closest && ev.target.closest("[data-thread-url]");
    if (!input) return;
    const list = input.closest("[data-thread-links]");
    const rows = $$("[data-thread-url]", list);
    // Letztes Feld ausgefuellt -> automatisch ein neues leeres darunter
    if (input === rows[rows.length - 1] && input.value.trim()) threadAddRow(list);
  });
  document.addEventListener("paste", (ev) => {
    const input = ev.target.closest && ev.target.closest("[data-thread-url]");
    if (!input) return;
    const links = (ev.clipboardData?.getData("text") || "").match(/https?:\/\/\S+/g) || [];
    if (links.length < 2) return;
    ev.preventDefault();
    const list = input.closest("[data-thread-links]");
    let rows = $$("[data-thread-url]", list);
    let i = rows.indexOf(input);
    links.forEach((url) => {
      rows = $$("[data-thread-url]", list);
      const target = rows[i] || threadAddRow(list);
      if (target) target.value = url;
      i += 1;
    });
    if ($$("[data-thread-url]", list).every((r) => r.value.trim())) threadAddRow(list);
    toast(`${links.length} Links verteilt`);
  }, true);

  // --- Screenshot-Upload: Auswahl, Ziehen & Ablegen, Einfuegen (Cmd/Strg+V) -----------------------
  const isVideoFile = (f) => (f.type || "").startsWith("video/") || /\.(mp4|m4v|mov|webm)$/i.test(f.name || "");

  // --- Galerie-Upload (0.13): Standbild + Laenge der Videos im Browser bestimmen, mit Fortschritt senden
  function videoFrame(file) {
    return new Promise((resolve) => {
      const v = document.createElement("video");
      const url = URL.createObjectURL(file);
      let done = false, duration = null;
      const finish = (blob) => {
        if (done) return;
        done = true;
        URL.revokeObjectURL(url);
        resolve({ blob, duration });
      };
      setTimeout(() => finish(null), 15000);  // Format, das der Browser nicht kann: Server uebernimmt
      v.muted = true; v.playsInline = true; v.preload = "auto";
      v.onerror = () => finish(null);
      v.onloadedmetadata = () => {
        duration = isFinite(v.duration) ? v.duration : null;
        v.currentTime = Math.min(1, (duration || 2) / 3);
      };
      v.onseeked = () => {
        const w = v.videoWidth, h = v.videoHeight;
        if (!w || !h) return finish(null);
        const k = Math.min(1, 1600 / Math.max(w, h));
        const c = document.createElement("canvas");
        c.width = Math.round(w * k); c.height = Math.round(h * k);
        try { c.getContext("2d").drawImage(v, 0, 0, c.width, c.height); } catch (e) { return finish(null); }
        c.toBlob((b) => finish(b), "image/jpeg", 0.85);
      };
      v.src = url;
    });
  }
  document.addEventListener("submit", async (ev) => {
    const form = ev.target.closest && ev.target.closest("form[data-gallery-upload]");
    if (!form || !window.XMLHttpRequest || !window.FormData) return;
    const input = $("[data-drop-input]", form);
    const files = Array.from(input.files || []);
    if (!files.length) return;  // Server meldet "bitte auswaehlen"
    ev.preventDefault();
    const btn = $("[data-upload-submit]", form);
    const label = btn.innerHTML;
    btn.disabled = true;
    const data = new FormData(form);
    const info = {};
    const videos = files.map((f, i) => [f, i]).filter(([f]) => isVideoFile(f));
    for (const [f, i] of videos) {
      btn.textContent = videos.length > 1 ? `Bereite Videos vor … (${i + 1})` : "Bereite Video vor …";
      const r = await videoFrame(f);
      if (r.blob) data.append("posters", r.blob, `${i}.jpg`);
      if (r.duration) info[i] = r.duration;
    }
    data.set("video_info", JSON.stringify(info));
    const bar = $("[data-upload-bar]", form), wrap = $("[data-upload-progress]", form);
    if (wrap) wrap.hidden = false;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      if (bar) bar.style.width = pct + "%";
      btn.textContent = pct < 100 ? `Lade hoch … ${pct} %` : "Wird gespeichert …";
    };
    xhr.onload = () => { location.href = xhr.responseURL || form.action.replace(/\/hochladen$/, ""); };
    xhr.onerror = () => {
      btn.disabled = false; btn.innerHTML = label;
      if (wrap) wrap.hidden = true;
      toast("Hochladen fehlgeschlagen – Verbindung prüfen und nochmal versuchen.", "error");
    };
    xhr.send(data);
  });
  function setFiles(zone, files) {
    const input = $("[data-drop-input]", zone);
    const max = parseInt(zone.dataset.dropMax || "10", 10);
    const videosOk = (input.accept || "").includes("video");
    const images = Array.from(files).filter((f) => f.type.startsWith("image/") || (videosOk && isVideoFile(f))).slice(0, max);
    if (!images.length) return;
    const dt = new DataTransfer();
    // Bereits gewaehlte Bilder behalten, neue anhaengen (z. B. mehrere Screenshots nacheinander einfuegen)
    Array.from(input.files || []).forEach((f) => dt.items.add(f));
    images.forEach((f) => { if (dt.items.length < max) dt.items.add(f); });
    input.files = dt.files;
    renderPreviews(zone);
  }
  function renderPreviews(zone) {
    const box = $("[data-drop-previews]", zone);
    const input = $("[data-drop-input]", zone);
    box.replaceChildren();
    Array.from(input.files || []).forEach((f, i) => {
      const fig = document.createElement("span");
      fig.className = "drop-thumb";
      let img;
      if (isVideoFile(f)) {
        img = document.createElement("video");
        img.muted = true; img.playsInline = true; img.preload = "metadata";
        img.src = URL.createObjectURL(f) + "#t=0.5";
        fig.classList.add("is-video");
      } else {
        img = document.createElement("img");
        img.alt = "";
        img.src = URL.createObjectURL(f);
      }
      const btn = document.createElement("button");
      btn.type = "button"; btn.textContent = "×"; btn.dataset.dropRemove = String(i);
      btn.setAttribute("aria-label", `Bild ${i + 1} entfernen`);
      fig.append(img, btn);
      box.appendChild(fig);
    });
    zone.classList.toggle("has-files", (input.files || []).length > 0);
  }
  document.addEventListener("change", (ev) => {
    const input = ev.target.closest("[data-drop-input]");
    if (input) renderPreviews(input.closest("[data-dropzone]"));
  });
  document.addEventListener("click", (ev) => {
    const rm = ev.target.closest("[data-drop-remove]");
    if (!rm) return;
    ev.preventDefault();
    const zone = rm.closest("[data-dropzone]");
    const input = $("[data-drop-input]", zone);
    const dt = new DataTransfer();
    Array.from(input.files).forEach((f, i) => { if (String(i) !== rm.dataset.dropRemove) dt.items.add(f); });
    input.files = dt.files;
    renderPreviews(zone);
  });
  ["dragenter", "dragover"].forEach((t) => document.addEventListener(t, (ev) => {
    const zone = ev.target.closest && ev.target.closest("[data-dropzone]");
    if (zone) { ev.preventDefault(); zone.classList.add("dragging"); }
  }));
  ["dragleave", "drop"].forEach((t) => document.addEventListener(t, (ev) => {
    const zone = ev.target.closest && ev.target.closest("[data-dropzone]");
    if (!zone) return;
    zone.classList.remove("dragging");
    if (t === "drop") { ev.preventDefault(); setFiles(zone, ev.dataTransfer.files); }
  }));
  // Bild aus der Zwischenablage: landet in der sichtbaren Ablage-Flaeche. Ist im Hinzufuegen-Sheet
  // gerade der Link-Reiter offen, wird automatisch auf "Screenshot" umgeschaltet.
  document.addEventListener("paste", (ev) => {
    const files = Array.from(ev.clipboardData?.files || []).filter((f) => f.type.startsWith("image/"));
    if (!files.length) return;
    if (ev.target.closest && ev.target.closest("textarea, input:not([type=file])") && !$("dialog[open]")) return;
    let scope = $("dialog[open]");
    // Kein Sheet offen und keine sichtbare Ablage auf der Seite -> Hinzufuegen-Sheet oeffnen
    const visible = $$("[data-dropzone]").find((z) => z.offsetParent !== null && !z.closest("dialog"));
    // Auf der Galerie-Seite landen eingefuegte Bilder in der Galerie, sonst im Hinzufuegen-Sheet.
    const target = document.getElementById("gallery-upload") ? "gallery-upload" : "add-dialog";
    if (!scope && !visible && document.getElementById(target)) {
      openDialog(target);
      scope = $("#" + target);
    }
    scope = scope || document;
    const tabs = $("[data-add-tabs]", scope);
    if (tabs) showAddTab(tabs, "upload");
    const zone = (scope === document && visible) || $$("[data-dropzone]", scope).find((z) => !z.closest("[hidden]")) || $("[data-dropzone]", scope);
    if (!zone) return;
    ev.preventDefault();
    zone.closest("details")?.setAttribute("open", "");
    setFiles(zone, files);
    toast(files.length === 1 ? "Bild eingefügt" : `${files.length} Bilder eingefügt`);
  });

  // --- Galerie: Vollbild mit Blaettern, Wischen, Tastatur ---------------------------------
  const lb = () => document.getElementById("lightbox");
  let lbIndex = -1;
  const galItems = () => $$("[data-gal-item]");
  function lbShow(i) {
    const items = galItems();
    if (!items.length || !lb()) return;
    lbIndex = (i + items.length) % items.length;
    const a = items[lbIndex], box = lb();
    const img = $("[data-lb-img]", box);
    const vid = $("[data-lb-video]", box);
    const isVideo = a.dataset.kind === "video";
    img.hidden = isVideo;
    if (vid) {
      vid.pause();
      vid.hidden = !isVideo;
      if (isVideo) {
        vid.poster = a.dataset.poster || "";
        vid.src = a.dataset.full;
        vid.play().catch(() => { /* Autoplay blockiert: Nutzer tippt auf Play */ });
      } else {
        vid.removeAttribute("src");
        vid.load();
      }
    }
    if (!isVideo) {
      img.classList.remove("is-loaded");
      img.onload = () => img.classList.add("is-loaded");
      img.style.setProperty("--c", a.style.getPropertyValue("--c"));
      img.src = a.dataset.full;
      img.alt = a.dataset.title || "";
    }
    $("[data-lb-count]", box).textContent = `${lbIndex + 1} / ${items.length}`;
    $("[data-lb-download]", box).href = a.dataset.full + "?download=1";
    $("[data-lb-title]", box).textContent = a.dataset.title || "Ohne Titel";
    $("[data-lb-title]", box).classList.toggle("is-empty", !a.dataset.title);
    $("[data-lb-note]", box).textContent = a.dataset.note || "";
    $("[data-lb-meta]", box).textContent = a.dataset.meta || "";
    const cats = $("[data-lb-cats]", box);
    cats.replaceChildren();
    const names = (a.dataset.cats || "").split("|").filter(Boolean), tones = (a.dataset.tones || "").split("|");
    names.forEach((n, k) => {
      const c = document.createElement("span");
      c.className = "lb-cat";
      c.innerHTML = `<i class="dot tone-${tones[k] || 0}"></i>`;
      c.append(n);
      cats.appendChild(c);
    });
    const edit = $("[data-lb-edit]", box);
    edit.setAttribute("hx-get", a.dataset.edit + "?back=" + encodeURIComponent(location.pathname.replace(root(), "") + location.search));
    if (window.htmx) window.htmx.process(edit);
    // Nachbarn vorladen - Blaettern fuehlt sich sofort an
    [1, -1].forEach((d) => {
      const n = items[(lbIndex + d + items.length) % items.length];
      if (n) new Image().src = n.dataset.kind === "video" ? n.dataset.poster : n.dataset.full;
    });
    if (!box.open) box.showModal();
  }
  // Vollbild zu (x, Esc, Wischen): Video anhalten. "close" blubbert nicht -> Capture-Phase.
  document.addEventListener("close", (ev) => {
    if (ev.target !== lb()) return;
    const v = $("[data-lb-video]", ev.target);
    if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
  }, true);
  document.addEventListener("click", (ev) => {
    const item = ev.target.closest("[data-gal-item]");
    if (item) { ev.preventDefault(); lbShow(galItems().indexOf(item)); return; }
    const box = lb();
    if (!box || !box.open) return;
    if (ev.target.closest("[data-lb-next]")) lbShow(lbIndex + 1);
    else if (ev.target.closest("[data-lb-prev]")) lbShow(lbIndex - 1);
    else if (ev.target.closest("[data-lb-close]")) box.close();
    else if (ev.target.closest("[data-lb-info]")) {
      const on = box.classList.toggle("show-info");
      $("[data-lb-info]", box).setAttribute("aria-pressed", String(on));
    } else if (ev.target === box || ev.target.closest("[data-lb-stage]") && !["IMG", "VIDEO"].includes(ev.target.tagName)) box.close();
  });
  document.addEventListener("keydown", (ev) => {
    const box = lb();
    if (!box || !box.open || $("dialog.sheet[open]")) return;
    if (ev.key === "ArrowRight") { ev.preventDefault(); lbShow(lbIndex + 1); }
    else if (ev.key === "ArrowLeft") { ev.preventDefault(); lbShow(lbIndex - 1); }
    else if (ev.key === "i") { $("[data-lb-info]", box).click(); }
  });
  let touchX = null, touchY = null;
  document.addEventListener("touchstart", (ev) => {
    if (!ev.target.closest || !ev.target.closest("[data-lb-stage]")) return;
    touchX = ev.touches[0].clientX; touchY = ev.touches[0].clientY;
  }, { passive: true });
  document.addEventListener("touchend", (ev) => {
    if (touchX === null) return;
    const dx = ev.changedTouches[0].clientX - touchX, dy = ev.changedTouches[0].clientY - touchY;
    touchX = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) lbShow(lbIndex + (dx < 0 ? 1 : -1));
    else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) lb()?.close();  // nach unten wischen = schliessen
  }, { passive: true });

  // --- Handy: Tab-Leiste ausblenden, solange getippt wird (0.12) -----------------------------
  // Android schiebt fest unten klebende Leisten sonst ueber die Tastatur, iOS
  // laesst sie nach dem Schliessen der Tastatur manchmal mitten im Bild stehen.
  const isTextField = (el) => el && el.matches && el.matches(
    "input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]):not([type=button]):not([type=submit]), textarea, select, [contenteditable]");
  let typingTimer = null;
  document.addEventListener("focusin", (ev) => {
    if (!isTextField(ev.target)) return;
    clearTimeout(typingTimer);
    document.documentElement.classList.add("is-typing");
  });
  document.addEventListener("focusout", (ev) => {
    if (!isTextField(ev.target)) return;
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => {
      if (!isTextField(document.activeElement)) document.documentElement.classList.remove("is-typing");
    }, 120);
  });

  // --- Idiotarium: "#…" im Suchfeld schlaegt Tags vor (0.15) ------------------------------------
  let pickTimer = null;
  function hashWord(input) {
    const before = input.value.slice(0, input.selectionStart ?? input.value.length);
    const m = before.match(/(?:^|\s)#([^\s#]*)$/);
    return m ? { word: m[1], start: before.length - m[1].length - 1 } : null;
  }
  function pickTag(form, name) {
    const field = $("[data-tag-filter]", form);
    const tags = new Set((field.value || "").split(",").map((t) => t.trim()).filter(Boolean));
    tags.add(name);
    field.value = [...tags].join(",");
    $$(`[data-tag-toggle="${CSS.escape(name)}"]`, form).forEach((b) => b.setAttribute("aria-pressed", "true"));
    field.dispatchEvent(new Event("change", { bubbles: true }));
  }
  document.addEventListener("input", (ev) => {
    const input = ev.target.closest && ev.target.closest("[data-tag-pick-url]");
    if (!input) return;
    const box = $("[data-search-tags]", input.closest("form"));
    const hw = hashWord(input);
    clearTimeout(pickTimer);
    if (!hw) { box.hidden = true; return; }
    pickTimer = setTimeout(async () => {
      const r = await fetch(`${input.dataset.tagPickUrl}&tq=${encodeURIComponent(hw.word)}&tags=${encodeURIComponent($("[data-tag-filter]", input.closest("form")).value)}`,
                            { credentials: "same-origin" });
      if (!r.ok) return;
      box.innerHTML = await r.text();
      box.hidden = false;
    }, 120);
  });
  document.addEventListener("click", (ev) => {
    const pick = ev.target.closest("[data-tag-pick]");
    const boxes = $$("[data-search-tags]");
    if (!pick) { boxes.forEach((b) => { if (!b.contains(ev.target)) b.hidden = true; }); return; }
    const form = pick.closest("form");
    const input = $("[data-tag-pick-url]", form);
    const hw = hashWord(input);
    if (hw) input.value = (input.value.slice(0, hw.start) + input.value.slice(hw.start + hw.word.length + 1)).replace(/\s{2,}/g, " ").trim();
    $("[data-search-tags]", form).hidden = true;
    pickTag(form, pick.dataset.tagPick);
    input.focus();
  });
  document.addEventListener("keydown", (ev) => {
    const input = ev.target.closest && ev.target.closest("[data-tag-pick-url]");
    if (!input) return;
    const box = $("[data-search-tags]", input.closest("form"));
    if (ev.key === "Escape") { box.hidden = true; return; }
    if ((ev.key === "Enter" || ev.key === " ") && hashWord(input) && !box.hidden) {
      const first = $("[data-tag-pick]", box);
      if (first) { ev.preventDefault(); first.click(); }
    }
  });

  // --- Recherche-Arbeitsplatz (0.15): rechts lesen/bearbeiten ohne Seitenwechsel ------------------
  const paneWide = () => window.matchMedia("(min-width: 1000px)").matches && document.getElementById("rs-pane");
  function openInPane(href) {
    const pane = document.getElementById("rs-pane");
    if (!pane || !window.htmx) return false;
    window.htmx.ajax("GET", href, { target: "#rs-pane", swap: "innerHTML" }).then(() => {
      pane.scrollIntoView({ block: "nearest" });
      pane.querySelector("textarea, input[type=text]")?.focus({ preventScroll: true });
    });
    const id = (href.match(/\/recherche\/(\d+)(?:$|\?|\/bearbeiten)/) || [])[1];
    $$("[data-rs-id]").forEach((a) => a.classList.toggle("is-active", a.dataset.rsId === id));
    if (id) {
      const u = new URL(location.href);
      u.searchParams.set("id", id);
      history.replaceState(null, "", u);
    }
    return true;
  }
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-pane-link]");
    if (a && paneWide() && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey) {
      if (openInPane(a.getAttribute("href"))) ev.preventDefault();
      return;
    }
    const cancel = ev.target.closest("[data-pane-cancel]");
    if (cancel && paneWide()) {
      ev.preventDefault();
      const active = $("[data-rs-id].is-active") || $("[data-rs-id]");
      if (active) openInPane(active.getAttribute("href"));
      else document.getElementById("rs-pane").innerHTML = "";
    }
  });

  // Liste links neu geladen: aktiven Eintrag (aus der Adresse) wieder markieren
  document.addEventListener("htmx:afterSettle", (ev) => {
    if (!ev.target || ev.target.id !== "rs-index") return;
    const id = new URL(location.href).searchParams.get("id");
    if (id) $$("[data-rs-id]").forEach((a) => a.classList.toggle("is-active", a.dataset.rsId === id));
  });

  // --- Auswahlfelder mit Suche (Recherche: Personen, Postings) -----------------------------------
  document.addEventListener("click", (ev) => {
    const add = ev.target.closest("[data-picker-add]");
    if (add) {
      const picker = add.closest("[data-picker]");
      const name = picker.dataset.name;
      const chips = $("[data-picker-chips]", picker);
      if (!$(`input[name="${name}"][value="${add.dataset.id}"]`, chips)) {
        const chip = document.createElement("span");
        chip.className = "tp-chip";
        chip.textContent = add.dataset.label;
        const x = document.createElement("button");
        x.type = "button"; x.dataset.pickerRemove = ""; x.textContent = "×"; x.setAttribute("aria-label", `${add.dataset.label} entfernen`);
        const hidden = document.createElement("input");
        hidden.type = "hidden"; hidden.name = name; hidden.value = add.dataset.id;
        chip.append(x, hidden);
        chips.appendChild(chip);
      }
      const q = $("[data-picker-q]", picker);
      q.value = "";
      $("[data-picker-results]", picker).replaceChildren();
      q.focus();
      return;
    }
    const rm = ev.target.closest("[data-picker-remove]");
    if (rm) { rm.closest(".tp-chip").remove(); return; }
    $$("[data-picker]").forEach((p) => { if (!p.contains(ev.target)) $("[data-picker-results]", p)?.replaceChildren(); });
  });
  document.addEventListener("keydown", (ev) => {
    const q = ev.target.closest && ev.target.closest("[data-picker-q]");
    if (!q) return;
    const picker = q.closest("[data-picker]");
    if (ev.key === "Enter") {
      ev.preventDefault();  // Enter waehlt den ersten Treffer, schickt aber nie das Formular ab
      $("[data-picker-add]", picker)?.click();
    } else if (ev.key === "Backspace" && !q.value) {
      const chips = $$(".tp-chip", picker);
      chips[chips.length - 1]?.remove();
    } else if (ev.key === "Escape") {
      $("[data-picker-results]", picker).replaceChildren();
    }
  });

  // --- Kommentare (0.17): Feld waechst mit, Strg/Cmd+Enter sendet ------------------------------
  const growCm = (t) => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 320) + "px"; };
  document.addEventListener("input", (ev) => {
    if (ev.target.matches && ev.target.matches("[data-cm-input]")) growCm(ev.target);
  });
  document.addEventListener("keydown", (ev) => {
    const t = ev.target.closest && ev.target.closest("[data-cm-input]");
    if (t && ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); t.form?.requestSubmit(); }
  });
  document.addEventListener("htmx:afterSettle", (ev) => {
    if (!ev.target || ev.target.id !== "kommentare") return;
    const t = $("[data-autofocus]", ev.target);
    if (t) {
      const last = $$(".cm", ev.target).pop();
      last?.scrollIntoView({ block: "center", behavior: "smooth" });
      last?.classList.add("is-new");
      t.focus({ preventScroll: true });
    }
  });

  // --- Auswahlfeld schickt sein Formular sofort ab (z. B. Tag einordnen) -------------------------
  document.addEventListener("change", (ev) => {
    if (ev.target.matches && ev.target.matches("select[data-autosubmit]")) ev.target.form?.requestSubmit();
    if (ev.target.matches && ev.target.matches("[data-tag-select]")) {
      const n = $$("[data-tag-select]:checked").length;
      const bar = $("[data-tag-bulk]");
      if (bar) { bar.hidden = n === 0; $("[data-tag-count]", bar).textContent = n; }
    }
  });

  // --- Recherche: Personen-Auswahl filtern (ausgewaehlte bleiben sichtbar) --------------------
  document.addEventListener("input", (ev) => {
    if (!ev.target.matches || !ev.target.matches("[data-person-filter]")) return;
    const q = ev.target.value.trim().toLowerCase();
    $$("[data-person-name]").forEach((el) => {
      el.hidden = q && !el.dataset.personName.includes(q) && !$("input", el).checked;
    });
  });

  // --- Alle Tags (Archiv): filtern ------------------------------------------------------------
  document.addEventListener("input", (ev) => {
    if (!ev.target.matches || !ev.target.matches("[data-tb-search]")) return;
    const q = ev.target.value.trim().toLowerCase().replace(/^#/, "");
    $$("[data-tb-group]").forEach((g) => {
      let any = false;
      $$("[data-tb-name]", g).forEach((b) => { const hit = !q || b.dataset.tbName.includes(q); b.hidden = !hit; any = any || hit; });
      g.hidden = !any;
    });
  });

  // --- Automatisch taggen (0.20): Wortvorschlag in die Begriffe uebernehmen --------------------
  document.addEventListener("click", (ev) => {
    const chip = ev.target.closest?.("[data-add-term]");
    if (!chip) return;
    const area = $("[data-ar-terms]");
    if (!area) return;
    const lines = area.value.split("\n").map((l) => l.trim()).filter(Boolean);
    const term = chip.dataset.addTerm;
    if (!lines.includes(term)) lines.push(term);
    area.value = lines.join("\n");
    chip.classList.add("is-added");
    area.dispatchEvent(new Event("input", { bubbles: true }));
  });

  // --- Tags organisieren: suchen und sortieren ------------------------------------------------
  function tgApply() {
    const table = $(".tg-table");
    if (!table) return;
    const q = ($("[data-tag-search]")?.value || "").trim().toLowerCase().replace(/^#/, "");
    const sort = $("[data-tg-sort]")?.value || "count";
    let shown = 0;
    $$("[data-tg-rows]", table).forEach((box) => {
      const rows = $$("[data-tg-row]", box);
      rows.sort((a, b) => sort === "name" ? a.dataset.name.localeCompare(b.dataset.name, "de")
        : Number(b.dataset.count) - Number(a.dataset.count) || a.dataset.name.localeCompare(b.dataset.name, "de"));
      rows.forEach((r) => { box.appendChild(r); r.hidden = !!q && !r.dataset.name.includes(q); if (!r.hidden) shown++; });
      const section = box.closest("[data-tg-section]");
      if (section) section.hidden = !!q && !rows.some((r) => !r.hidden);
    });
    const none = $("[data-tg-none]");
    if (none) none.hidden = shown > 0 || !q;
  }
  document.addEventListener("input", (ev) => { if (ev.target.matches?.("[data-tag-search]")) tgApply(); });
  document.addEventListener("change", (ev) => {
    if (!ev.target.matches?.("[data-tg-sort]")) return;
    remember("tt.tags.sort", ev.target.value);
    tgApply();
  });
  document.addEventListener("DOMContentLoaded", () => {
    const sel = $("[data-tg-sort]");
    if (!sel) return;
    const saved = recall("tt.tags.sort");
    if (saved === "name" || saved === "count") sel.value = saved;
    tgApply();
  });

  // --- Galerie: Darstellung und Groesse (0.12, pro Browser gemerkt) ---------------------------
  const GAL_SCALE = [0.55, 0.75, 1, 1.35, 1.8];
  const remember = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* privat: egal */ } };
  const recall = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  function applyGallery() {
    const style = recall("tt.gal.style") === "square" ? "square" : "mosaic";
    const size = Math.min(5, Math.max(1, parseInt(recall("tt.gal.size") || "3", 10) || 3));
    const gal = $("[data-gallery]");
    if (gal) {
      gal.classList.toggle("is-square", style === "square");
      gal.style.setProperty("--scale", GAL_SCALE[size - 1]);
    }
    $$("[data-gal-style]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.galStyle === style)));
    $$("[data-gal-size]").forEach((r) => (r.value = size));
  }
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-gal-style]");
    if (!b) return;
    remember("tt.gal.style", b.dataset.galStyle);
    applyGallery();
  });
  document.addEventListener("input", (ev) => {
    if (!ev.target.matches || !ev.target.matches("[data-gal-size]")) return;
    remember("tt.gal.size", ev.target.value);
    applyGallery();
  });
  document.addEventListener("htmx:afterSettle", applyGallery);

  // --- Raster als Mauerwerk (0.12) ------------------------------------------------------------
  // Jede Kachel ist so hoch wie ihr Text; das Grid hat 2px-Zeilen, jede Kachel
  // spannt so viele, wie sie braucht. Reihenfolge bleibt zeilenweise.
  const ROW = 2;
  function layoutMasonry(grid) {
    if (!grid || !grid.classList.contains("view-raster")) return;
    const narrow = getComputedStyle(grid).gridTemplateColumns.split(" ").length < 2;
    grid.classList.toggle("is-masonry", !narrow);
    if (narrow) { $$(".qtile", grid).forEach((t) => (t.style.gridRowEnd = "")); return; }
    const gap = parseFloat(getComputedStyle($(".qtile", grid) || grid).marginBottom) || 0;
    $$(".qtile", grid).forEach((t) => {
      t.style.gridRowEnd = `span ${Math.max(1, Math.ceil((t.getBoundingClientRect().height + gap) / ROW))}`;
    });
  }
  let masonryObserver = null;
  function initMasonry() {
    const grid = $("#post-grid.view-raster");
    if (!grid) return;
    layoutMasonry(grid);
    if (window.ResizeObserver) {
      masonryObserver?.disconnect();
      let queued = false;
      masonryObserver = new ResizeObserver(() => {
        if (queued) return;
        queued = true;
        requestAnimationFrame(() => { queued = false; layoutMasonry(grid); });
      });
      masonryObserver.observe(grid);
      $$(".qtile", grid).forEach((t) => masonryObserver.observe(t));
    }
    $$("img", grid).forEach((img) => { if (!img.complete) img.addEventListener("load", () => layoutMasonry(grid), { once: true }); });
  }
  document.addEventListener("htmx:afterSettle", initMasonry);
  window.addEventListener("load", initMasonry);
  document.fonts?.ready?.then(initMasonry);

  // --- Start ---------------------------------------------------------------------------------
  // Sprungmarke in einem eingeklappten Bereich (z. B. #datum nach dem Speichern): aufklappen
  function openHashTarget() {
    if (!location.hash) return;
    let el = null;
    try { el = document.querySelector(location.hash); } catch (e) { return; }
    let d = el && el.closest("details");
    while (d) { d.open = true; d = d.parentElement && d.parentElement.closest("details"); }
    if (el && el.tagName !== "DETAILS") el.scrollIntoView({ block: "center" });
  }
  window.addEventListener("hashchange", openHashTarget);

  // --- "Neu in x.x" (0.14): beim ersten Laden zeigen, Schliessen merkt es sich -------------------
  function initRelease() {
    const dlg = $("[data-release-dialog]");
    if (!dlg || dlg.open || $("dialog[open]")) return;
    const form = $("[data-release-form]", dlg);
    const markSeen = () => {
      if (dlg.dataset.sent) return;
      dlg.dataset.sent = "1";
      fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
        .catch(() => { /* naechstes Mal wieder */ });
    };
    form.addEventListener("submit", (ev) => { ev.preventDefault(); markSeen(); dlg.close(); });
    dlg.addEventListener("close", markSeen);
    setTimeout(() => dlg.showModal(), 350);
  }

  // Kopfzeile bekommt beim Scrollen eine Kante
  const onScroll = () => document.documentElement.classList.toggle("is-scrolled", window.scrollY > 4);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  function init(scope) {
    $$("[data-autoclose]", scope).forEach(autoclose);
    if (scope === document) initRelease();
    if (scope === document) openHashTarget();
    const form = $("#gen-form");
    if (scope === document && form && form.dataset.focus) {
      const field = $(`[name="${form.dataset.focus}"]`, form);
      if (field) field.focus();
    }
  }
  document.addEventListener("DOMContentLoaded", () => { init(document); initMasonry(); applyGallery(); });
})();
