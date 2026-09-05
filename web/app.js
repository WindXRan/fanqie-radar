/* 番茄指数 · 扫榜工作台：模拟人类扫榜过程（翻封面→扫书名→看在读→读简介→收藏候选→看趋势）。零依赖。 */
const state = {
  channel: "female", rank: "read",
  q: "", category: "", status: "", min_reads: 0, trope: "", sort: "reads",
};
const CAND_KEY = "fi_candidates";
let candidates = JSON.parse(localStorage.getItem(CAND_KEY) || "[]");

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtReads = n => { n = Number(n) || 0; return n >= 1e8 ? (n / 1e8).toFixed(1) + "亿" : n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n); };
const fmtWords = n => { n = Number(n) || 0; return n ? (n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n)) : ""; };

async function api(path, params = {}) {
  const qs = new URLSearchParams({ channel: state.channel, rank: state.rank, ...params }).toString();
  const r = await fetch(`/api/${path}?${qs}`);
  return r.json();
}

function coverHTML(b, cls) {
  return `<div class="cover ${cls}">` +
    (b.cover ? `<img src="${esc(b.cover)}" loading="lazy" alt="" onerror="this.parentNode.classList.add('noimg')">` : "") +
    `<span class="ph">无封面</span></div>`;
}

/* ── 主网格：书卡 ── */
function badgeHTML(b) {
  let h = "";
  if (b.status) h += b.status.includes("完结")
    ? `<span class="badge done">完结</span>` : `<span class="badge serial">连载中</span>`;
  if (b.words) h += `<span class="badge words">${fmtWords(b.words)}字</span>`;
  if (b.trope_hits >= 5) h += `<span class="badge trope">套路×${b.trope_hits}</span>`;
  return h ? `<div class="bbadges">${h}</div>` : "";
}
function cardHTML(b) {
  const starred = candidates.includes(b.book_id);
  return `<div class="bcard${starred ? " starred" : ""}" data-bid="${esc(b.book_id)}">
    ${coverHTML(b, "bcover")}
    <div class="bbody">
      <div class="btitle lnk" data-bid="${esc(b.book_id)}" title="${esc(b.title)}">${esc(b.title)}</div>
      <div class="bmeta">${esc(b.author || "—")} · ${esc(b.category || "—")}</div>
      <div><span class="breads">${fmtReads(b.reads)}<span class="u">在读</span></span></div>
      ${badgeHTML(b)}
      <div class="bintro lnk" data-bid="${esc(b.book_id)}" title="点击看完整简介">${esc(b.intro_preview || "")}</div>
    </div>
    <button class="star${starred ? " on" : ""}" data-bid="${esc(b.book_id)}" title="收藏候选">${starred ? "★" : "☆"}</button>
  </div>`;
}

async function renderGrid() {
  const params = { sort: state.sort, top: 300 };
  if (state.q) params.q = state.q;
  if (state.category) params.category = state.category;
  if (state.status) params.status = state.status;
  if (state.min_reads) params.min_reads = state.min_reads;
  if (state.trope) params.trope = state.trope;
  const d = await api("books", params);
  const grid = document.getElementById("grid");
  if (!d.count) { grid.innerHTML = `<div class="empty" style="grid-column:1/-1">没有匹配的书，放宽筛选试试</div>`; }
  else grid.innerHTML = d.items.map(cardHTML).join("");
  // 激活筛选提示条
  const bar = document.getElementById("activeBar");
  const chips = [];
  if (state.q) chips.push(`<span class="fchip" data-clear="q"><b>搜索</b>${esc(state.q)} ×</span>`);
  if (state.category) chips.push(`<span class="fchip" data-clear="category"><b>品类</b>${esc(state.category)} ×</span>`);
  if (state.status) chips.push(`<span class="fchip" data-clear="status"><b>状态</b>${state.status === "done" ? "完结" : "连载中"} ×</span>`);
  if (state.min_reads) chips.push(`<span class="fchip" data-clear="min_reads"><b>在读</b>≥${fmtReads(state.min_reads)} ×</span>`);
  if (state.trope) chips.push(`<span class="fchip" data-clear="trope"><b>套路</b>${esc(state.trope)} ×</span>`);
  bar.hidden = !chips.length;
  bar.innerHTML = chips.join("") + (chips.length ? `<span style="font-size:11px;color:var(--text-faint)">${d.count} 本</span>` : "");
}

