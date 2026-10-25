/* TrashTwitter – Collage-Studio (0.22)
 * Einstellungen -> Vorschau (iframe, skaliert) und Export (JPG vom Server).
 */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const SIZES = { square: [2160, 2160], portrait: [2160, 2700], story: [2160, 3840], wide: [3840, 2160], long: [2160, 0] };
  const KEEP = ["format", "stil", "inhalt", "datum", "nummern", "bilder", "fusszeile", "reihenfolge"];
  const store = {
    get() { try { return JSON.parse(localStorage.getItem("tt.collage") || "{}"); } catch (e) { return {}; } },
    set(v) { try { localStorage.setItem("tt.collage", JSON.stringify(v)); } catch (e) { /* egal */ } },
  };

  function init() {
    const studio = $("[data-collage-studio]");
    if (!studio) return;
    const form = $("[data-cs-form]", studio), frame = $("[data-preview]", studio), wrap = $("[data-frame-wrap]", studio);
    const busy = $("[data-busy]", studio), info = $("[data-info]", studio), list = $("[data-post-list]", studio);
    const exportBtn = $("[data-export]", studio), shareBtn = $("[data-export-share]", studio), msg = $("[data-export-msg]", studio);
    let contentH = 0, timer = 0, lastFile = null;

    // Gemerkte Einstellungen (nicht Titel/Texte - die kommen aus der Suche)
    const saved = store.get();
    KEEP.forEach((k) => {
      if (!(k in saved)) return;
      const el = form.elements[k];
      if (!el) return;
      if (el instanceof RadioNodeList) {
        const r = $$(`input[name="${k}"]`, form).find((i) => i.value === saved[k] && !i.disabled);
        if (r) r.checked = true;
      } else if (el.type === "checkbox") el.checked = !!saved[k];
      else el.value = saved[k];
    });

    function order() {
      const mode = form.elements.reihenfolge.value;
      const rows = $$("li[data-id]", list);
      rows.sort((a, b) => mode === "found" ? a.dataset.idx - b.dataset.idx
        : mode === "old" ? (a.dataset.date || "").localeCompare(b.dataset.date || "")
        : (b.dataset.date || "").localeCompare(a.dataset.date || ""));
      rows.forEach((r) => list.appendChild(r));
    }
    function ids() { return $$("li[data-id]", list).filter((li) => $("[data-post-on]", li).checked).map((li) => li.dataset.id); }
    function query() {
      const p = new URLSearchParams();
      p.set("ids", ids().join(","));
      ["titel", "untertitel", "markieren"].forEach((k) => p.set(k, form.elements[k].value));
      ["format", "stil", "inhalt"].forEach((k) => p.set(k, form.elements[k].value));
      ["datum", "nummern", "bilder", "fusszeile"].forEach((k) => p.set(k, form.elements[k].checked ? "1" : "0"));
      return p.toString();
    }
    function size() { return SIZES[form.elements.format.value] || SIZES.portrait; }

    // Ganze Grafik zeigen: in Breite und Hoehe einpassen (Endlos: nur in die Breite)
    function fit() {
      const [w, h] = size();
      const height = h || contentH || w * 1.5;
      const stage = wrap.parentElement;
      const maxW = stage.clientWidth;
      const maxH = h && window.innerWidth > 980 ? Math.max(320, window.innerHeight - stage.getBoundingClientRect().top - 60) : Infinity;
      const scale = Math.min(maxW / w, maxH / height);
      frame.style.width = w + "px";
      frame.style.height = height + "px";
      frame.style.transform = `scale(${scale})`;
      wrap.style.width = Math.round(w * scale) + "px";
      wrap.style.height = Math.round(height * scale) + "px";
    }
    window.addEventListener("resize", fit);
    function remember() {
      const v = {};
      KEEP.forEach((k) => {
        const el = form.elements[k];
        v[k] = el.type === "checkbox" ? el.checked : el.value;
      });
      store.set(v);
    }
    function refresh() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const n = ids().length;
        $("[data-post-count]", studio).textContent = `${n} von ${$$("li[data-id]", list).length}`;
        exportBtn.disabled = n === 0;
        lastFile = null;
        if (!n) { info.textContent = "Keine Postings ausgewählt."; return; }
        busy.hidden = false;
        contentH = 0;
        fit();
        frame.src = `${studio.dataset.previewUrl}?${query()}`;
        remember();
      }, 350);
    }

    window.addEventListener("message", (ev) => {
      if (ev.source !== frame.contentWindow || !ev.data || !ev.data.collage) return;
      busy.hidden = true;
      contentH = ev.data.height;
      fit();
      const [w, h] = size();
      info.textContent = `${w} × ${h || ev.data.height} px · ${ev.data.cols} ${ev.data.cols === 1 ? "Spalte" : "Spalten"}`;
    });
    new ResizeObserver(fit).observe(wrap.parentElement);
    form.addEventListener("submit", (ev) => ev.preventDefault());
    form.addEventListener("input", (ev) => { if (ev.target.name === "reihenfolge") order(); refresh(); });
    form.addEventListener("change", (ev) => { if (ev.target.name === "reihenfolge") order(); refresh(); });
    studio.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-check-all]")) { $$("[data-post-on]", list).forEach((c) => { c.checked = true; }); refresh(); }
      if (ev.target.closest("[data-check-none]")) { $$("[data-post-on]", list).forEach((c) => { c.checked = false; }); refresh(); }
    });

    // Export: Server rendert das JPG (dauert ein paar Sekunden)
    async function makeFile() {
      exportBtn.disabled = true;
      msg.textContent = "Bild wird erzeugt …";
      try {
        const res = await fetch(`${studio.dataset.exportUrl}?${query()}`, { credentials: "same-origin" });
        if (!res.ok) throw new Error((await res.text()).slice(0, 200) || res.statusText);
        const blob = await res.blob();
        const cd = res.headers.get("Content-Disposition") || "";
        const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "collage.jpg";
        lastFile = new File([blob], name, { type: "image/jpeg" });
        msg.textContent = `Fertig: ${name} (${Math.round(blob.size / 1024)} KB)`;
        return lastFile;
      } catch (e) {
        msg.textContent = "Das Bild ließ sich gerade nicht erzeugen. Bitte noch einmal versuchen.";
        return null;
      } finally {
        exportBtn.disabled = ids().length === 0;
      }
    }
    exportBtn.addEventListener("click", async () => {
      const file = lastFile || await makeFile();
      if (!file) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(file);
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      if (navigator.canShare && navigator.canShare({ files: [file] })) shareBtn.hidden = false;
    });
    shareBtn.addEventListener("click", async () => {
      const file = lastFile || await makeFile();
      if (!file) return;
      try { await navigator.share({ files: [file], title: form.elements.titel.value || "Collage" }); } catch (e) { /* abgebrochen */ }
    });
    // Am Handy gleich teilen statt speichern anbieten
    if (navigator.canShare && navigator.canShare({ files: [new File([""], "x.jpg", { type: "image/jpeg" })] })) shareBtn.hidden = false;

    order();
    refresh();
  }
  document.addEventListener("DOMContentLoaded", init);
})();
