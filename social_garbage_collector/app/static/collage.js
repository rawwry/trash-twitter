/* TrashTwitter – Collage-Anordnung (0.22)
 *
 * Laeuft in templates/collage_render.html (Vorschau und Export). Feste Flaeche:
 * probiert 1..n Spalten und sucht je Spaltenzahl per Halbierung die groesste
 * Schrift (Karten) bzw. Breite (Belege), bei der alles hineinpasst. Gewinner ist
 * die Anordnung mit der groessten Schrift; bei Gleichstand die besser gefuellte.
 * Bei gleich grosser Schrift gewinnt die gleichmaessiger gefuellte Anordnung. "Endlos" (ohne Hoehe): feste Schrift,
 * Spaltenzahl nach Anzahl, Hoehe nach Inhalt.
 */
(() => {
  "use strict";
  const canvas = document.getElementById("canvas");
  const board = document.getElementById("board");
  const W = Number(canvas.dataset.w), H = Number(canvas.dataset.h);
  const shots = canvas.dataset.mode === "shots";
  const items = Array.from(board.children);
  const PAD = W * 0.045;
  const GAP = W * 0.012;
  const innerW = W - 2 * PAD;

  function available() {
    if (!H) return Infinity;
    const head = document.getElementById("head");
    const foot = document.getElementById("foot");
    const headH = head ? head.offsetHeight + parseFloat(getComputedStyle(head).marginBottom) : 0;
    const footH = foot ? foot.offsetHeight + W * 0.03 : 0;
    return H - 2 * PAD - headH - footH;
  }

  // Hoehen aller Elemente bei Spaltenbreite colW und Schrift f (ein Reflow)
  function measure(colW, f) {
    board.style.fontSize = f + "px";
    items.forEach((el) => { el.style.width = colW + "px"; });
    return items.map((el) => el.offsetHeight);
  }

  // Masonry: der Reihe nach in die kuerzeste Spalte
  function pack(heights, cols, gap) {
    const colH = new Array(cols).fill(0), place = [];
    heights.forEach((h, i) => {
      let c = 0;
      for (let k = 1; k < cols; k++) if (colH[k] < colH[c] - 0.5) c = k;
      place.push({ i, col: c, y: colH[c] });
      colH[c] += h + gap;
    });
    return { place, colH: colH.map((h) => Math.max(0, h - gap)), total: Math.max(...colH.map((h) => Math.max(0, h - gap))) };
  }

  function bestFor(cols, avail) {
    // Karten: Schrift skalieren. Belege: Breitenfaktor skalieren (Schrift fuer die Bildunterschrift folgt).
    const colFull = (innerW - (cols - 1) * GAP) / cols;
    // Karten: Zeilen nicht zu schmal - hoechstens colW/15 als Schrift (ca. 30+ Zeichen je Zeile)
    const lo0 = shots ? 0.25 : Math.min(W / 150, colFull / 15), hi0 = shots ? 1 : Math.min(W / 26, colFull / 15);
    const fontFor = (k) => (shots ? Math.max(W / 110, colFull * k / 18) : k);
    const widthFor = (k) => (shots ? colFull * k : colFull);
    const tryK = (k) => {
      const colW = widthFor(k);
      const heights = measure(colW, fontFor(k));
      return { k, colW, font: fontFor(k), heights, ...pack(heights, cols, GAP) };
    };
    let best = tryK(lo0);
    if (best.total > avail) return null;              // passt nicht mal klein
    const top = tryK(hi0);
    if (top.total <= avail) return top;
    let lo = lo0, hi = hi0;
    for (let n = 0; n < 14; n++) {
      const mid = (lo + hi) / 2;
      const r = tryK(mid);
      if (r.total <= avail) { lo = mid; best = r; } else hi = mid;
    }
    return best;
  }

  function choose() {
    const avail = available();
    const n = items.length;
    if (!n) return null;
    if (!isFinite(avail)) {
      const cols = Math.min(n, W > 3000 ? 5 : n <= 2 ? 1 : n <= 6 ? 2 : n <= 18 ? 3 : 4);
      const colW = (innerW - (cols - 1) * GAP) / cols;
      const font = shots ? W / 110 : W / 46;
      const heights = measure(colW, font);
      return { cols, colW, font, heights, ...pack(heights, cols, GAP) };
    }
    const maxCols = Math.min(n, W > H ? 9 : 7);
    let winner = null;
    for (let cols = 1; cols <= maxCols; cols++) {
      const r = bestFor(cols, avail);
      if (!r) continue;
      r.cols = cols;
      const size = shots ? r.colW : r.font;
      const fill = r.total / avail;
      // Leere Spalten (mehr Spalten als sinnvoll) sind schlecht
      const used = r.colH.filter((h) => h > 0).length;
      if (used < cols) continue;
      // Gleichmaessig gefuellte Spalten wirken ruhiger als ein ausgefranster unterer Rand
      const balance = Math.min(...r.colH) / Math.max(...r.colH);
      const score = size * (0.78 + 0.1 * fill + 0.12 * balance);
      if (!winner || score > winner.score) winner = { ...r, score };
    }
    if (!winner) {
      // Notfall: sehr viele/lange Postings - kleinste Schrift, meiste Spalten
      const cols = maxCols, colW = (innerW - (cols - 1) * GAP) / cols, font = W / 150;
      const heights = measure(colW, font);
      winner = { cols, colW, font, heights, ...pack(heights, cols, GAP) };
    }
    return winner;
  }

  function apply(r) {
    measure(r.colW, r.font);   // Endzustand herstellen
    const avail = available();
    const gridW = r.cols * r.colW + (r.cols - 1) * GAP;
    const offsetX = (innerW - gridW) / 2;
    // Oben buendig, Spalten nebeneinander; das ganze Brett wird unten mittig gesetzt
    r.place.forEach((p) => {
      const el = items[p.i];
      el.style.left = (offsetX + p.col * (r.colW + GAP)) + "px";
      el.style.top = p.y + "px";
    });
    const boardH = r.total;
    board.style.height = boardH + "px";
    if (isFinite(avail) && avail > boardH) board.style.marginTop = ((avail - boardH) / 2) + "px";
  }

  async function run() {
    try { await document.fonts.ready; } catch (e) { /* egal */ }
    await Promise.all(Array.from(document.images).map((img) => (img.complete ? null : new Promise((ok) => { img.onload = img.onerror = ok; }))));
    const r = choose();
    if (r) apply(r);
    window.__collageReady = true;
    const h = canvas.offsetHeight;
    try { window.parent.postMessage({ collage: true, height: h, cols: r ? r.cols : 0, font: r ? Math.round(r.font) : 0 }, "*"); } catch (e) { /* egal */ }
  }
  run();
})();