/* ── 侧栏 ── */
async function renderHeat() {
  const d = await api("heat", { top: 12 });
  const max = Math.max(1, ...d.items.map(h => h.total_reads || 0));
  document.getElementById("heatList").innerHTML = d.items.length
    ? d.items.map(h => `
      <div class="bar-row${state.category === h.category ? " on" : ""}" data-cat="${esc(h.category)}">
        <div class="b-name" title="${esc(h.category)}">${esc(h.category)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(100 * (h.total_reads || 0) / max).toFixed(1)}%"><span class="bar-val">${fmtReads(h.total_reads)}</span></div></div>
      </div>`).join("")
    : `<div class="empty">暂无</div>`;
  // 品类下拉同步
  const sel = document.getElementById("catSel");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部品类</option>` + d.items.map(h => `<option value="${esc(h.category)}">${esc(h.category)}</option>`).join("");
  sel.value = cur;
}

async function renderTrend() {
  const d = await api("trend", { top: 30 });
  const box = document.getElementById("trendBox");
  document.getElementById("trendDate").textContent = d.available ? `${d.prev_date.slice(-4)} → ${d.now_date.slice(-4)}` : "";
  if (!d.available) { box.innerHTML = `<div class="empty">${esc(d.hint || "趋势差分需 ≥2 份快照")}</div>`; return; }
  const row = (t, cls, mark) => `<div class="t-item"><span class="t-name lnk" data-bid="${esc(t.book_id || "")}">${esc(t.title)}</span><span class="t-delta ${cls}">${mark}</span></div>`;
  box.innerHTML =
    (d.entered.length ? `<div class="t-sep">新上榜 ${d.entered.length}</div>` + d.entered.slice(0, 6).map(t => row(t, "new", "NEW")).join("") : "") +
    (d.dropped.length ? `<div class="t-sep">掉出榜 ${d.dropped.length}</div>` + d.dropped.slice(0, 4).map(t => row(t, "dn", "OUT")).join("") : "") +
    (!d.entered.length && !d.dropped.length ? `<div class="empty">两日榜单无进出</div>` : "");
}

async function renderHotwords() {
  const d = await api("hotwords", { top: 18 });
  document.getElementById("hotwords").innerHTML = d.items.length
    ? d.items.map(w => `<span class="w${state.trope === w.word ? " on" : ""}" data-trope="${esc(w.word)}">${esc(w.word)}<span class="c">${w.count}</span></span>`).join("")
    : `<div class="empty">暂无</div>`;
}

function renderCandidates() {
  const box = document.getElementById("candBox");
  if (!candidates.length) { box.innerHTML = `<div class="empty">还没有收藏，翻到心动的点 ☆</div>`; return; }
  box.innerHTML = candidates.map(bid => {
    const meta = window._candIndex?.[bid] || {};
    return `<div class="c-item"><span class="c-name lnk" data-bid="${esc(bid)}">${esc(meta.title || bid)}</span><button class="c-x" data-bid="${esc(bid)}">✕</button></div>`;
  }).join("");
}

/* ── 全量刷新 ── */
async function refresh() {
  try {
    const meta = await api("meta");
    document.getElementById("dateBadge").textContent = "数据日期 " + (meta.last_date || "—");
    await Promise.all([renderGrid(), renderHeat(), renderTrend(), renderHotwords()]);
  } catch (e) {
    document.getElementById("grid").innerHTML = `<div class="empty" style="grid-column:1/-1">接口不可用：${esc(e.message)}</div>`;
  }
}

/* ── 收藏 ── */
function toggleStar(bid) {
  const i = candidates.indexOf(bid);
  if (i >= 0) candidates.splice(i, 1); else candidates.push(bid);
  localStorage.setItem(CAND_KEY, JSON.stringify(candidates));
  document.querySelectorAll(`.bcard[data-bid="${bid}"]`).forEach(c => {
    c.classList.toggle("starred", candidates.includes(bid));
    const s = c.querySelector(".star");
    s.classList.toggle("on", candidates.includes(bid));
    s.textContent = candidates.includes(bid) ? "★" : "☆";
  });
  renderCandidates();
}

/* ── 详情弹窗 ── */
const mask = document.getElementById("modalMask");
async function openBook(bid) {
  if (!bid) return;
  try {
    const d = await fetch(`/api/book?book_id=${encodeURIComponent(bid)}`).then(r => r.json());
    if (!d.available) return;
    const m = d.item;
    document.getElementById("mTitle").textContent = m.title || "未知";
    document.getElementById("mCover").innerHTML = coverHTML(m, "lg");
    document.getElementById("mMeta").innerHTML =
      `<span><b>${esc(m.author || "—")}</b></span><span>${esc(m.category || "—")}</span>` +
      `<span>在读 <b>${fmtReads(m.reads)}</b></span>` +
      (m.words ? `<span>${fmtWords(m.words)}字</span>` : "") +
      (m.status ? `<span>${esc(m.status)}</span>` : "") +
      (m.rank_pos ? `<span>榜单第 ${m.rank_pos} 位</span>` : "");
    const intro = (m.intro || "").trim();
    const mi = document.getElementById("mIntro");
    mi.textContent = intro || "（快照中未收录简介）";
    mi.classList.toggle("empty", !intro);
    document.getElementById("mFoot").innerHTML =
      (m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">在番茄打开 ↗</a>` : "") +
      `<span>book_id: ${esc(m.book_id || bid)}</span>`;
    mask.hidden = false;
  } catch (e) { /* 静默 */ }
}

