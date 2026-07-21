/* ChubbAgent dashboard — charts, filtering, and actions. */
(function () {
  "use strict";

  const NAVY = "#123a63";
  const STEEL = "#30628a";
  const YELLOW = "#f0c03e";

  function toast(msg) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  // --- Trend chart (dashboard) ---------------------------------------
  function initTrendChart() {
    const canvas = document.getElementById("trendChart");
    if (!canvas || !window.Chart || !window.__trend) return;
    const data = window.__trend;
    new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: data.labels.map((d) => d.slice(5)), // MM-DD
        datasets: [{
          label: "检测到的变化",
          data: data.values,
          borderColor: NAVY,
          backgroundColor: "rgba(18,58,99,0.08)",
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          pointBackgroundColor: YELLOW,
          pointBorderColor: NAVY,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#73777f", font: { size: 11 } } },
          y: {
            beginAtZero: true,
            grid: { color: "rgba(195,198,208,0.3)" },
            ticks: { color: "#73777f", font: { size: 11 }, precision: 0 },
          },
        },
      },
    });
  }

  // --- Product table filtering ---------------------------------------
  function initProductFilter() {
    const nameEl = document.getElementById("filter-name");
    const catEl = document.getElementById("filter-category");
    const compEl = document.getElementById("filter-company");
    const chanEl = document.getElementById("filter-channel");
    const countEl = document.getElementById("results-count");
    if (!nameEl) return;
    const rows = Array.from(document.querySelectorAll(".product-row"));

    function apply() {
      const q = nameEl.value.trim().toLowerCase();
      const cat = catEl.value;
      const comp = compEl.value;
      const chan = chanEl ? chanEl.value : "";
      let shown = 0;
      rows.forEach((r) => {
        const ok =
          (!q || r.dataset.name.includes(q)) &&
          (!cat || r.dataset.category === cat) &&
          (!comp || r.dataset.company === comp) &&
          (!chan || r.dataset.channel === chan);
        r.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      if (countEl) countEl.textContent = "共 " + shown + " 条结果";
    }
    [nameEl, catEl, compEl, chanEl].filter(Boolean).forEach((el) => {
      el.addEventListener("input", apply);
      el.addEventListener("change", apply);
    });

    // Prefill from ?q= (global search deep-link) and apply immediately.
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) { nameEl.value = q; apply(); }
  }
  window.__initProductFilter = initProductFilter;

  // --- Global search (top bar) ----------------------------------------
  function initGlobalSearch() {
    const input = document.getElementById("global-search");
    const panel = document.getElementById("search-results");
    if (!input || !panel) return;
    let timer = null;

    function hide() { panel.classList.add("hidden"); panel.innerHTML = ""; }

    async function run() {
      const q = input.value.trim();
      if (!q) return hide();
      try {
        const res = await fetch("/api/search?q=" + encodeURIComponent(q));
        const json = await res.json();
        if (!json.results.length) {
          panel.innerHTML = '<div class="px-4 py-3 text-sm" style="color:#73777f">未找到匹配结果</div>';
        } else {
          panel.innerHTML = json.results.map((r) =>
            `<a href="${encodeURI(r.href)}" class="flex items-center gap-2 px-4 py-2.5 hover:bg-[#f3f4f5] transition-colors">
               <span class="px-1.5 py-0.5 rounded text-[11px] font-semibold" style="background:#d3e4ff;color:#123a63">${r.type}</span>
               <span class="text-sm" style="color:#191c1d">${r.label}</span>
             </a>`).join("");
        }
        panel.classList.remove("hidden");
      } catch (e) { hide(); }
    }

    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 250); });
    input.addEventListener("focus", () => { if (input.value.trim()) run(); });
    document.addEventListener("click", (e) => {
      if (!panel.contains(e.target) && e.target !== input) hide();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hide();
      if (e.key === "Enter") { const first = panel.querySelector("a"); if (first) window.location.href = first.href; }
    });
  }

  // --- Notifications bell ----------------------------------------------
  function initNotifications() {
    const btn = document.getElementById("notif-btn");
    const panelEl = document.getElementById("notif-panel");
    const itemsEl = document.getElementById("notif-items");
    const dot = document.getElementById("notif-dot");
    if (!btn || !panelEl) return;

    async function load() {
      try {
        const res = await fetch("/api/notifications");
        const json = await res.json();
        if (json.unread > 0 && dot) dot.classList.remove("hidden");
        itemsEl.innerHTML = json.items.length
          ? json.items.map((n) =>
              `<div class="px-4 py-3 border-b" style="border-color:rgba(195,198,208,.4)">
                 <div class="flex items-start gap-2">
                   <span class="material-symbols-outlined" style="font-size:18px;color:${n.kind === "insight" ? "#c89c15" : "#30628a"}">${n.kind === "insight" ? "lightbulb" : "bolt"}</span>
                   <div class="flex-1 min-w-0">
                     <div class="text-sm font-medium" style="color:#191c1d">${n.title}</div>
                     <div class="text-xs mt-0.5 line-clamp-2" style="color:#43474e">${n.detail}</div>
                   </div>
                   ${n.time ? `<span class="text-xs whitespace-nowrap" style="color:#73777f">${n.time}</span>` : ""}
                 </div>
               </div>`).join("")
          : '<div class="px-4 py-3 text-sm" style="color:#73777f">暂无动态</div>';
      } catch (e) {
        itemsEl.innerHTML = '<div class="px-4 py-3 text-sm" style="color:#73777f">加载失败</div>';
      }
    }

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const opening = panelEl.classList.contains("hidden");
      panelEl.classList.toggle("hidden");
      if (opening) { load(); if (dot) dot.classList.add("hidden"); }
    });
    document.addEventListener("click", (e) => {
      if (!panelEl.contains(e.target) && !btn.contains(e.target)) panelEl.classList.add("hidden");
    });
    load(); // initial fetch just to light the unread dot honestly
  }

  // --- 重点关注 (key-competitor) toggle ---------------------------------
  async function toggleFocus(name, el) {
    try {
      const res = await fetch("/api/brands/" + encodeURIComponent(name) + "/focus", { method: "POST" });
      const json = await res.json();
      toast(json.is_focus ? "已标记为重点关注竞品：" + name : "已取消重点关注：" + name);
      setTimeout(() => window.location.reload(), 600);
    } catch (e) { toast("操作失败：" + e.message); }
  }
  window.__toggleFocus = toggleFocus;

  // --- Run-crawl button ----------------------------------------------
  function initRunCrawl() {
    const btn = document.getElementById("run-crawl");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const original = btn.innerHTML;
      btn.innerHTML = '<span class="material-symbols-outlined animate-spin" style="font-size:18px;">progress_activity</span>';
      toast("正在运行每日抓取…");
      try {
        const res = await fetch("/api/trigger/daily", { method: "POST" });
        const json = await res.json();
        if (json.status === "ok") {
          toast("抓取完成：检测到 " + json.events + " 处变化，正在刷新…");
          setTimeout(() => window.location.reload(), 1200);
        } else {
          toast("抓取失败：" + (json.error || "未知错误"));
          btn.disabled = false;
          btn.innerHTML = original;
        }
      } catch (e) {
        toast("请求失败：" + e.message);
        btn.disabled = false;
        btn.innerHTML = original;
      }
    });
  }

  // --- Price-changes table filtering ---------------------------------
  function initPriceChangeFilter() {
    const nameEl = document.getElementById("pc-name");
    const compEl = document.getElementById("pc-company");
    const dirEl = document.getElementById("pc-dir");
    const countEl = document.getElementById("pc-count");
    if (!nameEl) return;
    const rows = Array.from(document.querySelectorAll(".pc-row"));
    function apply() {
      const q = nameEl.value.trim().toLowerCase();
      const c = compEl.value;
      const d = dirEl.value;
      let shown = 0;
      rows.forEach((r) => {
        const ok =
          (!q || r.dataset.name.includes(q)) &&
          (!c || r.dataset.company === c) &&
          (!d || r.dataset.dir === d);
        r.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      if (countEl) countEl.textContent = "共 " + shown + " 条记录";
    }
    [nameEl, compEl, dirEl].forEach((el) => {
      el.addEventListener("input", apply);
      el.addEventListener("change", apply);
    });
  }
  window.__initPriceChangeFilter = initPriceChangeFilter;

  // --- Market-trends charts ------------------------------------------
  const PALETTE = ["#123a63", "#30628a", "#9ccbf8", "#f0c03e", "#a1d1fe",
                   "#265a81", "#c89c15", "#ba1a1a", "#73777f"];

  function initTrendsCharts() {
    if (!window.Chart || !window.__trends) return;
    const t = window.__trends;
    const noGrid = { grid: { display: false }, ticks: { color: "#73777f", font: { size: 10 } } };
    const yAxis = { beginAtZero: true, ticks: { precision: 0, color: "#73777f" },
                    grid: { color: "rgba(195,198,208,0.3)" } };

    const pd = document.getElementById("priceDirChart");
    if (pd) new Chart(pd, {
      type: "bar",
      data: { labels: t.price_direction.labels.map((d) => d.slice(5)), datasets: [
        { label: "涨价", data: t.price_direction.up, backgroundColor: STEEL, stack: "s" },
        { label: "降价", data: t.price_direction.down, backgroundColor: "#ba1a1a", stack: "s" },
      ] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        scales: { x: { stacked: true, ...noGrid }, y: { stacked: true, ...yAxis } } },
    });

    const et = document.getElementById("eventTypeChart");
    if (et) new Chart(et, {
      type: "doughnut",
      data: { labels: t.event_types.labels, datasets: [{ data: t.event_types.values, backgroundColor: PALETTE }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { font: { size: 11 } } } } },
    });

    const ca = document.getElementById("competitorChart");
    if (ca) new Chart(ca, {
      type: "bar",
      data: { labels: t.competitor_activity.labels, datasets: [{ label: "变化数", data: t.competitor_activity.values, backgroundColor: NAVY }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: yAxis, y: { grid: { display: false }, ticks: { color: "#43474e", font: { size: 11 } } } } },
    });

    const cat = document.getElementById("categoryChart");
    if (cat) new Chart(cat, {
      type: "doughnut",
      data: { labels: t.categories.labels, datasets: [{ data: t.categories.values, backgroundColor: PALETTE }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { font: { size: 11 } } } } },
    });
  }
  window.__initTrendsCharts = initTrendsCharts;

  // --- Products table sorting -----------------------------------------
  function initProductSort() {
    const tbody = document.getElementById("products-tbody");
    if (!tbody) return;
    const headers = Array.from(document.querySelectorAll("#products-table th.sortable"));
    let current = { key: null, dir: 1 };

    headers.forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.key;
        const type = th.dataset.type;
        current.dir = current.key === key ? -current.dir : 1;
        current.key = key;
        headers.forEach((h) => (h.querySelector(".sort-ind").textContent =
          h === th ? (current.dir === 1 ? "▲" : "▼") : ""));

        const rows = Array.from(tbody.querySelectorAll("tr.product-row"));
        rows.sort((a, b) => {
          const va = a.dataset[key], vb = b.dataset[key];
          if (type === "num") {
            const na = va === "" ? -Infinity : parseFloat(va);
            const nb = vb === "" ? -Infinity : parseFloat(vb);
            return (na - nb) * current.dir;
          }
          return va.localeCompare(vb, "zh") * current.dir;
        });
        rows.forEach((r) => tbody.appendChild(r));
      });
    });
  }
  window.__initProductSort = initProductSort;

  // --- Market map: capacity×price scatter + brand quadrant -------------
  function initMarketMap() {
    if (!window.Chart || !window.__marketMap) return;
    const m = window.__marketMap;

    const sc = document.getElementById("capacityScatter");
    if (sc) {
      const datasets = [];
      let i = 0;
      for (const [brand, points] of Object.entries(m.scatter)) {
        datasets.push({
          label: brand, data: points,
          backgroundColor: PALETTE[i % PALETTE.length],
          pointRadius: 5, pointHoverRadius: 7,
        });
        i++;
      }
      if (m.own_points && m.own_points.length) {
        datasets.push({
          label: "集宝 ChubbSafes", data: m.own_points,
          backgroundColor: YELLOW, borderColor: NAVY, borderWidth: 1.5,
          pointRadius: 7, pointHoverRadius: 9, pointStyle: "rectRot",
        });
      }
      new Chart(sc, {
        type: "scatter",
        data: { datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom", labels: { font: { size: 11 }, usePointStyle: true } },
            tooltip: { callbacks: { label: (ctx) =>
              `${ctx.raw.name}: ${ctx.raw.x}L / ¥${Number(ctx.raw.y).toLocaleString()}` } },
          },
          scales: {
            x: { title: { display: true, text: "容积 (L)", color: "#43474e" },
                 grid: { color: "rgba(195,198,208,0.25)" }, ticks: { color: "#73777f" } },
            y: { type: "logarithmic",
                 title: { display: true, text: "零售价 (¥)", color: "#43474e" },
                 grid: { color: "rgba(195,198,208,0.25)" },
                 ticks: { color: "#73777f", callback: (v) => "¥" + Number(v).toLocaleString() } },
          },
        },
      });
    }

    const qc = document.getElementById("quadChart");
    if (qc && m.quad && m.quad.length) {
      const compPts = m.quad.filter((q) => !q.own);
      const ownPts = m.quad.filter((q) => q.own);
      const toPoint = (q) => ({ x: q.avg_price, y: q.avg_score, r: Math.min(6 + q.count, 22), brand: q.brand, count: q.count });
      // Quadrant midlines at the median price / score.
      const scores = m.quad.map((q) => q.avg_score);
      const midY = scores.length ? (Math.min(...scores) + Math.max(...scores)) / 2 : 3;
      new Chart(qc, {
        type: "bubble",
        data: { datasets: [
          { label: "竞争对手", data: compPts.map(toPoint), backgroundColor: "rgba(48,98,138,0.55)", borderColor: STEEL },
          { label: "集宝", data: ownPts.map(toPoint), backgroundColor: "rgba(240,192,62,0.8)", borderColor: NAVY, borderWidth: 1.5 },
        ] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom", labels: { font: { size: 11 } } },
            tooltip: { callbacks: { label: (ctx) =>
              `${ctx.raw.brand}: 均价 ¥${Number(ctx.raw.x).toLocaleString()} · 防盗分 ${ctx.raw.y} · ${ctx.raw.count} 款` } },
          },
          scales: {
            x: { type: "logarithmic",
                 title: { display: true, text: "品牌均价 (¥)", color: "#43474e" },
                 grid: { color: "rgba(195,198,208,0.25)" },
                 ticks: { color: "#73777f", callback: (v) => "¥" + Number(v).toLocaleString() } },
            y: { title: { display: true, text: "防盗等级分（均值）", color: "#43474e" },
                 min: 0, suggestedMax: Math.max(6, midY * 2),
                 grid: { color: "rgba(195,198,208,0.25)" }, ticks: { color: "#73777f" } },
          },
        },
      });
    }
  }
  window.__initMarketMap = initMarketMap;

  // --- Value leaderboard: avg price by brand (集宝 highlighted) ---------
  function initLeaderboard() {
    const el = document.getElementById("avgPriceChart");
    if (!el || !window.Chart || !window.__leaderboard) return;
    const rows = window.__leaderboard.rows || [];
    if (!rows.length) return;
    new Chart(el, {
      type: "bar",
      data: {
        labels: rows.map((r) => r.brand),
        datasets: [{
          label: "均价 (¥)",
          data: rows.map((r) => r.avg_price),
          backgroundColor: rows.map((r) => (r.is_own ? YELLOW : STEEL)),
          borderColor: rows.map((r) => (r.is_own ? NAVY : STEEL)),
          borderWidth: rows.map((r) => (r.is_own ? 2 : 0)),
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => {
            const r = rows[ctx.dataIndex];
            const sec = r.avg_sec != null ? ` · 防盗分 ${r.avg_sec}` : "";
            return `均价 ¥${Number(r.avg_price).toLocaleString()}（${r.count} 款${sec}）`;
          } } },
        },
        scales: {
          x: { type: "logarithmic", beginAtZero: false,
               ticks: { color: "#73777f", callback: (v) => "¥" + Number(v).toLocaleString() },
               grid: { color: "rgba(195,198,208,0.25)" } },
          y: { grid: { display: false }, ticks: { color: "#43474e", font: { size: 11 } } },
        },
      },
    });
  }
  window.__initLeaderboard = initLeaderboard;

  document.addEventListener("DOMContentLoaded", function () {
    initTrendChart();
    initProductFilter();
    initPriceChangeFilter();
    initProductSort();
    initRunCrawl();
    initGlobalSearch();
    initNotifications();
  });
})();

