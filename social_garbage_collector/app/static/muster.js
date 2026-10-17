/* TrashTwitter – Muster (0.19): Chronik (SVG) und Themen-Netz (force-graph).
 * Daten kommen eingebettet aus pattern.html (#muster-data), siehe services/patterns.py.
 */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const NS = "http://www.w3.org/2000/svg";
  const PALETTE = ["#2bb5a8", "#e0794f", "#6f8fe8", "#d4a72c", "#b46fd6", "#4fae6f", "#e05a8a", "#5aa7c9", "#a3895b", "#8f9bb3"];
  const FIGURE = "#f0a830";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("tt.muster." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("tt.muster." + k, JSON.stringify(v)); } catch (e) { /* egal */ } },
  };

  function el(name, attrs = {}, parent) {
    const n = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  function init() {
    const dataEl = $("#muster-data");
    if (!dataEl) return;
    const D = JSON.parse(dataEl.textContent);
    const tagById = new Map(D.tags.map((t) => [t.id, t]));
    const archive = (names) => `${D.base}/?person=${D.person}&tags=${encodeURIComponent(names.join(","))}`;

    // Personenwechsel
    const sw = $("[data-pt-switch]");
    if (sw) sw.addEventListener("change", () => { if (sw.value) location.href = sw.value; });

    chronik(D, tagById);
    themennetz(D, tagById, archive);
  }

  // --- Chronik ---------------------------------------------------------------------------------
  function chronik(D, tagById) {
    const box = $("[data-chronik]");
    if (!box) return;
    const chart = $("[data-chart]", box), pick = $("[data-lanes-pick]", box), tip = $("[data-tip]", box);
    const dated = D.posts.filter((p) => p.t).map((p) => Object.assign({}, p, { d: new Date(p.t + "T12:00:00") }));
    if (!dated.length) { chart.innerHTML = `<p class="faint small">Keine Postings mit Datum.</p>`; return; }
    const ranked = D.tags.slice(0, 30);
    const key = "lanes." + D.person;
    let lanes = store.get(key, null);
    if (!Array.isArray(lanes) || !lanes.every((id) => tagById.has(id))) {
      lanes = D.tags.filter((t) => t.n > 1).slice(0, 8).map((t) => t.id);
    }
    const color = (id) => (tagById.get(id)?.kind === "figur" ? FIGURE : PALETTE[ranked.findIndex((t) => t.id === id) % PALETTE.length] || PALETTE[9]);

    function renderPick() {
      pick.innerHTML = ranked.map((t) => `<button type="button" class="pt-lane-chip" data-lane="${t.id}" aria-pressed="${lanes.includes(t.id)}"
        style="--c:${color(t.id)}"><i></i>${t.kind === "figur" ? "👤 " : ""}#${esc(t.name)} <small>${t.n}</small></button>`).join("")
        + (D.tags.length > 30 ? `<span class="faint xs">+${D.tags.length - 30} seltene</span>` : "");
    }
    pick.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-lane]");
      if (!b) return;
      const id = Number(b.dataset.lane);
      lanes = lanes.includes(id) ? lanes.filter((x) => x !== id) : [...lanes, id].sort((a, c) => tagById.get(c).n - tagById.get(a).n);
      store.set(key, lanes);
      renderPick(); draw();
    });

    const y0 = new Date(D.years[0], 0, 1), y1 = new Date(D.years[1] + 1, 0, 1);
    function draw() {
      const W = Math.max(220, chart.clientWidth), mobile = W < 560;
      const LBL = mobile ? 92 : 150, PAD_R = 14, HIST = 54, LANE = mobile ? 30 : 32, AXIS = 26;
      const H = HIST + lanes.length * LANE + AXIS + 8;
      const x = (d) => LBL + ((d - y0) / (y1 - y0)) * (W - LBL - PAD_R);
      chart.innerHTML = "";
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Chronik der Postings nach Tags" }, chart);
      // Jahresraster
      for (let y = D.years[0]; y <= D.years[1] + 1; y++) {
        const xx = x(new Date(y, 0, 1));
        el("line", { x1: xx, x2: xx, y1: 4, y2: H - AXIS, class: "pt-grid" }, svg);
        if (y <= D.years[1]) {
          const mid = x(new Date(y, 6, 1));
          const t = el("text", { x: mid, y: H - 8, class: "pt-axis", "text-anchor": "middle" }, svg);
          t.textContent = mobile && D.years[1] - D.years[0] > 5 ? "’" + String(y).slice(2) : y;
        }
      }
      // Histogramm: alle Postings je Quartal
      const q = new Map();
      dated.forEach((p) => { const k = p.d.getFullYear() * 4 + Math.floor(p.d.getMonth() / 3); q.set(k, (q.get(k) || 0) + 1); });
      const peak = Math.max(...q.values());
      const lbl = el("text", { x: 8, y: HIST / 2 + 4, class: "pt-lane-label" }, svg);
      lbl.textContent = "Alle";
      const sub = el("text", { x: 8, y: HIST / 2 + 18, class: "pt-lane-sub" }, svg);
      sub.textContent = `${dated.length} Postings`;
      for (const [k, n] of q) {
        const yr = Math.floor(k / 4), qu = k % 4;
        const a = x(new Date(yr, qu * 3, 1)), b = x(new Date(yr, qu * 3 + 3, 1));
        const h = Math.max(2, (n / peak) * (HIST - 12));
        const r = el("rect", { x: a + 1, y: HIST - 4 - h, width: Math.max(1, b - a - 2), height: h, rx: 2, class: "pt-hist" }, svg);
        el("title", {}, r).textContent = `${yr} Q${qu + 1}: ${n} Postings`;
      }
      // Spuren je Tag
      lanes.forEach((id, i) => {
        const t = tagById.get(id), top = HIST + i * LANE, c = color(id);
        el("rect", { x: 0, y: top, width: W, height: LANE, class: i % 2 ? "pt-lane odd" : "pt-lane" }, svg);
        const label = el("text", { x: 8, y: top + LANE / 2 + 4, class: "pt-lane-label" }, svg);
        const name = (t.kind === "figur" ? "👤 " : "#") + t.name;
        label.textContent = name.length > (mobile ? 10 : 17) ? name.slice(0, mobile ? 9 : 16) + "…" : name;
        el("title", {}, label).textContent = `#${t.name}: ${t.n} Postings`;
        const cnt = el("text", { x: LBL - 8, y: top + LANE / 2 + 4, class: "pt-lane-count", "text-anchor": "end" }, svg);
        cnt.textContent = t.n;
        dated.forEach((p) => {
          if (!p.g.includes(id)) return;
          const jitter = ((p.id * 2654435761) % 1000) / 1000 - 0.5;
          const dot = el("circle", { cx: x(p.d), cy: top + LANE / 2 + jitter * (LANE - 14), r: mobile ? 4 : 4.6, fill: c, class: "pt-dot", tabindex: 0,
            "data-post": p.id }, svg);
          dot.__post = p;
        });
      });
    }

    function showTip(dot, evX, evY) {
      const p = dot.__post;
      const r = $("[data-chart]", box).getBoundingClientRect(), br = box.getBoundingClientRect();
      tip.innerHTML = `<time>${p.d.toLocaleDateString("de-DE")}</time><p>${esc(p.s || "Kein Wortlaut")}</p>
        <span>${p.g.map((g) => `#${esc(tagById.get(g)?.name)}`).join(" ")}</span>`;
      tip.hidden = false;
      const w = tip.offsetWidth, h = tip.offsetHeight;
      let left = evX - br.left + 12, top = evY - br.top + 14;
      if (left + w > br.width - 8) left = Math.max(8, evX - br.left - w - 12);
      if (top + h > br.height - 8) top = Math.max(8, evY - br.top - h - 12);
      tip.style.left = left + "px"; tip.style.top = top + "px";
      void r;
    }
    chart.addEventListener("mouseover", (ev) => { const d = ev.target.closest(".pt-dot"); if (d) showTip(d, ev.clientX, ev.clientY); });
    chart.addEventListener("mouseout", (ev) => { if (ev.target.closest(".pt-dot")) tip.hidden = true; });
    chart.addEventListener("focusin", (ev) => { const d = ev.target.closest(".pt-dot"); if (d) { const b = d.getBoundingClientRect(); showTip(d, b.right, b.bottom); } });
    chart.addEventListener("focusout", () => { tip.hidden = true; });
    chart.addEventListener("click", (ev) => { const d = ev.target.closest(".pt-dot"); if (d) location.href = `${D.base}/posts/${d.dataset.post}`; });
    chart.addEventListener("keydown", (ev) => {
      const d = ev.target.closest(".pt-dot");
      if (d && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); location.href = `${D.base}/posts/${d.dataset.post}`; }
    });

    renderPick(); draw();
    // Nur bei neuer Breite neu zeichnen - die Hoehe aendert sich durchs Zeichnen selbst
    let rt = 0, lastW = chart.clientWidth;
    new ResizeObserver(() => {
      if (chart.clientWidth === lastW) return;
      lastW = chart.clientWidth;
      clearTimeout(rt); rt = setTimeout(draw, 120);
    }).observe(chart);
  }

  // --- Themen-Netz ---------------------------------------------------------------------------------
  function themennetz(D, tagById, archive) {
    const box = $("[data-themennetz]");
    if (!box || !window.ForceGraph || !D.pairs.length) return;
    const canvasBox = $("[data-net-canvas]", box), info = $("[data-net-info]", box);
    // Bei vielen Paaren nur die wiederkehrenden zeigen
    const minW = D.pairs.length > 140 ? 2 : 1;
    const pairs = D.pairs.filter((p) => p[2] >= minW);
    const used = new Set(pairs.flatMap((p) => [p[0], p[1]]));
    const nodes = D.tags.filter((t) => used.has(t.id)).map((t) => ({ id: t.id, name: t.name, kind: t.kind, n: t.n, r: 3.5 + Math.sqrt(t.n) * 1.9 }));
    const links = pairs.map(([a, b, w]) => ({ source: a, target: b, w }));
    const maxN = Math.max(...nodes.map((n) => n.n));
    let hover = null, selected = null, nb = new Set(), hiLinks = new Set();

    function focus(n) {
      nb = new Set(); hiLinks = new Set();
      if (!n) return;
      nb.add(n.id);
      links.forEach((l) => { if (l.source.id === n.id || l.target.id === n.id) { nb.add(l.source.id); nb.add(l.target.id); hiLinks.add(l); } });
    }
    function describe(n) {
      if (!n) { info.innerHTML = "Fahr über einen Punkt oder tipp ihn an."; return; }
      const partners = links.filter((l) => l.source.id === n.id || l.target.id === n.id)
        .map((l) => ({ o: l.source.id === n.id ? l.target : l.source, w: l.w })).sort((a, b) => b.w - a.w).slice(0, 8);
      info.innerHTML = `<a class="pt-net-title" href="${esc(archive([n.name]))}">${n.kind === "figur" ? "👤 " : ""}#${esc(n.name)}</a>
        <span class="faint xs">${n.n} Postings</span>
        <span class="pt-net-partners">${partners.map(({ o, w }) => `<a href="${esc(archive([n.name, o.name]))}">+ #${esc(o.name)} <b>${w}</b></a>`).join("")}</span>`;
    }

    const G = window.ForceGraph;
    const graph = (typeof G === "function" && G.prototype && G.prototype.graphData) ? new G(canvasBox) : G()(canvasBox);
    graph.backgroundColor("rgba(0,0,0,0)").nodeId("id").nodeRelSize(1).nodeVal((n) => n.r * n.r)
      .nodeCanvasObject((n, ctx, scale) => {
        if (!Number.isFinite(n.x)) return;
        const active = nb.size > 0, near = !active || nb.has(n.id);
        const col = n.kind === "figur" ? FIGURE : "#56d6c8";
        ctx.save();
        ctx.globalAlpha = near ? 1 : 0.14;
        ctx.shadowColor = col; ctx.shadowBlur = n === hover || n === selected ? 22 : 8;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 2 * Math.PI); ctx.fillStyle = col; ctx.fill();
        if (n === selected) { ctx.shadowBlur = 0; ctx.lineWidth = 2 / scale; ctx.strokeStyle = "#ffe3a8"; ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 3 / scale, 0, 2 * Math.PI); ctx.stroke(); }
        ctx.restore();
        const big = n.n >= Math.max(3, maxN * 0.08);
        if (near && (active || big || scale > 1.4)) {
          const size = Math.max(10, 12) / scale;
          ctx.save(); ctx.globalAlpha = near ? 1 : 0.2;
          ctx.font = `${big ? 650 : 520} ${size}px -apple-system, "Segoe UI", sans-serif`;
          ctx.textAlign = "center"; ctx.textBaseline = "top";
          const text = (n.kind === "figur" ? "👤 " : "#") + n.name;
          ctx.lineWidth = 3 / scale; ctx.strokeStyle = "rgba(10,12,22,.85)"; ctx.lineJoin = "round";
          ctx.strokeText(text, n.x, n.y + n.r + 2 / scale);
          ctx.fillStyle = n.kind === "figur" ? "#ffe0a6" : "#d4f6f1"; ctx.fillText(text, n.x, n.y + n.r + 2 / scale);
          ctx.restore();
        }
      })
      .nodePointerAreaPaint((n, c, ctx) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(n.r * 1.3, 6), 0, 2 * Math.PI); ctx.fill(); })
      .linkColor((l) => (hiLinks.has(l) ? "rgba(255,227,168,.85)" : nb.size ? "rgba(160,170,200,.05)" : "rgba(120,220,208,.22)"))
      .linkWidth((l) => Math.min(7, 0.6 + Math.sqrt(l.w) * 0.9) * (hiLinks.has(l) ? 1.3 : 1))
      .linkLabel((l) => `#${l.source.name} + #${l.target.name}: ${l.w}× – antippen öffnet die Postings`)
      .linkHoverPrecision(6)
      .minZoom(0.3).maxZoom(8)
      .enableZoomInteraction((ev) => ev.type !== "wheel" || ev.ctrlKey || ev.metaKey)
      .warmupTicks(100).cooldownTicks(160)
      .onNodeHover((n) => { canvasBox.style.cursor = n ? "pointer" : ""; hover = n || null; focus(hover || selected); describe(hover || selected); })
      .onNodeClick((n) => { selected = selected === n ? null : n; focus(selected); describe(selected); })
      .onLinkClick((l) => { location.href = archive([l.source.name, l.target.name]); })
      .onLinkHover((l) => { canvasBox.style.cursor = l ? "pointer" : ""; })
      .onBackgroundClick(() => { selected = null; focus(null); describe(null); });
    graph.d3Force("charge").strength((n) => -60 - n.r * 6).distanceMax(380);
    graph.d3Force("link").distance((l) => 90 - Math.min(50, l.w * 4)).strength((l) => Math.min(1, 0.15 + l.w * 0.06));
    let gNodes = [];
    const gravity = (alpha) => {
      const r = canvasBox.clientWidth / Math.max(1, canvasBox.clientHeight), sr = Math.pow(Math.min(2.2, Math.max(0.6, r)), 1.4);
      gNodes.forEach((n) => { const k = 0.04 * alpha; n.vx -= (n.x * k) / sr; n.vy -= n.y * k * sr; });
    };
    gravity.initialize = (ns) => { gNodes = ns; };
    graph.d3Force("gravity", gravity);
    const resize = () => { const r = canvasBox.getBoundingClientRect(); graph.width(r.width).height(r.height); };
    resize();
    new ResizeObserver(resize).observe(box);
    graph.graphData({ nodes, links });
    const pad = () => Math.min(60, canvasBox.clientWidth * 0.08);
    setTimeout(() => graph.zoomToFit(0, pad()), 30);
    let fitted = false;
    graph.onEngineStop(() => { if (!fitted) { fitted = true; graph.zoomToFit(600, pad()); } });
    $("[data-net-fit]", box)?.addEventListener("click", () => graph.zoomToFit(500, pad()));
    box.classList.add("is-ready");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