/* ── 事件 ── */
document.getElementById("segChannel").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#segChannel button").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); state.channel = b.dataset.v;
  state.category = ""; document.getElementById("catSel").value = "";
  refresh();
});
document.getElementById("segRank").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#segRank button").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); state.rank = b.dataset.v; refresh();
});
document.getElementById("segSort").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#segSort button").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); state.sort = b.dataset.v; renderGrid();
});
document.getElementById("searchBox").addEventListener("input", e => {
  state.q = e.target.value.trim(); renderGrid();
});
document.getElementById("catSel").addEventListener("change", e => {
  state.category = e.target.value; renderGrid(); renderHeat();
});
document.getElementById("chips").addEventListener("click", e => {
  const b = e.target.closest(".chip"); if (!b) return;
  const f = b.dataset.f;
  const on = b.classList.toggle("on");
  if (f === "status") state.status = on ? b.dataset.v : "";
  if (f === "min_reads") state.min_reads = on ? Number(b.dataset.v) : 0;
  // 同组互斥（完结/连载、10万/50万）
  document.querySelectorAll(`#chips .chip[data-f="${f}"]`).forEach(x => { if (x !== b) x.classList.remove("on"); });
  if (f === "status" && on) state.status = b.dataset.v;
  renderGrid();
});
document.getElementById("catSel");
document.addEventListener("click", ev => {
  const t = ev.target.closest(".lnk");
  if (t) { openBook(t.dataset.bid); return; }
  const s = ev.target.closest(".star");
  if (s) { toggleStar(s.dataset.bid); return; }
  const x = ev.target.closest(".c-x");
  if (x) { toggleStar(x.dataset.bid); return; }
  const w = ev.target.closest(".cloud .w");
  if (w) {
    const tw = w.dataset.trope;
    state.trope = state.trope === tw ? "" : tw;
    document.querySelectorAll(".cloud .w").forEach(x => x.classList.toggle("on", x.dataset.trope === state.trope));
    renderGrid(); return;
  }
  const br = ev.target.closest(".bar-row");
  if (br) {
    const cat = state.category === br.dataset.cat ? "" : br.dataset.cat;
    state.category = cat;
    document.getElementById("catSel").value = cat;
    renderGrid(); renderHeat(); return;
  }
  const fc = ev.target.closest(".fchip");
  if (fc) {
    const k = fc.dataset.clear;
    state[k] = k === "min_reads" ? 0 : "";
    document.querySelectorAll(`#chips .chip[data-f="${k}"]`).forEach(x => x.classList.remove("on"));
    if (k === "category") document.getElementById("catSel").value = "";
    renderGrid(); if (k === "category") renderHeat();
    return;
  }
  if (ev.target === mask || ev.target.id === "mClose") mask.hidden = true;
});
document.addEventListener("keydown", e => { if (e.key === "Escape") mask.hidden = true; });

/* 启动 */
(async () => {
  // 候选清单索引（书名回显用，惰性）
  try {
    const d = await api("books", { top: 500 });
    window._candIndex = {};
    d.items.forEach(b => window._candIndex[b.book_id] = b);
  } catch (e) { /* 忽略 */ }
  renderCandidates();
  refresh();
})();
