/* 番茄指数看板前端：拉 /api/* 并渲染。零依赖、无框架。 */
const state = { channel: "female", rank: "read" };

const DIM_LABELS = { s_done: "完结", s_words: "体量", s_reads: "热度", s_heat: "吸量", s_trope: "套路", s_gf: "金指" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtReads(n) {
  n = Number(n) || 0;
  if (n >= 1e8) return (n / 1e8).toFixed(1) + "亿";
  if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
  return String(n);
}
function fmtWords(n) {
  n = Number(n) || 0;
  if (!n) return "—";
  return n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n);
}
async function api(path, params = {}) {
  const qs = new URLSearchParams({ channel: state.channel, rank: state.rank, ...params }).toString();
  const r = await fetch(`/api/${path}?${qs}`);
  return r.json();
}
function ring(score) {
  const r = 24, c = 2 * Math.PI * r, off = c * (1 - score / 100);
  return `<svg class="ring" viewBox="0 0 56 56">
    <circle class="track" cx="28" cy="28" r="${r}"></circle>
    <circle class="prog" cx="28" cy="28" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 28 28)"></circle>
    <text class="num" x="28" y="28">${Math.round(score)}</text></svg>`;
}
function dimsHTML(b) {
  const bd = b.breakdown || {};
  return `<div class="dims">` + Object.keys(DIM_LABELS).map(k => {
    const v = Math.min(100, Number(bd[k] || 0));
    return `<div class="dim"><span class="dl">${DIM_LABELS[k]}</span><span class="dt"><span class="df" style="width:${v}%"></span></span></div>`;
  }).join("") + `</div>`;
}
function tagsHTML(b) {
  let t = "";
  if (b.trope_hits) t += `<span class="tag">套路×${b.trope_hits}</span>`;
  if (b.gf_hits) t += `<span class="tag gf">金指×${b.gf_hits}</span>`;
  return t ? `<div class="tags">${t}</div>` : "";
}

async function render() {
  let meta, score, heat, trend, hot, ranks;
  try {
    [meta, score, heat, trend, hot, ranks] = await Promise.all([
      api("meta"), api("score", { top: 500 }), api("heat", { top: 15 }),
      api("trend", { top: 30 }), api("hotwords", { top: 24 }), api("ranks", { top: 500 }),
    ]);
  } catch (e) {
    document.getElementById("kpis").innerHTML = `<div class="empty">数据接口不可用：${esc(e.message)}</div>`;
    return;
  }

  // Header 日期
  document.getElementById("dateBadge").textContent = "数据日期 " + (meta.last_date || "—");

  // KPI
  const topBook = (score.items && score.items[0]) || null;
  const topHeat = (heat.items && heat.items[0]) || null;
  document.getElementById("kpis").innerHTML = `
    <div class="kpi"><div class="k-label">快照数量</div><div class="k-val">${meta.snapshots}</div><div class="k-sub">本地快照文件</div></div>
    <div class="kpi"><div class="k-label">书目总数</div><div class="k-val">${meta.books}</div><div class="k-sub">book_id 可寻址 ${meta.with_book_id}</div></div>
    <div class="kpi"><div class="k-label">最高分书</div><div class="k-val" style="font-size:18px">${topBook ? esc(topBook.title) : "—"}</div><div class="k-sub">评分 ${topBook ? topBook.score : "—"}</div></div>
    <div class="kpi"><div class="k-label">最强吸量题材</div><div class="k-val" style="font-size:18px">${topHeat ? esc(topHeat.category) : "—"}</div><div class="k-sub">${topHeat ? fmtReads(topHeat.total_reads) + " 在读" : ""}</div></div>`;

  // 题材热度
  const maxH = Math.max(1, ...heat.items.map(h => h.total_reads || 0));
  document.getElementById("heatList").innerHTML = heat.items.length
    ? heat.items.map(h => `
      <div class="bar-row">
        <div class="b-name" title="${esc(h.category)}">${esc(h.category)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(100 * (h.total_reads || 0) / maxH).toFixed(1)}%"><span class="bar-val">${fmtReads(h.total_reads)}</span></div></div>
      </div>`).join("")
    : `<div class="empty">暂无数据</div>`;

  // 评分 Top
  const top = (score.items || []).slice(0, 10);
  document.getElementById("scoreList").innerHTML = top.length
    ? top.map(b => `
      <div class="score-card">
        ${ring(b.score)}
        <div class="sc-body">
          <div class="sc-title" title="${esc(b.title)}">${esc(b.title)}</div>
          <div class="sc-meta"><b>${esc(b.author || "—")}</b> · ${esc(b.category || "—")} · ${b.status === "已完结" ? "完结" : "连载"} · ${fmtWords(b.words)}字</div>
          ${dimsHTML(b)}
          ${tagsHTML(b)}
        </div>
      </div>`).join("")
    : `<div class="empty">暂无评分数据</div>`;

  // 趋势
  const td = document.getElementById("trendDate");
  if (trend.available) {
    td.textContent = `${trend.prev_date} → ${trend.now_date}`;
    document.getElementById("trendEntered").innerHTML = (trend.entered || []).length
      ? trend.entered.map((b, i) => `<div class="t-item"><span class="t-rank">${i + 1}</span><span class="t-name" title="${esc(b.title)}">${esc(b.title)}</span><span class="t-delta new">NEW</span></div>`).join("")
      : `<div class="empty">无新上榜</div>`;
    document.getElementById("trendDropped").innerHTML = (trend.dropped || []).length
      ? trend.dropped.map((b, i) => `<div class="t-item"><span class="t-rank">${i + 1}</span><span class="t-name" title="${esc(b.title)}">${esc(b.title)}</span><span class="t-delta dn">OUT</span></div>`).join("")
      : `<div class="empty">无掉榜</div>`;
  } else {
    td.textContent = "";
    const msg = `<div class="empty">${esc(trend.hint || "趋势差分需 ≥2 份快照")}</div>`;
    document.getElementById("trendEntered").innerHTML = msg;
    document.getElementById("trendDropped").innerHTML = msg;
  }

  // 热词
  document.getElementById("hotwords").innerHTML = (hot.items || []).length
    ? hot.items.map(w => `<span class="w">${esc(w.word)}<span class="c">${w.count}</span></span>`).join("")
    : `<div class="empty">暂无</div>`;

  // 明细表（合并评分）
  const smap = {};
  (score.items || []).forEach(b => { if (b.book_id) smap[b.book_id] = b.score; });
  const rows = ranks.items || [];
  document.getElementById("tblCount").textContent = rows.length + " 本";
  document.getElementById("tblBody").innerHTML = rows.length
    ? rows.map(b => {
        const sc = b.book_id && smap[b.book_id] != null ? smap[b.book_id] : "—";
        const stCls = b.status === "已完结" ? "done" : "ing";
        const stTxt = b.status === "已完结" ? "完结" : "连载";
        return `<tr><td>${esc(b.title)}</td><td>${esc(b.author || "—")}</td><td>${esc(b.category || "—")}</td>
          <td>${fmtReads(b.reads)}</td><td><span class="st ${stCls}">${stTxt}</span></td>
          <td>${fmtWords(b.words)}</td><td>${sc}</td></tr>`;
      }).join("")
    : `<tr><td colspan="7" class="empty">暂无数据</td></tr>`;
}

/* 控制切换 */
function bindSeg(id, key) {
  const seg = document.getElementById(id);
  seg.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach(b => b.classList.remove("on"));
      btn.classList.add("on");
      state[key] = btn.dataset.v;
      render();
    });
  });
}
bindSeg("segChannel", "channel");
bindSeg("segRank", "rank");
render();