// ======================================================================
// Research-agent console — shared across the hub + every feature sub-page.
// Auto-initializes wherever an #agent-console element is present.
// ======================================================================
(function () {
  const WF = {ingest: "文档摄取", research: "品牌深挖",
              enrich: "竞品信息自动化搜集", sentiment: "舆情分析"};
  const NODE_COLOR = {核查: "#f0c03e", 应用: "#a1d1fe"};
  let currentRun = null, pollTimer = null, stream = null, wfFilter = null;

  const $ = (id) => document.getElementById(id);

  window.agentStart = async function (params) {
    try {
      const res = await fetch("/api/agent/start", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(params),
      });
      const json = await res.json();
      if (json.error) { alert(json.error); return; }
      selectRun(json.run_id);
      loadRuns();
    } catch (e) { alert("启动失败：" + e.message); }
  };

  window.loadRuns = async function () {
    const list = $("run-list");
    if (!list) return;
    const json = await (await fetch("/api/agent/runs")).json();
    let runs = json.runs || [];
    if (wfFilter) runs = runs.filter((r) => r.workflow === wfFilter);
    if (!runs.length) {
      list.innerHTML = '<p class="px-lg py-md text-body-sm" style="color:#73777f">暂无运行记录。</p>';
      return;
    }
    const stColor = {running: "#c89c15", done: "#1b5e20", failed: "#93000a"};
    list.innerHTML = runs.map((r) =>
      `<div onclick="selectRun(${r.id})" class="px-lg py-sm cursor-pointer hover:bg-[#f3f4f5] ${currentRun === r.id ? "bg-[#e7f0fa]" : ""}">
         <div class="flex items-center justify-between">
           <span class="text-sm font-medium" style="color:#191c1d">#${r.id} ${WF[r.workflow] || r.workflow}</span>
           <span class="text-xs font-semibold" style="color:${stColor[r.status] || "#43474e"}">${r.status}</span>
         </div>
         <div class="text-xs mt-0.5 truncate" style="color:#73777f">${r.goal} · ¥${r.cost_cny}${r.facts_pending ? " · 待审 " + r.facts_pending : ""}</div>
       </div>`).join("");
  };

  function stepLine(s) {
    return `<div><span style="color:rgba(240,241,242,.45)">${s.ts}</span> <span style="color:${NODE_COLOR[s.node] || "#9ccbf8"}">[${s.node}]</span> <span style="color:#f0f1f2">${s.message}</span>${s.detail ? ` <span style="color:rgba(240,241,242,.4)">— ${s.detail}</span>` : ""}</div>`;
  }
  function setStatusChip(status) {
    const st = $("run-status");
    if (!st) return;
    st.textContent = `#${currentRun} · ${status}` + (stream ? " · SSE" : "");
    st.style.background = status === "running" ? "#ffdf95" : (status === "done" ? "#c8e6c9" : "#ffdad6");
  }
  function setMeta(run) {
    const m = $("run-meta");
    if (m) m.textContent = `迭代 ${run.iterations} · tokens ${run.tokens_in}/${run.tokens_out} · 成本 ≈¥${run.cost_cny}` + (run.error ? ` · 错误：${run.error}` : "");
  }

  window.selectRun = function (id) {
    currentRun = id;
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (stream) { stream.close(); stream = null; }
    poll().then((run) => { if (run && run.status === "running") openStream(id); });
  };

  function openStream(id) {
    const log = $("agent-log");
    if (!window.EventSource || !log) { pollTimer = setInterval(poll, 2000); return; }
    stream = new EventSource(`/api/agent/runs/${id}/stream`);
    stream.addEventListener("step", (e) => {
      if (log.firstChild && log.firstChild.dataset && log.firstChild.dataset.placeholder) log.innerHTML = "";
      log.insertAdjacentHTML("beforeend", stepLine(JSON.parse(e.data)));
      log.scrollTop = log.scrollHeight;
    });
    stream.addEventListener("status", (e) => { const r = JSON.parse(e.data); setStatusChip(r.status); setMeta(r); });
    stream.addEventListener("done", () => { stream.close(); stream = null; poll(); loadRuns(); });
    stream.onerror = () => { if (stream) { stream.close(); stream = null; } if (!pollTimer) pollTimer = setInterval(poll, 2000); };
    setStatusChip("running");
  }

  async function poll() {
    if (!currentRun) return null;
    const json = await (await fetch("/api/agent/runs/" + currentRun)).json();
    if (json.error) return null;
    const run = json.run;
    setStatusChip(run.status);
    const log = $("agent-log");
    if (log) {
      log.innerHTML = json.steps.map(stepLine).join("")
        || '<div data-placeholder="1" style="color:rgba(240,241,242,.5)">等待第一条日志…</div>';
      log.scrollTop = log.scrollHeight;
    }
    setMeta(run);
    const resultCard = $("result-card");
    if (resultCard) {
      if (run.result_md) {
        resultCard.classList.remove("hidden");
        $("agent-result").innerHTML = window.marked ? marked.parse(run.result_md) : run.result_md;
      } else resultCard.classList.add("hidden");
    }
    const factsCard = $("facts-card");
    if (factsCard) {
      if (json.facts.length) {
        factsCard.classList.remove("hidden");
        const stChip = {pending: ["待确认", "#ffdf95", "#251a00"], verified: ["自动通过", "#c8e6c9", "#1b5e20"],
                        applied: ["已采纳", "#cde5ff", "#104a71"], rejected: ["已驳回", "#ffdad6", "#93000a"]};
        $("facts-list").innerHTML = json.facts.map((f) => {
          const [label, bg, fg] = stChip[f.status] || [f.status, "#edeeef", "#43474e"];
          const srcs = (f.sources || []).map((s) => s.startsWith("http")
            ? `<a href="${s}" target="_blank" class="underline">${s.slice(0, 60)}</a>` : s).join("、");
          const actions = f.status === "pending"
            ? `<div class="flex gap-2 mt-1">
                 <button onclick="reviewFact(${f.id}, true)" class="px-2 py-1 rounded text-xs font-semibold" style="background:#123a63;color:#fff">采纳</button>
                 <button onclick="reviewFact(${f.id}, false)" class="px-2 py-1 rounded text-xs font-semibold" style="background:#ffdad6;color:#93000a">驳回</button>
               </div>` : (f.review_note ? `<div class="text-xs mt-1" style="color:#73777f">${f.review_note}</div>` : "");
          return `<div class="px-lg py-sm">
                    <div class="flex items-start justify-between gap-2">
                      <div class="text-sm" style="color:#191c1d">${f.claim}</div>
                      <span class="px-1.5 py-0.5 rounded text-[11px] font-semibold whitespace-nowrap" style="background:${bg};color:${fg}">${label}</span>
                    </div>
                    <div class="text-xs mt-0.5" style="color:#73777f">置信 ${f.confidence} · 来源：${srcs || "—"}</div>
                    ${actions}
                  </div>`;
        }).join("");
      } else factsCard.classList.add("hidden");
    }
    if (run.status !== "running" && pollTimer) { clearInterval(pollTimer); pollTimer = null; loadRuns(); }
    return run;
  }

  window.reviewFact = async function (id, accept) {
    const note = accept ? "" : (prompt("驳回原因（可选）：") || "");
    const res = await fetch(`/api/agent/facts/${id}/review`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({accept, note}),
    });
    const json = await res.json();
    if (json.error) alert(json.error);
    poll();
  };

  document.addEventListener("DOMContentLoaded", function () {
    const console_ = $("agent-console");
    if (!console_) return;
    wfFilter = console_.dataset.workflow || null;
    loadRuns();
    const wanted = parseInt(new URLSearchParams(location.search).get("run"), 10);
    if (wanted) selectRun(wanted);
  });
})();
