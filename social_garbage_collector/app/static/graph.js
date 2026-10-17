/* TrashTwitter – Netzwerk (0.18)
 *
 * Zeichnet das Archiv als Kraft-Graph (force-graph, Canvas). Der Server liefert
 * Postings mit ihren Verbindungen; hier wird je nach Auswahl zusammengefasst:
 *   ohne Postings:  Person – Tag (Linie so dick wie die Zahl der Postings),
 *                   Liste – Person, Recherche – Person, Tag – Oberbegriff
 *   mit Postings:   Posting – Person / Tag / Liste, Recherche – Posting
 * Personen sind nie direkt verbunden – sie begegnen sich ueber Themen.
 */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const COLOR = {
    person: "#f3efe6",
    tag: "#56d6c8",
    group: "#2bb5a8",
    list: "#f6b94a",
    research: { widerspruch: "#ff7b54", fakt: "#5fd08f", hintergrund: "#7fa8ff" },
    post: { x: "#a7b0c4", bluesky: "#4f9dff" },
    heart: "#ff4f8e",
  };
  const TYPE_LABEL = { person: "Person", tag: "Tag", group: "Oberbegriff", list: "Liste", research: "Recherche", post: "Posting" };
  const store = {
    get(k, d) { try { const v = localStorage.getItem("tt.graph." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("tt.graph." + k, JSON.stringify(v)); } catch (e) { /* egal */ } },
  };
  const colorOf = (n) => n.type === "research" ? (COLOR.research[n.kind] || COLOR.research.hintergrund)
    : n.type === "post" ? (n.hearts ? COLOR.heart : (COLOR.post[n.platform] || COLOR.post.x)) : COLOR[n.type];

  function initGraph(stage) {
    if (!window.ForceGraph) return;
    const local = stage.dataset.local === "1";
    const canvasBox = $("[data-graph-canvas]", stage);
    const panel = $("[data-graph-panel]", stage);
    const state = {
      showPosts: local ? false : store.get("posts", false),
      hidden: new Set(local ? [] : store.get("hidden", [])),
      from: null, to: null,
      hover: null, selected: null, onlyNeighborhood: false,
      neighbors: new Set(), hiLinks: new Set(),
    };
    let raw = null, graph = null, data = { nodes: [], links: [] }, firstFit = true, quickFit = false;
    const images = new Map();

    function img(url) {
      if (!url) return null;
      let im = images.get(url);
      if (!im) {
        im = new Image();
        im.decoding = "async";
        im.onload = () => graph && graph.d3ReheatSimulation && redraw();
        im.src = url;
        images.set(url, im);
      }
      return im.complete && im.naturalWidth ? im : null;
    }
    const redraw = () => { if (graph) { const z = graph.zoom(); graph.zoom(z * 1.00001, 0); } };

    // --- Daten fuer die aktuelle Auswahl zusammenstellen ------------------------------------------
    function build() {
      const byId = new Map(raw.nodes.map((n) => [n.id, n]));
      const inYears = (n) => n.type !== "post" || !n.year || ((state.from == null || n.year >= state.from) && (state.to == null || n.year <= state.to));
      const posts = new Set(raw.nodes.filter((n) => n.type === "post" && inYears(n)).map((n) => n.id));
      const keepType = (t) => !state.hidden.has(t === "group" ? "tag" : t);
      const links = [];
      const add = (s, t, kind, w = 1) => links.push({ source: s, target: t, kind, w });
      const L = (kind) => raw.links.filter((l) => l.kind === kind);

      if (state.showPosts) {
        for (const l of raw.links) {
          const s = l.source, t = l.target;
          if (s.startsWith("t") && !posts.has(s)) continue;
          if (t.startsWith("t") && !posts.has(t)) continue;
          add(s, t, l.kind);
        }
      } else {
        // Person – Tag und Liste – Person ueber die Postings zusammenfassen
        const author = new Map(L("post-person").map((l) => [l.source, l.target]));
        const pt = new Map(), lp = new Map();
        for (const l of L("post-tag")) {
          if (!posts.has(l.source)) continue;
          const key = author.get(l.source) + "|" + l.target;
          pt.set(key, (pt.get(key) || 0) + 1);
        }
        for (const l of L("post-list")) {
          if (!posts.has(l.source)) continue;
          const key = l.target + "|" + author.get(l.source);
          lp.set(key, (lp.get(key) || 0) + 1);
        }
        for (const [k, w] of pt) { const [p, g] = k.split("|"); add(p, g, "person-tag", w); }
        for (const [k, w] of lp) { const [l, p] = k.split("|"); add(l, p, "list-person", w); }
        for (const l of L("research-person")) add(l.source, l.target, "research-person");
        for (const l of L("tag-group")) add(l.source, l.target, "tag-group");
      }
      // Sichtbare Knoten: nach Typ gefiltert und nur, was verbunden ist (Personen auch einzeln)
      let vis = links.filter((l) => keepType(byId.get(l.source)?.type) && keepType(byId.get(l.target)?.type));
      const used = new Set();
      vis.forEach((l) => { used.add(l.source); used.add(l.target); });
      let nodes = raw.nodes.filter((n) => keepType(n.type) && (n.type === "post" ? state.showPosts && posts.has(n.id)
        : used.has(n.id) || n.type === "person"));
      // Nur Umgebung des gewaehlten Knotens (2 Schritte)
      if (state.onlyNeighborhood && state.selected) {
        const near = new Set([state.selected]);
        for (let step = 0; step < 2; step++) {
          const add2 = [];
          vis.forEach((l) => { if (near.has(l.source)) add2.push(l.target); if (near.has(l.target)) add2.push(l.source); });
          add2.forEach((x) => near.add(x));
        }
        nodes = nodes.filter((n) => near.has(n.id));
        vis = vis.filter((l) => near.has(l.source) && near.has(l.target));
      }
      const ids = new Set(nodes.map((n) => n.id));
      vis = vis.filter((l) => ids.has(l.source) && ids.has(l.target));
      // Groesse nach Gewicht der Verbindungen
      const deg = new Map();
      vis.forEach((l) => { deg.set(l.source, (deg.get(l.source) || 0) + l.w); deg.set(l.target, (deg.get(l.target) || 0) + l.w); });
      const old = new Map(data.nodes.map((n) => [n.id, n]));
      nodes = nodes.map((n) => {
        const prev = old.get(n.id);  // Positionen behalten, damit beim Umschalten nichts springt
        const d = deg.get(n.id) || 0;
        const r = n.type === "person" ? 9 + Math.min(16, Math.sqrt((n.n || 0) + d) * 2.4)
          : n.type === "group" ? 8 + Math.min(12, Math.sqrt(d) * 2.2)
          : n.type === "tag" ? 4.5 + Math.min(10, Math.sqrt(d) * 1.8)
          : n.type === "list" ? 7 + Math.min(9, Math.sqrt(d) * 1.6)
          : n.type === "research" ? 7.5
          : 2.4 + Math.min(4, (n.hearts || 0) * 1.2 + (n.comments ? 0.8 : 0));
        return Object.assign(prev || {}, n, { _r: r, _deg: d });
      });
      return { nodes, links: vis };
    }

    function linkNodes(l) {
      return [typeof l.source === "object" ? l.source.id : l.source, typeof l.target === "object" ? l.target.id : l.target];
    }
    function computeHighlight() {
      const focus = state.hover || (state.selected && data.nodes.find((n) => n.id === state.selected));
      state.neighbors = new Set();
      state.hiLinks = new Set();
      if (!focus) return;
      const fid = focus.id || focus;
      state.neighbors.add(fid);
      data.links.forEach((l) => {
        const [s, t] = linkNodes(l);
        if (s === fid || t === fid) { state.neighbors.add(s); state.neighbors.add(t); state.hiLinks.add(l); }
      });
    }

    // --- Zeichnen ------------------------------------------------------------------------------
    function shape(ctx, n, r) {
      ctx.beginPath();
      if (n.type === "list") {
        const s = r * 1.7, rr = r * 0.45;
        ctx.roundRect ? ctx.roundRect(n.x - s / 2, n.y - s / 2, s, s, rr) : ctx.rect(n.x - s / 2, n.y - s / 2, s, s);
      } else if (n.type === "research") {
        ctx.moveTo(n.x, n.y - r * 1.25); ctx.lineTo(n.x + r * 1.25, n.y); ctx.lineTo(n.x, n.y + r * 1.25); ctx.lineTo(n.x - r * 1.25, n.y); ctx.closePath();
      } else {
        ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      }
    }
    function drawNode(n, ctx, scale) {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return;  // frisch eingefuegt, noch ohne Position
      const active = state.neighbors.size > 0;
      const near = !active || state.neighbors.has(n.id);
      const isSel = n.id === state.selected || (local && raw && n.id === raw.focus), isHover = state.hover && state.hover.id === n.id;
      const r = n._r, col = colorOf(n);
      ctx.save();
      ctx.globalAlpha = near ? 1 : 0.13;
      // Leuchten
      if (near && n.type !== "post") { ctx.shadowColor = col; ctx.shadowBlur = (isSel || isHover ? 26 : 12); }
      else if (near && n.type === "post" && (n.hearts || isHover)) { ctx.shadowColor = col; ctx.shadowBlur = 10; }
      if (n.type === "person") {
        const im = img(n.img);
        ctx.beginPath(); ctx.arc(n.x, n.y, r + 1.6, 0, 2 * Math.PI); ctx.fillStyle = isSel ? "#ffd27a" : "rgba(255,255,255,.9)"; ctx.fill();
        ctx.shadowBlur = 0;
        ctx.save(); ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI); ctx.clip();
        if (im) { ctx.drawImage(im, n.x - r, n.y - r, r * 2, r * 2); }
        else {
          const g = ctx.createLinearGradient(n.x - r, n.y - r, n.x + r, n.y + r);
          const h = (Number(n.id.slice(1)) * 67) % 360;
          g.addColorStop(0, `hsl(${h} 45% 52%)`); g.addColorStop(1, `hsl(${(h + 40) % 360} 50% 34%)`);
          ctx.fillStyle = g; ctx.fillRect(n.x - r, n.y - r, r * 2, r * 2);
          ctx.fillStyle = "rgba(255,255,255,.92)"; ctx.font = `600 ${r * 1.05}px Georgia, serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText((n.label || "?").replace(/^@/, "").slice(0, 1).toUpperCase(), n.x, n.y + r * 0.06);
        }
        ctx.restore();
      } else {
        shape(ctx, n, r);
        if (n.type === "group") {
          ctx.fillStyle = "rgba(43,181,168,.22)"; ctx.fill(); ctx.lineWidth = 2 / scale + 1.2; ctx.strokeStyle = col; ctx.stroke();
          ctx.shadowBlur = 0; ctx.beginPath(); ctx.arc(n.x, n.y, r * 0.42, 0, 2 * Math.PI); ctx.fillStyle = col; ctx.fill();
        } else {
          ctx.fillStyle = col; ctx.fill();
          if (n.type === "list") { ctx.shadowBlur = 0; ctx.fillStyle = "rgba(20,16,8,.55)"; const s = r * 0.5;
            for (let i = -1; i <= 1; i++) ctx.fillRect(n.x - s, n.y + i * s * 0.62 - s * 0.13, s * 2, s * 0.26); }
        }
        if (isSel) { ctx.shadowBlur = 0; shape(ctx, n, r + 3.5 / scale + 1.5); ctx.lineWidth = 1.6 / scale + 0.6; ctx.strokeStyle = "#ffd27a"; ctx.stroke(); }
      }
      ctx.restore();
      // Beschriftung: wichtige Knoten immer, der Rest ab einer Zoomstufe oder in der Naehe
      const showLabel = isHover || isSel || (active && near && n.type !== "post") ||
        (!active && ((n.type === "person" && scale > 0.3) || (n.type === "group" && scale > 0.42) ||
          ((n.type === "list" || n.type === "research") && scale > 0.6) ||
          (n.type === "tag" && scale > 0.45 && scale * n._r > 4.4) || (n.type === "post" && scale > 3.2)));
      if (showLabel) {
        const size = Math.max(10, Math.min(14, 12 * (n.type === "person" || n.type === "group" ? 1.08 : 1))) / scale;
        let text = n.label || "";
        if (n.type === "post") text = text.length > 60 ? text.slice(0, 58) + " …" : text;
        else if (text.length > (local ? 24 : 34)) text = text.slice(0, local ? 22 : 32) + " …";
        ctx.save();
        ctx.globalAlpha = near ? 1 : 0.15;
        ctx.font = `${n.type === "person" || n.type === "group" ? 650 : 520} ${size}px -apple-system, "Segoe UI", sans-serif`;
        ctx.textAlign = "center"; ctx.textBaseline = "top";
        const y = n.y + (n.type === "research" ? r * 1.3 : r) + 3 / scale;
        ctx.lineWidth = 3.2 / scale; ctx.strokeStyle = "rgba(10,12,22,.85)"; ctx.lineJoin = "round"; ctx.strokeText(text, n.x, y);
        ctx.fillStyle = n.type === "tag" || n.type === "group" ? "#bff3ec" : n.type === "post" ? "#d9deea" : "#f6f3ec";
        ctx.fillText(text, n.x, y);
        ctx.restore();
      }
    }
    function paintArea(n, color, ctx) {
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(n._r * 1.3, 4), 0, 2 * Math.PI); ctx.fill();
    }
    const linkColor = (l) => {
      const hi = state.hiLinks.has(l), active = state.neighbors.size > 0;
      if (hi) {
        const t = typeof l.target === "object" ? l.target : null, s = typeof l.source === "object" ? l.source : null;
        const other = s && state.neighbors.size && (s.id === (state.hover?.id || state.selected)) ? t : s;
        return other ? colorOf(other) : "rgba(255,255,255,.8)";
      }
      if (active) return "rgba(160,170,200,.05)";
      return l.kind === "tag-group" ? "rgba(86,214,200,.35)" : l.kind.startsWith("research") ? "rgba(255,140,100,.32)"
        : l.kind === "list-person" || l.kind === "post-list" ? "rgba(246,185,74,.3)" : l.kind === "person-tag" ? "rgba(120,220,208,.2)" : "rgba(170,182,210,.2)";
    };
    const linkWidth = (l) => (state.hiLinks.has(l) ? 1.8 : 0.8) * (l.kind === "person-tag" ? Math.min(5, 0.6 + Math.sqrt(l.w) * 0.8) : 1);

    // --- Detailbereich -----------------------------------------------------------------------------
    function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
    function showPanel(n) {
      if (!panel) return;
      if (!n) { panel.hidden = true; return; }
      const nb = [];
      data.links.forEach((l) => {
        const [s, t] = linkNodes(l);
        if (s === n.id || t === n.id) {
          const other = data.nodes.find((x) => x.id === (s === n.id ? t : s));
          if (other) nb.push({ node: other, w: l.w || 1 });
        }
      });
      nb.sort((a, b) => b.w - a.w);
      const groups = {};
      nb.forEach(({ node, w }) => { (groups[node.type] = groups[node.type] || []).push({ node, w }); });
      const meta = n.type === "person" ? `${n.n || 0} Postings${n.sub ? " · " + esc(n.sub) : ""}`
        : n.type === "post" ? `${esc(n.date)} · ${n.platform === "bluesky" ? "Bluesky" : "X (Twitter)"}${n.hearts ? ` · ♥ ${n.hearts}` : ""}${n.comments ? ` · 💬 ${n.comments}` : ""}`
        : n.type === "research" ? esc(n.kindLabel) : "";
      const order = ["person", "group", "tag", "list", "research", "post"];
      panel.innerHTML = `
        <div class="gp-head">
          <span class="gp-type t-${n.type} ${n.kind ? "k-" + n.kind : ""}">${TYPE_LABEL[n.type]}</span>
          <button type="button" class="gp-close" data-gp-close aria-label="Schließen">×</button>
        </div>
        ${n.type === "person" && n.img ? `<img class="gp-avatar" src="${esc(n.img)}" alt="">` : ""}
        <h2 class="gp-title">${esc(n.type === "post" ? "„" + n.label + "“" : n.label)}</h2>
        ${meta ? `<p class="gp-meta">${meta}</p>` : ""}
        <div class="gp-actions">
          <a class="btn sm" href="${esc(n.url)}">Öffnen</a>
          ${local ? "" : `<button type="button" class="btn-soft sm" data-gp-near aria-pressed="${state.onlyNeighborhood}">${state.onlyNeighborhood ? "Ganzes Netz" : "Nur Umgebung"}</button>`}
        </div>
        ${order.filter((t) => groups[t]).map((t) => `
          <div class="gp-group"><span class="gp-label">${TYPE_LABEL[t]}${groups[t].length > 1 ? "" : ""} <small>${groups[t].length}</small></span>
            <div class="gp-chips">${groups[t].slice(0, 14).map(({ node, w }) =>
              `<button type="button" class="gp-chip t-${node.type}" data-gp-go="${esc(node.id)}">${esc(node.type === "post" ? node.label.slice(0, 48) + (node.label.length > 48 ? " …" : "") : node.label)}${w > 1 ? ` <small>${w}</small>` : ""}</button>`).join("")}
              ${groups[t].length > 14 ? `<span class="gp-more">+${groups[t].length - 14}</span>` : ""}</div></div>`).join("")}
      `;
      panel.hidden = false;
    }

    function select(n, center = true) {
      state.selected = n ? n.id : null;
      computeHighlight();
      showPanel(n);
      if (n && center && graph) {
        const z = Math.max(graph.zoom(), 1.5);
        // Punkt neben das Detailfeld ruecken (rechts am Desktop, unten am Handy)
        const mobile = stage.clientWidth < 700;
        const dx = panel && !panel.hidden && !mobile ? (panel.offsetWidth / 2 + 10) / z : 0;
        const dy = panel && !panel.hidden && mobile ? (stage.clientHeight * 0.28) / z : 0;
        graph.centerAt(n.x + dx, n.y + dy, 600);
        graph.zoom(z, 600);
      }
      redraw();
    }

    // --- Aufbau ------------------------------------------------------------------------------------
    function render() {
      data = build();
      if (!graph) {
        const G = window.ForceGraph;
        graph = (typeof G === "function" && G.prototype && G.prototype.graphData) ? new G(canvasBox) : G()(canvasBox);
        graph
          .backgroundColor("rgba(0,0,0,0)")
          .nodeId("id")
          .nodeRelSize(1)
          .nodeVal((n) => n._r * n._r)
          .nodeCanvasObject(drawNode)
          .nodePointerAreaPaint(paintArea)
          .linkColor(linkColor)
          .linkWidth(linkWidth)
          .linkCurvature((l) => (l.kind === "person-tag" ? 0.12 : 0))
          .linkDirectionalParticles((l) => (state.hiLinks.has(l) ? 2 : 0))
          .linkDirectionalParticleWidth(2.2)
          .linkDirectionalParticleSpeed(0.006)
          .linkDirectionalParticleColor(() => "#ffe3a8")
          .minZoom(0.2).maxZoom(9)
          // Scrollen soll die Seite bewegen; zoomen mit Pinch, Cmd/Strg + Rad oder im Vollbild
          .enableZoomInteraction((ev) => ev.type !== "wheel" || ev.ctrlKey || ev.metaKey || stage.classList.contains("is-full"))
          .warmupTicks(local ? 60 : 120)
          .cooldownTicks(200)
          .onNodeHover((n) => { canvasBox.style.cursor = n ? "pointer" : ""; state.hover = n || null; computeHighlight(); })
          .onNodeClick((n) => { if (local) { if (n.id !== raw.focus && n.url) location.href = n.url; } else select(n); })
          .onNodeRightClick((n) => { if (n?.url) location.href = n.url; })
          .onBackgroundClick(() => { if (state.onlyNeighborhood) return; select(null, false); })
          .onEngineStop(() => {
            if (firstFit) {
              firstFit = false;
              const f = stage.dataset.focus || raw.focus;
              const target = f && data.nodes.find((x) => x.id === f);
              if (target && !local) select(target);
              else graph.zoomToFit(700, fitPad());
            }
          });
        graph.d3Force("charge").strength((n) => (n.type === "post" ? -34 : n.type === "tag" ? -80 : local ? -240 : -190)).distanceMax(local ? 300 : 520);
        graph.d3Force("link").distance((l) => ({ "post-person": 34, "post-tag": 52, "post-list": 60, "tag-group": 34,
          "person-tag": 90, "list-person": 110, "research-person": 70, "research-post": 48 }[l.kind] || 60))
          .strength((l) => (l.kind === "person-tag" ? Math.min(0.9, 0.08 + l.w * 0.05) : 0.5));
        // Sanfte Schwerkraft zur Mitte: Einzelgaenger ohne Tags treiben sonst an den Rand
        let gNodes = [];
        // Nach dem Seitenverhaeltnis der Buehne ziehen: breit am Desktop, hoch am Handy
        const gravity = (alpha) => {
          const sr = Math.pow(Math.min(2.2, Math.max(0.7, canvasBox.clientWidth / Math.max(1, canvasBox.clientHeight))), 1.5);
          gNodes.forEach((n) => {
            const k = (n._deg ? 0.03 : 0.05) * alpha;
            n.vx -= n.x * k / sr; n.vy -= n.y * k * sr;
          });
        };
        gravity.initialize = (ns) => { gNodes = ns; };
        graph.d3Force("gravity", gravity);
        // Abstand halten (nur bei ueberschaubaren Netzen; O(n²))
        let cNodes = [];
        const collide = () => {
          if (cNodes.length > 450) return;
          for (let i = 0; i < cNodes.length; i++) {
            const a = cNodes[i];
            if (a.type === "post") continue;
            for (let j = i + 1; j < cNodes.length; j++) {
              const b = cNodes[j];
              if (b.type === "post") continue;
              const min = a._r + b._r + (a.type === "person" || b.type === "person" ? 14 : 8);
              let dx = b.x - a.x, dy = b.y - a.y;
              if (!Number.isFinite(dx) || !Number.isFinite(dy)) continue;
              if (!dx && !dy) { dx = (Math.random() - 0.5) * 0.1; dy = (Math.random() - 0.5) * 0.1; }
              const d = Math.hypot(dx, dy);
              if (d >= min) continue;
              const push = (min - d) / d * 0.7;
              dx *= push; dy *= push;
              if (a.fx == null) { a.x -= dx; a.y -= dy; }
              if (b.fx == null) { b.x += dx; b.y += dy; }
            }
          }
        };
        collide.initialize = (ns) => { cNodes = ns; };
        graph.d3Force("collide", collide);
        let hintTimer = 0;
        canvasBox.addEventListener("wheel", (ev) => {
          if (ev.ctrlKey || ev.metaKey || stage.classList.contains("is-full")) return;
          stage.classList.add("show-zoom-hint");
          clearTimeout(hintTimer);
          hintTimer = setTimeout(() => stage.classList.remove("show-zoom-hint"), 1400);
        }, { passive: true });
        resize();
        new ResizeObserver(resize).observe(stage);
      }
      graph.graphData(data);
      if (firstFit && !quickFit) { quickFit = true; setTimeout(() => graph.zoomToFit(0, fitPad()), 30); }  // vorberechnet: sofort passend
      if (local && raw.focus) {
        const f = data.nodes.find((x) => x.id === raw.focus);
        if (f) { f.fx = 0; f.fy = 0; }
      }
      updateCounts();
    }
    const fitPad = () => (local ? 40 : Math.round(Math.min(100, canvasBox.clientWidth * 0.1)));
    function resize() {
      if (!graph) return;
      const r = canvasBox.getBoundingClientRect();
      graph.width(r.width).height(r.height);
    }
    function updateCounts() {
      const c = {};
      data.nodes.forEach((n) => { const t = n.type === "group" ? "tag" : n.type; c[t] = (c[t] || 0) + 1; });
      $$("[data-count]", stage).forEach((el) => { el.textContent = c[el.dataset.count] || 0; });
      const st = $("[data-graph-stats]", stage);
      if (st) st.textContent = `${data.nodes.length} Knoten · ${data.links.length} Verbindungen`;
      const empty = $("[data-graph-empty]", stage);
      if (empty) empty.hidden = data.nodes.length > 0;
    }

    // --- Bedienung -----------------------------------------------------------------------------------
    stage.addEventListener("click", (ev) => {
      const t = ev.target;
      const chip = t.closest("[data-graph-type]");
      if (chip) {
        const type = chip.dataset.graphType;
        if (type === "post") { state.showPosts = !state.showPosts; store.set("posts", state.showPosts); chip.setAttribute("aria-pressed", String(state.showPosts)); }
        else { state.hidden.has(type) ? state.hidden.delete(type) : state.hidden.add(type); store.set("hidden", [...state.hidden]);
          chip.setAttribute("aria-pressed", String(!state.hidden.has(type))); }
        render(); graph.d3ReheatSimulation(); return;
      }
      if (t.closest("[data-graph-fit]")) { graph.zoomToFit(600, fitPad()); return; }
      const zb = t.closest("[data-graph-zoom]");
      if (zb) { graph.zoom(graph.zoom() * (zb.dataset.graphZoom === "in" ? 1.45 : 1 / 1.45), 300); return; }
      if (t.closest("[data-graph-full]")) {
        const on = !stage.classList.contains("is-full");
        stage.classList.toggle("is-full", on);
        document.documentElement.classList.toggle("graph-full", on);
        setTimeout(() => { resize(); graph.zoomToFit(500, fitPad()); }, 60);
        return;
      }
      if (t.closest("[data-gp-close]")) { state.onlyNeighborhood = false; select(null, false); render(); return; }
      if (t.closest("[data-gp-near]")) {
        state.onlyNeighborhood = !state.onlyNeighborhood;
        const sel = state.selected;
        render(); graph.d3ReheatSimulation();
        const n = data.nodes.find((x) => x.id === sel);
        select(n || null, false);
        setTimeout(() => graph.zoomToFit(600, fitPad()), 700);
        return;
      }
      const go = t.closest("[data-gp-go]");
      if (go) { const n = data.nodes.find((x) => x.id === go.dataset.gpGo); if (n) select(n); }
    });
    // Suche: Treffer anzeigen, Enter/Klick waehlt
    const search = $("[data-graph-search]", stage), results = $("[data-graph-results]", stage);
    if (search) {
      search.addEventListener("input", () => {
        const q = search.value.trim().toLowerCase().replace(/^[#@]/, "");
        if (!q) { results.hidden = true; return; }
        const hits = data.nodes.filter((n) => (n.label || "").toLowerCase().replace(/^[#@]/, "").includes(q))
          .sort((a, b) => (a.type === "post") - (b.type === "post") || b._deg - a._deg).slice(0, 8);
        results.innerHTML = hits.map((n) => `<button type="button" data-gp-go="${esc(n.id)}"><span class="gp-dot t-${n.type} ${n.kind ? "k-" + n.kind : ""}"></span>${esc((n.label || "").slice(0, 60))}<small>${TYPE_LABEL[n.type]}</small></button>`).join("")
          || `<span class="gr-empty">Nichts gefunden</span>`;
        results.hidden = false;
      });
      search.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); $("[data-gp-go]", results)?.click(); }
        if (ev.key === "Escape") { results.hidden = true; search.blur(); }
      });
      results.addEventListener("click", (ev) => { if (ev.target.closest("[data-gp-go]")) { results.hidden = true; search.value = ""; } });
    }
    // Zeitraum
    const yFrom = $("[data-graph-from]", stage), yTo = $("[data-graph-to]", stage);
    [yFrom, yTo].forEach((el) => el && el.addEventListener("change", () => {
      state.from = yFrom.value ? Number(yFrom.value) : null;
      state.to = yTo.value ? Number(yTo.value) : null;
      render(); graph.d3ReheatSimulation();
    }));
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && stage.classList.contains("is-full")) $("[data-graph-full]", stage)?.click();
    });

    // --- Entdeckungen: was der Graph verraet, als Liste zum Antippen ------------------------------
    function renderInsights() {
      const box = document.querySelector("[data-graph-insights]");
      if (!box || local) return;
      const byId = new Map(raw.nodes.map((n) => [n.id, n]));
      const author = new Map(raw.links.filter((l) => l.kind === "post-person").map((l) => [l.source, l.target]));
      const tagPersons = new Map(), tagged = new Set(), personTags = new Map();
      raw.links.filter((l) => l.kind === "post-tag").forEach((l) => {
        const p = author.get(l.source);
        tagged.add(l.source);
        if (!p) return;
        (tagPersons.get(l.target) || tagPersons.set(l.target, new Set()).get(l.target)).add(p);
        (personTags.get(p) || personTags.set(p, new Set()).get(p)).add(l.target);
      });
      const researched = new Set(raw.links.filter((l) => l.kind === "research-person").map((l) => l.target));
      const untagged = new Map();
      author.forEach((p, t) => { if (!tagged.has(t)) untagged.set(p, (untagged.get(p) || 0) + 1); });
      const persons = raw.nodes.filter((n) => n.type === "person");
      const cards = [
        { title: "Brückenthemen", hint: "Tags, über die die meisten Personen verbunden sind",
          items: [...tagPersons].filter(([id]) => byId.get(id)).sort((a, b) => b[1].size - a[1].size).slice(0, 6)
            .filter(([, s]) => s.size > 1).map(([id, s]) => [id, `${s.size} Personen`]) },
        { title: "Themenbreit", hint: "Personen, die zu den meisten verschiedenen Tags posten",
          items: [...personTags].sort((a, b) => b[1].size - a[1].size).slice(0, 6).map(([id, s]) => [id, `${s.size} Tags`]) },
        { title: "Ohne Recherche", hint: "Viele Postings, aber noch keine eigenen Fakten dazu",
          items: persons.filter((n) => !researched.has(n.id) && n.n > 0).sort((a, b) => b.n - a.n).slice(0, 6).map((n) => [n.id, `${n.n} Postings`]) },
        { title: "Noch einzuordnen", hint: "Postings ohne Tag – im Netz fehlen sie deshalb",
          items: [...untagged].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([id, c]) => [id, `${c} ohne Tag`]) },
      ].filter((c) => c.items.length);
      box.innerHTML = cards.map((c) => `
        <div class="gi-card"><h3>${c.title}</h3><p>${c.hint}</p><ol>
          ${c.items.map(([id, meta]) => { const n = byId.get(id); return `<li><button type="button" data-gi-go="${esc(id)}">
            <span class="gp-dot t-${n.type}"></span><span class="gi-name">${esc(n.label)}</span><small>${esc(meta)}</small></button></li>`; }).join("")}
        </ol></div>`).join("");
      box.onclick = (ev) => {
        const b = ev.target.closest("[data-gi-go]");
        if (!b) return;
        let n = data.nodes.find((x) => x.id === b.dataset.giGo);
        if (!n) { state.hidden.clear(); store.set("hidden", []); state.from = state.to = null; if (yFrom) yFrom.value = yTo.value = "";
          $$("[data-graph-type]", stage).forEach((c) => c.dataset.graphType !== "post" && c.setAttribute("aria-pressed", "true"));
          render(); n = data.nodes.find((x) => x.id === b.dataset.giGo); }
        stage.scrollIntoView({ behavior: "smooth", block: "center" });
        if (n) setTimeout(() => select(n), n.x == null ? 900 : 250);
      };
    }

    // --- Laden ---------------------------------------------------------------------------------------
    fetch(stage.dataset.src, { credentials: "same-origin" }).then((r) => r.json()).then((json) => {
      raw = json;
      if (yFrom && raw.years.length) {
        const opts = [];
        for (let y = raw.years[0]; y <= raw.years[1]; y++) opts.push(y);
        yFrom.innerHTML = `<option value="">von</option>` + opts.map((y) => `<option>${y}</option>`).join("");
        yTo.innerHTML = `<option value="">bis</option>` + opts.map((y) => `<option>${y}</option>`).join("");
      }
      $$("[data-graph-type]", stage).forEach((chip) => {
        const t = chip.dataset.graphType;
        chip.setAttribute("aria-pressed", String(t === "post" ? state.showPosts : !state.hidden.has(t)));
      });
      stage.classList.add("is-ready");
      render();
      renderInsights();
    }).catch(() => { stage.classList.add("is-error"); });
  }

  document.addEventListener("DOMContentLoaded", () => $$("[data-graph]").forEach(initGraph));
})();
