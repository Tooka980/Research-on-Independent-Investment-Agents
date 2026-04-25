const { useEffect, useMemo, useRef, useState } = React;

const yen = new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY", maximumFractionDigits: 0 });
const number = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 2 });
const colors = ["#f1bf73", "#75f28a", "#69bdf8", "#a99cf7", "#6b6f68", "#ff6373", "#d7d2c4"];

const DEMO = {
  header: {
    eyebrow: "VOL.01 / PRIVATE FUND / EST.2026",
    titleLead: "投資",
    titleAccent: "Simulator",
    subtitle: "実際の市場価格をもとに、仮想資金のみで売買結果を観察するための投資シミュレーション環境",
    utc: "00:00:00",
    jst: "2026/04/24 09:00:00",
    marketLabel: "TSE 閉場中",
    marketOpen: false,
  },
  ranges: [
    ["all", "すべて"], ["10y", "10年間"], ["5y", "5年間"], ["2y", "2年間"], ["1y", "1年間"],
    ["ytd", "年初来"], ["6mo", "6ヶ月"], ["3mo", "3か月"], ["1mo", "1カ月"], ["1w", "1週間"], ["1d", "1日"],
  ].map(([key, label]) => ({ key, label })),
  selectedRange: "3mo",
  focusSymbol: "6758.T",
  tickerTape: [],
  equityCurve: [],
  sessionDelta: { value: 0, pct: 0 },
  summary: { equity: 1000000, cash: 1000000, holdingsValue: 0, totalReturn: 0, totalReturnPct: 0, openPnl: 0, realizedPnl: 0, fills: 0, positionCount: 0, principal: 1000000 },
  marketDesk: null,
  watchlist: [],
  allocation: [{ symbol: "現金", sector: "—", value: 1000000, share: 100 }],
  positions: [],
  analysis: ["データ取得を待機しています。"],
  processStatus: [],
  virtualOrderDesk: {
    mode: "simulated_virtual_only",
    safety: "実売買・外部注文・ブローカー接続はありません。",
    summary: { latestStatus: "no_virtual_order", ordersStored: 0, executionsStored: 0, decisionTracesStored: 0, statusCounts: {} },
    orders: [],
    riskChecks: [],
    executions: [],
    decisionTrace: [],
    artifactPaths: {},
  },
  organizationDesk: {
    mode: "research_simulation_only",
    safety: "No broker API, no external execution, no real-money order.",
    divisions: [],
  },
  researchTasks: [],
  evidenceSummary: {},
  evidenceRecords: [],
  decisionContexts: [],
  researchMarkdown: "",
  virtualOrderMarkdown: "",
  companies: [],
  agentRuntime: [],
  tradeProposals: [],
  tradingConsensus: {},
  runtimeQueue: [],
  sharedTradingContext: {},
};

const AGENT_DEFINITIONS = [
  ["data-agent", "Data Agent"],
  ["market-agent", "Market Agent"],
  ["news-agent", "News Agent"],
  ["analysis-agent", "Analysis Agent"],
  ["strategy-agent", "Strategy Agent"],
  ["virtual-order-agent", "Virtual Order Agent"],
  ["portfolio-agent", "Portfolio Agent"],
  ["ui-agent", "UI Agent"],
];

const AGENT_STATUS_LABELS = {
  idle: "idle",
  running: "running",
  success: "success",
  warning: "warning",
  error: "error",
  offline: "offline",
};

function clsFor(value) {
  return Number(value) >= 0 ? "positive" : "negative";
}

function formatPct(value) {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${number.format(n)}%`;
}

function formatSignedYen(value) {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : "-"}${yen.format(Math.abs(n))}`;
}

function findWatchItem(data, symbol) {
  return (data.watchlist || []).find((item) => item.symbol === symbol) || {};
}

function buildClockSnapshot() {
  const now = new Date();
  const utc = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now);
  const jst = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now).replace(/\//g, "/");
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const weekday = parts.find((part) => part.type === "weekday")?.value;
  const hour = Number(parts.find((part) => part.type === "hour")?.value || 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value || 0);
  const minutes = hour * 60 + minute;
  const weekdayOpen = !["Sat", "Sun"].includes(weekday);
  const open = weekdayOpen && ((minutes >= 9 * 60 && minutes <= 11 * 60 + 30) || (minutes >= 12 * 60 + 30 && minutes <= 15 * 60 + 30));
  return { utc, jst, marketOpen: open, marketLabel: open ? "TSE 市場中" : "TSE 閉場中" };
}

function applyStreamTick(payload, tick) {
  if (!payload || !tick) return payload;
  const driftFor = (symbol, scale = 1) => {
    const seed = symbol.split("").reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
    return Math.sin((tick + seed) * 0.41) * 0.0009 * scale;
  };
  const updateQuote = (symbol, quote = {}) => {
    const current = Number(quote.current || 0);
    if (!current) return quote;
    const drift = driftFor(symbol);
    const next = Math.max(1, current * (1 + drift));
    const previous = Number(quote.previousClose || current);
    return {
      ...quote,
      current: next,
      close: next,
      change: next - previous,
      changePct: previous ? ((next - previous) / previous) * 100 : 0,
      volume: Math.max(0, Number(quote.volume || 0) + Math.round(Math.abs(drift) * 2500000)),
    };
  };
  const updateSeries = (series = [], symbol) => series.map((item, idx) => {
    if (idx !== series.length - 1) return item;
    const next = Number(item.value || item.close || 0) * (1 + driftFor(symbol, 0.7));
    return item.value !== undefined ? { ...item, value: next } : { ...item, close: next };
  });
  const tickerTape = (payload.tickerTape || []).map((item) => {
    const quote = updateQuote(item.symbol, { current: item.current, previousClose: item.current - (item.change || 0) });
    return { ...item, current: quote.current, change: quote.change, changePct: quote.changePct, sparkline: updateSeries(item.sparkline, item.symbol) };
  });
  const watchlist = (payload.watchlist || []).map((item) => {
    const quote = updateQuote(item.symbol, { current: item.current, previousClose: item.current / (1 + Number(item.changePct || 0) / 100) });
    return { ...item, current: quote.current, changePct: quote.changePct, sparkline: updateSeries(item.sparkline, item.symbol) };
  });
  const focus = payload.marketDesk ? {
    ...payload.marketDesk,
    quote: updateQuote(payload.marketDesk.symbol, payload.marketDesk.quote),
    sparkline: updateSeries(payload.marketDesk.sparkline, payload.marketDesk.symbol),
  } : payload.marketDesk;
  return { ...payload, tickerTape, watchlist, marketDesk: focus };
}

function timeStamp() {
  return new Date().toLocaleTimeString("ja-JP", { hour12: false });
}

function agentCode(id) {
  return String(id || "agent").toUpperCase().replace(/-/g, "_");
}

function agentPlan(id, context) {
  const focus = context.focus || {};
  const quote = focus.quote || {};
  const news = (context.intelligenceFeed || [])[0]?.title || "news queue";
  const map = {
    "data-agent": [`fetch_price("${focus.symbol || "N/A"}")`, `${focus.symbol || "銘柄"} の価格 ${yen.format(quote.current || 0)} を正規化`],
    "market-agent": ["clock_tick()", `${context.clock?.marketLabel || "TSE"} / heartbeat更新`],
    "news-agent": [`fetch_news("${focus.symbol || "N/A"}")`, `ニュース確認: ${news}`],
    "analysis-agent": ["compute_full_history_analysis()", (focus.analysis || ["全期間分析を更新"])[0]],
    "strategy-agent": ["emit_strategy_output()", context.strategyOutput?.tomorrow || "次回観測点を更新"],
    "virtual-order-agent": ["process_virtual_order_queue()", context.virtualOrderDesk?.summary?.latestStatus || "仮想注文キューを確認"],
    "portfolio-agent": ["mark_to_market()", `総資産 ${yen.format(context.summary?.equity || 0)} / 含み損益 ${formatSignedYen(context.summary?.openPnl || 0)}`],
    "ui-agent": ["sync_ui_state()", `FOCUS ${focus.symbol || "N/A"} / range ${context.rangeKey}`],
  };
  const [command, message] = map[id] || ["heartbeat()", "状態を更新"];
  return { command, message };
}

function buildAgentHealthSnapshot(previousAgents, context) {
  const previous = new Map((previousAgents || []).map((agent) => [agent.id, agent]));
  const server = new Map((context.processStatus || []).map((agent) => [agent.id || agent.label, agent]));
  const stamp = timeStamp();
  const nowIso = new Date().toISOString();
  return AGENT_DEFINITIONS.map(([id, label]) => {
    const prev = previous.get(id) || {};
    const remote = server.get(id) || server.get(label) || {};
    const plan = agentPlan(id, context);
    let status = remote.status || "running";
    if (!AGENT_STATUS_LABELS[status]) status = "running";
    let warningCount = Number(remote.warningCount || prev.warningCount || 0);
    let errorCount = Number(remote.errorCount || prev.errorCount || 0);
    if (context.apiFailures >= 3 && ["data-agent", "news-agent"].includes(id)) {
      status = "warning";
      warningCount += 1;
    }
    if (context.apiFailures >= 5 && id === "data-agent") {
      status = "error";
      errorCount += 1;
    }
    if (context.fallbackMode && ["data-agent", "news-agent"].includes(id)) {
      status = "warning";
      warningCount += 1;
    }
    const apiAge = context.lastApiSuccessAt ? Math.floor((Date.now() - context.lastApiSuccessAt) / 1000) : 999;
    if (apiAge >= 60 && ["data-agent", "news-agent", "analysis-agent", "strategy-agent"].includes(id)) {
      status = "error";
      errorCount += 1;
    } else if (apiAge >= 30 && ["data-agent", "news-agent", "analysis-agent", "strategy-agent"].includes(id)) {
      status = "warning";
      warningCount += 1;
    }
    const terminalLine = `[${stamp}] ${agentCode(id)} > ${plan.command}`;
    const logLine = `[${stamp}] ${plan.message}`;
    const remoteLogs = (remote.logs || []).slice(-3);
    const remoteTerminal = (remote.terminal || []).slice(-3);
    const logs = [...(prev.logs || []), ...remoteLogs, logLine].slice(-50);
    const terminal = [...(prev.terminal || []), ...remoteTerminal, terminalLine].slice(-50);
    const successCount = Number(prev.successCount || remote.successCount || 0) + (status === "error" ? 0 : 1);
    return {
      id,
      label: remote.label || label,
      status,
      statusLabel: remote.statusLabel || status,
      lastRunAt: nowIso,
      heartbeatAt: nowIso,
      heartbeatAge: apiAge,
      latestTask: remote.latestTask || plan.command,
      successCount,
      warningCount,
      errorCount,
      progress: remote.progress || (status === "warning" ? 72 : status === "error" ? 44 : 90),
      dataSuccessRate: context.apiFailures ? Math.max(0.35, 1 - context.apiFailures * 0.1) : 1,
      newsSuccessRate: id === "news-agent" && context.fallbackMode ? 0.68 : 1,
      logs,
      terminal,
    };
  });
}

function buildAgentNarrative(focus, summary, intelligenceFeed, clock, strategyOutput, agents) {
  const q = focus?.quote || {};
  const analysis = focus?.analysis || [];
  const volumeRatio = q.averageVolume ? Number(q.volume || 0) / Number(q.averageVolume || 1) : 0;
  const pressure = Number(q.changePct || 0) >= 0 ? "買い戻しが優勢" : "売り圧力が優勢";
  const rangeLine = analysis.find((line) => line.includes("52週")) || "52週レンジ位置を再評価中";
  const news = (intelligenceFeed || [])[0]?.title || "ニュース監視を継続中";
  const marketMode = clock.marketOpen ? "市場監視モード" : "閉場後分析モード";
  const latestLog = (agents || []).flatMap((agent) => agent.logs || []).slice(-1)[0] || "Agent heartbeat更新中";
  const strategy = strategyOutput?.tomorrow || "次回観測点を更新中";
  return `${focus?.jpName || focus?.symbol}を参照中。現在時刻 JST ${clock.jst.split(" ").pop()}、${marketMode}です。\n\n短期では${pressure}で、直近変動は ${formatPct(q.changePct)}。${rangeLine}。\n\n出来高は平均比 ${volumeRatio ? number.format(volumeRatio) : "算出中"}x。最新材料は「${news}」。ポートフォリオ含み損益は ${formatSignedYen(summary.openPnl || 0)}。\n\nSTRATEGY OUTPUT: ${strategy}\n直近ログ: ${latestLog}\n\n推奨ではなく観察ポイントとして、出来高回復、寄り付きギャップ、保有根拠の変化を重点確認します。`;
}

function pathFromPoints(items, xKey, yKey, width, height, pad = 18) {
  if (!items || items.length < 2) return "";
  const values = items.map((d) => Number(d[yKey])).filter(Number.isFinite);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / Math.max(items.length - 1, 1);
  return items.map((item, idx) => {
    const y = height - pad - ((Number(item[yKey]) - min) / span) * (height - pad * 2);
    const x = pad + idx * step;
    return `${idx === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
}

function Sparkline({ data = [], color, interactive = false }) {
  const path = pathFromPoints(data, "time", "value", 150, 46, 4);
  return (
    <svg className={interactive ? "sparkline interactive" : "sparkline"} width="150" height="46" viewBox="0 0 150 46" aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="2" />
      <path d={`${path} L 146 45 L 4 45 Z`} fill={color} opacity="0.09" />
    </svg>
  );
}

function EquityChart({ data }) {
  const width = 1500;
  const height = 360;
  const path = pathFromPoints(data, "time", "equity", width, height, 36);
  return (
    <svg className="svg-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {[0,1,2,3,4].map((i) => <line key={i} x1="0" x2={width} y1={40 + i * 62} y2={40 + i * 62} stroke="rgba(255,255,255,.06)" />)}
      <path d={`${path} L ${width - 36} ${height - 28} L 36 ${height - 28} Z`} fill="rgba(241,191,115,.18)" />
      <path d={path} fill="none" stroke="#d9d5ca" strokeWidth="2.2" />
    </svg>
  );
}

function CandleChart({ candles = [] }) {
  const [hover, setHover] = useState(null);
  const width = 1300;
  const height = 560;
  const pad = { top: 34, right: 72, bottom: 76, left: 24 };
  const rows = candles.slice(-120);
  const prices = rows.flatMap((d) => [d.open, d.high, d.low, d.close].map(Number)).filter(Number.isFinite);
  const volumes = rows.map((d) => Number(d.volume || 0));
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const maxVol = Math.max(...volumes, 1);
  const plotH = height - pad.top - pad.bottom - 80;
  const step = (width - pad.left - pad.right) / Math.max(rows.length, 1);
  const body = Math.max(4, step * 0.56);
  const y = (value) => pad.top + (1 - ((Number(value) - min) / span)) * plotH;
  const volY = height - pad.bottom;
  const move = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * width;
    const idx = Math.max(0, Math.min(rows.length - 1, Math.floor((relX - pad.left) / Math.max(step, 1))));
    const row = rows[idx];
    if (!row) return;
    setHover({ x: pad.left + idx * step + step / 2, y: y(row.close), row });
  };

  return (
    <svg className="svg-chart chart-interactive" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" onMouseMove={move} onMouseLeave={() => setHover(null)}>
      {[0,1,2,3,4,5].map((i) => <line key={`h${i}`} x1={pad.left} x2={width-pad.right} y1={pad.top + i * (plotH/5)} y2={pad.top + i * (plotH/5)} stroke="rgba(255,255,255,.055)" />)}
      {[0,1,2,3,4,5,6,7,8].map((i) => <line key={`v${i}`} y1={pad.top} y2={height-pad.bottom} x1={pad.left + i * ((width-pad.left-pad.right)/8)} x2={pad.left + i * ((width-pad.left-pad.right)/8)} stroke="rgba(255,255,255,.035)" />)}
      {rows.map((d, idx) => {
        const x = pad.left + idx * step + step / 2;
        const up = Number(d.close) >= Number(d.open);
        const color = up ? "#dcd8cf" : "#e0525e";
        const top = Math.min(y(d.open), y(d.close));
        const h = Math.max(2, Math.abs(y(d.close) - y(d.open)));
        const volH = (Number(d.volume || 0) / maxVol) * 72;
        return (
          <g key={`${d.time}-${idx}`}>
            <line x1={x} x2={x} y1={y(d.high)} y2={y(d.low)} stroke={color} strokeWidth="1.2" opacity="0.8" />
            <rect x={x - body / 2} y={top} width={body} height={h} fill={color} />
            <rect x={x - body / 2} y={volY - volH} width={body} height={volH} fill={up ? "rgba(117,242,138,.18)" : "rgba(255,99,115,.20)"} />
          </g>
        );
      })}
      <line x1={pad.left} x2={width-pad.right} y1={y(rows[rows.length-1]?.close || max)} y2={y(rows[rows.length-1]?.close || max)} stroke="rgba(241,191,115,.42)" strokeDasharray="2 4" />
      <text x={width - 62} y={y(rows[rows.length-1]?.close || max) + 4} fill="#f1bf73" fontFamily="monospace" fontSize="13">{number.format(rows[rows.length-1]?.close || 0)}</text>
      <text x="30" y={height - 20} fill="#63605b" fontFamily="monospace" fontSize="13">data: yfinance / cached fallback</text>
      {hover && (
        <g className="chart-crosshair">
          <line x1={hover.x} x2={hover.x} y1={pad.top} y2={height - pad.bottom} stroke="rgba(231,231,224,.28)" strokeDasharray="3 5" />
          <line x1={pad.left} x2={width - pad.right} y1={hover.y} y2={hover.y} stroke="rgba(231,231,224,.18)" strokeDasharray="3 5" />
          <rect x={Math.min(hover.x + 12, width - 236)} y={Math.max(hover.y - 66, 24)} width="218" height="64" fill="rgba(6,7,10,.92)" stroke="rgba(231,231,224,.22)" />
          <text x={Math.min(hover.x + 24, width - 224)} y={Math.max(hover.y - 42, 48)} fill="#eeece3" fontFamily="monospace" fontSize="12">O {number.format(hover.row.open)} H {number.format(hover.row.high)}</text>
          <text x={Math.min(hover.x + 24, width - 224)} y={Math.max(hover.y - 22, 68)} fill="#9a9890" fontFamily="monospace" fontSize="12">L {number.format(hover.row.low)} C {number.format(hover.row.close)}</text>
        </g>
      )}
    </svg>
  );
}

function Donut({ rows }) {
  const [hovered, setHovered] = useState(null);
  const radius = 92;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0) || 1;
  return (
    <svg width="310" height="310" viewBox="0 0 310 310">
      <circle cx="155" cy="155" r={radius} fill="none" stroke="rgba(255,255,255,.12)" strokeWidth="34" />
      {rows.map((row, idx) => {
        const share = Number(row.value || 0) / total;
        const dash = share * circumference;
        const circle = <circle key={row.symbol} cx="155" cy="155" r={radius} fill="none" stroke={colors[idx % colors.length]} strokeWidth="34" strokeDasharray={`${dash} ${circumference - dash}`} strokeDashoffset={-offset} transform="rotate(-90 155 155)" opacity={hovered === null || hovered === idx ? "0.82" : "0.30"} onMouseEnter={() => setHovered(idx)} onMouseLeave={() => setHovered(null)} />;
        offset += dash;
        return circle;
      })}
      <text x="155" y="145" fill="#6b6862" fontFamily="monospace" fontSize="12" textAnchor="middle">TOTAL EQUITY</text>
      <text x="155" y="175" fill="#eeece3" fontFamily="monospace" fontSize="24" fontWeight="700" textAnchor="middle">{yen.format(hovered === null ? total : rows[hovered]?.value || total)}</text>
      <text x="155" y="198" fill="#6b6862" fontFamily="monospace" fontSize="12" textAnchor="middle">{hovered === null ? `${Math.max(rows.length - 1, 0)} positions` : rows[hovered]?.symbol}</text>
    </svg>
  );
}

function App() {
  const [data, setData] = useState(DEMO);
  const [focusSymbol, setFocusSymbol] = useState("6758.T");
  const [rangeKey, setRangeKey] = useState("3mo");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [equityOpen, setEquityOpen] = useState(false);
  const [positionView, setPositionView] = useState("table");
  const [agentPulse, setAgentPulse] = useState(3);
  const [clock, setClock] = useState(buildClockSnapshot());
  const [streamTick, setStreamTick] = useState(0);
  const [capitalInput, setCapitalInput] = useState("");
  const [capitalAdjustment, setCapitalAdjustment] = useState(0);
  const [lastNewsRefresh, setLastNewsRefresh] = useState(null);
  const [intelligenceItems, setIntelligenceItems] = useState([]);
  const [agents, setAgents] = useState([]);
  const [apiFailures, setApiFailures] = useState(0);
  const [fallbackMode, setFallbackMode] = useState(false);
  const [cachePreviewMode, setCachePreviewMode] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [watchlistSymbols, setWatchlistSymbols] = useState(["7203.T", "6758.T", "9984.T", "6861.T", "9983.T", "8306.T", "7974.T", "8035.T"]);
  const [confirmAction, setConfirmAction] = useState(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [restartNonce, setRestartNonce] = useState(0);
  const [organizationTab, setOrganizationTab] = useState("research");
  const [lastApiSuccessAt, setLastApiSuccessAt] = useState(Date.now());
  const newsRefreshRef = useRef(0);
  const agentContextRef = useRef({});

  useEffect(() => {
    let active = true;
    let timer = null;
    const loadDashboard = () => {
      setLoading(true);
      setAgentPulse(1);
      const watchlistParam = watchlistSymbols.join(",");
      if (cachePreviewMode) {
        setData((prev) => ({ ...DEMO, ...prev, generatedAt: new Date().toISOString() }));
        setFallbackMode(true);
        setLoading(false);
        timer = window.setTimeout(loadDashboard, 9000);
        return;
      }
      fetch(`/api/dashboard?symbol=${encodeURIComponent(focusSymbol)}&range=${encodeURIComponent(rangeKey)}&watchlist=${encodeURIComponent(watchlistParam)}`, { cache: "no-store" })
        .then((res) => res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)))
        .then((payload) => {
          if (!active) return;
          setData(payload);
          setApiFailures(0);
          setFallbackMode(false);
          setLastApiSuccessAt(Date.now());
          const now = Date.now();
          if (!newsRefreshRef.current || now - newsRefreshRef.current >= 30000) {
            newsRefreshRef.current = now;
            setIntelligenceItems(payload.intelligenceFeed || []);
            setLastNewsRefresh(new Date(now));
          }
          setLoading(false);
          timer = window.setTimeout(loadDashboard, 7000);
        })
        .catch(() => {
          if (!active) return;
          setData((prev) => ({ ...DEMO, ...prev }));
          setApiFailures((value) => {
            const next = value + 1;
            if (next >= 5) setFallbackMode(true);
            return next;
          });
          setLoading(false);
          timer = window.setTimeout(loadDashboard, 9000);
        });
    };
    loadDashboard();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [focusSymbol, rangeKey, watchlistSymbols, refreshNonce, cachePreviewMode]);

  useEffect(() => {
    let raf = 0;
    let lastSecond = "";
    const tick = () => {
      const next = buildClockSnapshot();
      if (next.jst !== lastSecond) {
        lastSecond = next.jst;
        setClock(next);
      }
      raf = window.requestAnimationFrame(tick);
    };
    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const tick = () => {
      if (cancelled) return;
      setStreamTick((value) => value + 1);
      timer = window.setTimeout(tick, 5500);
    };
    timer = window.setTimeout(tick, 5500);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const pulse = () => {
      if (cancelled) return;
      setAgentPulse((value) => Math.min(3, value + 1));
      timer = window.setTimeout(pulse, 520);
    };
    setAgentPulse(1);
    timer = window.setTimeout(pulse, 520);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [focusSymbol, rangeKey, streamTick]);

  const liveData = useMemo(() => applyStreamTick(data, streamTick), [data, streamTick]);
  const baseSummary = liveData.summary || DEMO.summary;
  const summary = useMemo(() => {
    const principal = Number(baseSummary.principal || 0) + capitalAdjustment;
    const equity = Number(baseSummary.equity || 0) + capitalAdjustment;
    const cash = Number(baseSummary.cash || 0) + capitalAdjustment;
    const totalReturn = Number(baseSummary.totalReturn || 0);
    return {
      ...baseSummary,
      equity,
      cash,
      principal,
      totalReturnPct: principal ? (totalReturn / principal) * 100 : 0,
    };
  }, [baseSummary, capitalAdjustment]);
  const allocationRows = useMemo(() => {
    const rows = (liveData.allocation || []).map((row) => ({ ...row }));
    if (capitalAdjustment) {
      const cashRow = rows.find((row) => row.symbol === "現金" || row.symbol === "Cash");
      if (cashRow) cashRow.value = Number(cashRow.value || 0) + capitalAdjustment;
      else rows.push({ symbol: "現金", sector: "—", value: capitalAdjustment, share: 0 });
    }
    const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0) || 1;
    return rows.map((row) => ({ ...row, share: (Number(row.value || 0) / total) * 100 }));
  }, [liveData.allocation, capitalAdjustment]);
  const tape = useMemo(() => [...(liveData.tickerTape || []), ...(liveData.tickerTape || [])], [liveData.tickerTape]);
  const focus = liveData.marketDesk || DEMO.marketDesk;
  const quote = focus?.quote || {};
  const header = liveData.header || DEMO.header;
  const displayedIntelligence = intelligenceItems.length ? intelligenceItems : (liveData.intelligenceFeed || []);
  const strategyOutput = liveData.strategyOutput || {};
  const virtualOrderDesk = liveData.virtualOrderDesk || DEMO.virtualOrderDesk;
  const organizationDesk = liveData.organizationDesk || DEMO.organizationDesk;
  const researchTasks = liveData.researchTasks || [];
  const evidenceSummary = liveData.evidenceSummary || {};
  const evidenceRecords = liveData.evidenceRecords || [];
  const decisionContexts = liveData.decisionContexts || [];
  const researchMarkdown = liveData.researchMarkdown || "";
  const virtualOrderMarkdown = liveData.virtualOrderMarkdown || virtualOrderDesk.markdown || "";
  const companies = liveData.companies || [];
  const agentRuntime = liveData.agentRuntime || [];
  const tradeProposals = liveData.tradeProposals || [];
  const tradingConsensus = liveData.tradingConsensus || {};
  const runtimeQueue = liveData.runtimeQueue || [];
  useEffect(() => {
    agentContextRef.current = {
      focus,
      summary,
      clock,
      rangeKey,
      processStatus: liveData.processStatus || [],
      intelligenceFeed: displayedIntelligence,
      strategyOutput,
      virtualOrderDesk,
      organizationDesk,
      evidenceSummary,
      companies,
      agentRuntime,
      tradeProposals,
      tradingConsensus,
      runtimeQueue,
      apiFailures,
      fallbackMode,
      lastApiSuccessAt,
      restartNonce,
    };
  }, [focus, summary, clock, rangeKey, liveData.processStatus, displayedIntelligence, strategyOutput, virtualOrderDesk, organizationDesk, evidenceSummary, companies, agentRuntime, tradeProposals, tradingConsensus, runtimeQueue, apiFailures, fallbackMode, lastApiSuccessAt, restartNonce]);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const heartbeat = () => {
      if (cancelled) return;
      setAgents((previous) => buildAgentHealthSnapshot(previous, agentContextRef.current || {}));
      timer = window.setTimeout(heartbeat, 1000);
    };
    heartbeat();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    setAgents([]);
  }, [restartNonce]);

  const requestConfirm = (label, action) => setConfirmAction({ label, action });
  const addWatchSymbol = () => {
    const symbol = symbolInput.trim().toUpperCase();
    if (!symbol) return;
    setWatchlistSymbols((items) => items.includes(symbol) ? items : [...items, symbol]);
    setFocusSymbol(symbol);
    setSymbolInput("");
  };
  const addCapital = () => {
    const amount = Number(String(capitalInput).replace(/[^\d.-]/g, ""));
    if (!Number.isFinite(amount) || amount <= 0) return;
    setCapitalAdjustment((value) => value + amount);
    setCapitalInput("");
  };
  const resetView = () => {
    setFocusSymbol("6758.T");
    setRangeKey("3mo");
    setEquityOpen(false);
    setPositionView("table");
  };
  const initializeSimulation = () => {
    setCapitalAdjustment(0);
    resetView();
  };
  const restartAgents = () => {
    setRestartNonce((value) => value + 1);
    setApiFailures(0);
    setFallbackMode(false);
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">{header.eyebrow}</div>
          <h1 className="title">{header.titleLead} <span>{header.titleAccent}</span></h1>
          <div className="subtitle">{header.subtitle}</div>
        </div>
        <div className="clock-panel">
          <div>UTC / {clock.utc}</div>
          <div>JST / {clock.jst}</div>
          <div className="market-pill"><span className={`market-dot ${clock.marketOpen ? "" : "closed"}`}></span>{clock.marketLabel}</div>
        </div>
      </header>

      <SimulationControlBar
        capitalInput={capitalInput}
        setCapitalInput={setCapitalInput}
        symbolInput={symbolInput}
        setSymbolInput={setSymbolInput}
        onAddCapital={() => requestConfirm("元本を追加しますか？", addCapital)}
        onAddWatch={() => requestConfirm("WATCHLISTに銘柄を追加しますか？", addWatchSymbol)}
        onResetView={() => requestConfirm("表示状態をリセットしますか？", resetView)}
        onInitialize={() => requestConfirm("シミュレーション表示を初期化しますか？", initializeSimulation)}
        onRestartAgents={() => requestConfirm("エージェントを再起動しますか？", restartAgents)}
        onRefetch={() => requestConfirm("データを再取得しますか？", () => setRefreshNonce((value) => value + 1))}
        onToggleFallback={() => requestConfirm("fallback / cache モードを切り替えますか？", () => setCachePreviewMode((value) => !value))}
        loading={loading}
        fallbackMode={fallbackMode || cachePreviewMode}
        positionView={positionView}
        setPositionView={setPositionView}
      />

      <section className="ticker">
        <div className="ticker-track">
          {tape.map((item, idx) => (
            <button className="ticker-item" key={`${item.symbol}-${idx}`} onClick={() => setFocusSymbol(item.symbol)}>
              <span className="ticker-name">{item.jpName || findWatchItem(liveData, item.symbol).jpName || item.symbol}</span>
              <span className="ticker-symbol">{item.symbol}</span>
              <span className="price">{yen.format(item.current || 0)}</span>
              <Sparkline data={item.sparkline || findWatchItem(liveData, item.symbol).sparkline || []} color={Number(item.changePct) >= 0 ? "#d8d5cc" : "#d65362"} />
              <span className={clsFor(item.changePct)}>{formatPct(item.changePct)}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="band">
        <div className="section-head">
          <div>
            <div className="section-kicker">EQUITY CURVE / SINCE INCEPTION</div>
            <div className="section-title">資産推移</div>
            <div className="subtitle">全スナップショットの時価評価</div>
          </div>
          <div className="session-delta">
            <div className="tiny-label">SESSION DELTA / セッション損益</div>
            <div className={`delta-value ${clsFor(liveData.sessionDelta?.value)}`}>{formatSignedYen(liveData.sessionDelta?.value)}</div>
            <div className={clsFor(liveData.sessionDelta?.pct)}>{formatPct(liveData.sessionDelta?.pct)}</div>
          </div>
        </div>
        <div className="equity-chart"><EquityChart data={liveData.equityCurve || []} /></div>
      </section>

      <section className="summary-grid">
        <Metric
          label="EQUITY"
          title="総資産"
          value={yen.format(summary.equity)}
          note={`現金 ${yen.format(summary.cash)} / ポジション ${yen.format(summary.holdingsValue)}`}
          expanded={equityOpen}
          onToggle={() => setEquityOpen((value) => !value)}
          detail={
            <div className="metric-detail">
              <div><span>現金</span><strong>{yen.format(summary.cash)}</strong></div>
              <div><span>株式</span><strong>{yen.format(summary.holdingsValue)}</strong></div>
              <div><span>今日</span><strong className={clsFor(liveData.sessionDelta?.value)}>{formatSignedYen(liveData.sessionDelta?.value)}</strong></div>
              <Sparkline data={(liveData.equityCurve || []).map((item) => ({ time: item.time, value: item.equity })).slice(-28)} color="#d8d5cc" interactive />
            </div>
          }
        />
        <Metric label="TOTAL RETURN" title="通算損益" value={formatSignedYen(summary.totalReturn)} note={`${formatPct(summary.totalReturnPct)} / 元本 ${yen.format(summary.principal)}`} signed={summary.totalReturn} />
        <Metric label="OPEN P&L" title="含み損益" value={formatSignedYen(summary.openPnl)} note={`保有 ${summary.positionCount} 銘柄`} signed={summary.openPnl} />
        <Metric label="REALIZED P&L" title="確定損益" value={formatSignedYen(summary.realizedPnl)} note={`${summary.fills} 約定`} signed={summary.realizedPnl} />
      </section>

      <section className="band">
        <div className="section-head">
          <div>
            <div className="section-kicker">MARKET DESK / LIVE TAPE</div>
            <div className="section-title">トレード台</div>
          </div>
          <div className="tiny-label">CLICK A TILE TO FOCUS / CANDLESTICK</div>
        </div>
        <div className="market-grid">
          <div>
            <div className="focus-head">
              <div>
                <div className="section-kicker">FOCUS / {focus?.symbol}</div>
                <div className="focus-name">{focus?.jpName}</div>
              </div>
              <div className="focus-price">
                <div className="focus-price-main">{yen.format(quote.current || 0)}</div>
                <div className={clsFor(quote.changePct)}>{formatSignedYen(quote.change)} / {formatPct(quote.changePct)}</div>
              </div>
            </div>
            <div className="range-tabs">
              {(liveData.ranges || DEMO.ranges).map((range) => (
                <button key={range.key} className={`range-tab ${range.key === rangeKey ? "active" : ""}`} onClick={() => setRangeKey(range.key)}>{range.label}</button>
              ))}
            </div>
            <div className="candle-wrap"><CandleChart candles={focus?.candles || []} /></div>
            <InfoStrip focus={focus} quote={quote} />
            <button className="detail-button" onClick={() => setDrawerOpen(true)}>詳細を見る</button>
          </div>
          <aside className="watchlist">
            <div className="section-kicker">WATCHLIST / ACTIVE UNIVERSE</div>
            <div className="watch-grid">
              {(liveData.watchlist || []).map((item) => (
                <button key={item.symbol} className={`watch-card ${item.symbol === focusSymbol ? "active" : ""}`} onClick={() => setFocusSymbol(item.symbol)}>
                  <div className="watch-top"><strong>{item.symbol}</strong><span className={clsFor(item.changePct)}>{formatPct(item.changePct)}</span></div>
                  <div className="watch-name">{item.jpName}</div>
                  <Sparkline data={item.sparkline} color={Number(item.changePct) >= 0 ? "#d8d5cc" : "#d65362"} interactive />
                  <div className="watch-price">{yen.format(item.current || 0)}</div>
                  <div className="watch-hover-detail">FOCUSへ切替 / 1カ月推移</div>
                </button>
              ))}
            </div>
          </aside>
        </div>
      </section>

      <section className="band">
        <div className="section-head">
          <div>
            <div className="section-kicker">ALLOCATION</div>
            <div className="section-title">資産配分</div>
          </div>
          <div className="tiny-label">現金 + ポジション = TOTAL EQUITY</div>
        </div>
        <div className="allocation-grid">
          <div className="donut-wrap"><Donut rows={allocationRows || []} /></div>
          <AllocationTable rows={allocationRows || []} />
        </div>
      </section>

      <section className="band">
        <div className="section-kicker">OPEN POSITIONS / LIVE BOOK</div>
        <div className="section-title">保有ポジション</div>
        <div className="view-switch">
          <button className={positionView === "table" ? "active" : ""} onClick={() => setPositionView("table")}>TABLE</button>
          <button className={positionView === "cards" ? "active" : ""} onClick={() => setPositionView("cards")}>CARDS</button>
        </div>
        {positionView === "table" ? <Positions rows={liveData.positions || []} setFocusSymbol={setFocusSymbol} /> : <PositionCards rows={liveData.positions || []} setFocusSymbol={setFocusSymbol} />}
      </section>

      <section className="band">
        <div className="section-kicker">ANALYSIS / FULL HISTORY</div>
        <div className="section-title">全期間ベース</div>
        <div className="analysis-grid">
          {(liveData.analysis || []).map((line, idx) => <div className="analysis-tile" key={idx}>{line}</div>)}
        </div>
      </section>

      <IntelligenceFeed items={displayedIntelligence} lastNewsRefresh={lastNewsRefresh} />
      <StrategyOutput output={strategyOutput} focus={focus} agents={agents} />
      <OrganizationConsole
        activeTab={organizationTab}
        setActiveTab={setOrganizationTab}
        companies={companies}
        tradeProposals={tradeProposals}
        tradingConsensus={tradingConsensus}
        runtimeQueue={runtimeQueue}
        desk={organizationDesk}
        tasks={researchTasks}
        evidenceSummary={evidenceSummary}
        evidenceRecords={evidenceRecords}
        decisionContexts={decisionContexts}
        markdown={researchMarkdown}
        virtualOrderDesk={virtualOrderDesk}
        virtualOrderMarkdown={virtualOrderMarkdown}
      />

      <AgentHealthMonitor agents={agents} agentPulse={agentPulse} />

      {drawerOpen && <DetailDrawer focus={focus} onClose={() => setDrawerOpen(false)} />}
      <AgentChatPanel focus={focus} summary={summary} intelligenceFeed={displayedIntelligence} clock={clock} strategyOutput={strategyOutput} agents={agents} />
      {confirmAction && (
        <ConfirmModal
          label={confirmAction.label}
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            confirmAction.action();
            setConfirmAction(null);
          }}
        />
      )}
      <div className="footer-spacer" />
    </main>
  );
}

function SimulationControlBar({
  capitalInput,
  setCapitalInput,
  symbolInput,
  setSymbolInput,
  onAddCapital,
  onAddWatch,
  onResetView,
  onInitialize,
  onRestartAgents,
  onRefetch,
  onToggleFallback,
  loading,
  fallbackMode,
  positionView,
  setPositionView,
}) {
  return (
    <section className="management-bar" aria-label="シミュレーション管理">
      <div className="management-state">
        <span className={`stream-dot ${loading ? "loading" : ""}`}></span>
        <span>{fallbackMode ? "FALLBACK / cache監視" : loading ? "DATA STREAM / 更新中" : "DATA STREAM / 接続中"}</span>
      </div>
      <div className="management-actions">
        <button onClick={onResetView}>表示リセット</button>
        <button onClick={onRefetch}>データ再取得</button>
        <button onClick={onRestartAgents}>エージェント再起動</button>
        <button onClick={onToggleFallback}>fallback切替</button>
        <button onClick={() => setPositionView(positionView === "table" ? "cards" : "table")}>表示モード</button>
        <label>
          <span>元本追加</span>
          <input value={capitalInput} onChange={(event) => setCapitalInput(event.target.value)} placeholder="100000" inputMode="numeric" />
        </label>
        <button onClick={onAddCapital}>反映</button>
        <label>
          <span>銘柄追加</span>
          <input value={symbolInput} onChange={(event) => setSymbolInput(event.target.value)} placeholder="7203.T" />
        </label>
        <button onClick={onAddWatch}>WATCHLIST追加</button>
        <button onClick={onInitialize}>シミュレーション初期化</button>
      </div>
    </section>
  );
}

function ConfirmModal({ label, onConfirm, onCancel }) {
  return (
    <>
      <div className="drawer-backdrop" onClick={onCancel}></div>
      <div className="confirm-modal">
        <div className="section-kicker">CONFIRM</div>
        <div className="confirm-title">{label}</div>
        <div className="confirm-actions">
          <button onClick={onCancel}>キャンセル</button>
          <button onClick={onConfirm}>実行</button>
        </div>
      </div>
    </>
  );
}

function IntelligenceFeed({ items, lastNewsRefresh }) {
  return (
    <section className="band">
      <div className="section-head">
        <div>
          <div className="section-kicker">INTELLIGENCE FEED</div>
          <div className="section-title">市場インテリジェンス</div>
        </div>
        <div className="tiny-label">NEWS / REPORTS {lastNewsRefresh ? lastNewsRefresh.toLocaleTimeString("ja-JP") : ""}</div>
      </div>
      <div className="intelligence-list">
        {(items || []).map((item, idx) => (
          <article className="feed-row" key={`${item.title}-${idx}`}>
            <div className="feed-meta">
              <span>{item.time}</span>
              <span>{item.source}</span>
              <span className={`impact impact-${String(item.impact || "low").toLowerCase()}`}>{item.impact}</span>
            </div>
            <div className="feed-title">{item.title}</div>
            <p>{item.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function StrategyOutput({ output, focus, agents }) {
  const nextTasks = (agents || []).map((agent) => agent.latestTask).filter(Boolean).slice(0, 3).join(" / ");
  const rows = [
    ["今日のまとめ", output?.summary],
    ["市場状況", output?.market],
    ["注目銘柄", output?.focus || `${focus?.symbol || ""} を監視中`],
    ["リスク評価", output?.risk],
    ["明日の観察点", output?.tomorrow],
    ["次に実行予定", nextTasks],
  ];
  return (
    <section className="band">
      <div className="section-kicker">STRATEGY OUTPUT</div>
      <div className="section-title">戦略出力</div>
      <div className="strategy-grid">
        {rows.map(([label, value]) => (
          <div className="strategy-line" key={label}>
            <div className="tiny-label">{label}</div>
            <div>{value || "分析を更新中です。"}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function OrganizationConsole({
  activeTab,
  setActiveTab,
  companies,
  tradeProposals,
  tradingConsensus,
  runtimeQueue,
  desk,
  tasks,
  evidenceSummary,
  evidenceRecords,
  decisionContexts,
  markdown,
  virtualOrderDesk,
  virtualOrderMarkdown,
}) {
  const tabs = [
    ["research", "調査部門", "Research"],
    ["analysis", "分析部門", "Analysis"],
    ["strategy", "意思決定支援部門", "Strategy"],
    ["virtual", "仮想注文管理部門", "Virtual Orders"],
  ];
  const companyFilter = {
    research: ["market-intelligence", "research"],
    analysis: ["quant-analysis"],
    strategy: ["strategy", "operations"],
    virtual: ["virtual-trading"],
  };
  const filteredCompanies = (companies || []).filter((company) => (companyFilter[activeTab] || []).includes(company.id));
  return (
    <section className="band organization-console">
      <div className="section-head">
        <div>
          <div className="section-kicker">ORGANIZATION CONSOLE</div>
          <div className="section-title">部門別エージェント運用</div>
        </div>
        <div className="view-switch">
          {tabs.map(([key, labelJa, labelEn]) => (
            <button key={key} className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>
              {labelJa}<span className="tab-sub">{labelEn}</span>
            </button>
          ))}
        </div>
      </div>
      {activeTab === "research" && (
        <ResearchOrganizationDesk
          desk={desk}
          tasks={tasks}
          evidenceSummary={evidenceSummary}
          evidenceRecords={evidenceRecords}
          decisionContexts={decisionContexts}
          markdown={markdown}
        />
      )}
      {activeTab === "analysis" && (
        <CompanyRuntimeDesk
          companies={filteredCompanies}
          tradeProposals={[]}
          tradingConsensus={{ status: "analysis", reason: "分析部門は全期間データ、ボラティリティ、相関、流動性を処理します。" }}
          runtimeQueue={runtimeQueue}
        />
      )}
      {activeTab === "strategy" && (
        <CompanyRuntimeDesk
          companies={filteredCompanies}
          tradeProposals={tradeProposals}
          tradingConsensus={tradingConsensus}
          runtimeQueue={runtimeQueue}
        />
      )}
      {activeTab === "virtual" && (
        <>
          <CompanyRuntimeDesk
            companies={filteredCompanies}
            tradeProposals={tradeProposals}
            tradingConsensus={tradingConsensus}
            runtimeQueue={runtimeQueue}
          />
          <VirtualOrderDesk desk={virtualOrderDesk} markdown={virtualOrderMarkdown} />
        </>
      )}
    </section>
  );
}

function CompanyRuntimeDesk({ companies, tradeProposals, tradingConsensus, runtimeQueue }) {
  const rows = companies || [];
  if (!rows.length) return null;
  const selected = tradingConsensus?.selected_proposal || null;
  return (
    <section className="band organization-band company-runtime-band">
      <details open>
        <summary className="virtual-summary">
          <span>
            <span className="section-kicker">COMPANY RUNTIME</span>
            <span className="section-title">事業部制エージェント実行</span>
          </span>
          <span className="metric-note">Company制 / 共有Evidence / 2名Virtual Trader</span>
        </summary>
        <div className="company-runtime-grid">
          {rows.map((company) => (
            <div className="organization-card company-card" key={company.id}>
              <div className="organization-card-head">
                <div>
                  <div className="company-ja">{company.labelJa}</div>
                  <div className="tiny-label">{company.labelEn}</div>
                </div>
                <span className="agent-status status-running">{(company.agents || []).length} agents</span>
              </div>
              <p className="metric-note">{company.descriptionJa}</p>
              <div className="company-agent-list">
                {(company.agents || []).map((agent) => (
                  <div className="company-agent-row" key={agent.agent_id}>
                    <div>
                      <div className="company-agent-ja">{agent.label_ja}</div>
                      <div className="tiny-label">{agent.label_en}</div>
                    </div>
                    <div className="company-agent-state">
                      <span className={`agent-status status-${agent.status}`}>{agent.status}</span>
                      <span className="metric-note">{agent.latest_task}</span>
                      <span className="metric-note">{(agent.principles || []).slice(0, 2).join(" / ")}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="virtual-grid runtime-summary-grid">
          <VirtualInfoCard
            label="CONSENSUS"
            title={tradingConsensus?.status || "waiting"}
            note={tradingConsensus?.reason || "共有情報の更新待ち"}
            tone={tradingConsensus?.status === "approved_for_virtual_order" ? "positive" : "warning"}
          />
          <VirtualInfoCard
            label="SELECTED PROPOSAL"
            title={selected ? `${selected.symbol} ${selected.side}/${selected.order_type}` : "no order"}
            note={selected ? `confidence ${number.format((selected.confidence || 0) * 100)}%` : "市場外・Evidence不足・意見割れでは作成しません"}
            tone={selected ? "positive" : ""}
          />
          <VirtualInfoCard
            label="RUNTIME QUEUE"
            title={`${(runtimeQueue || []).length} tasks`}
            note={(runtimeQueue || [])[0]?.task || "queue empty"}
            tone=""
          />
        </div>
        <div className="runtime-ledgers">
          <ResearchLedger
            title="TRADE PROPOSALS / 仮想売買案"
            rows={tradeProposals || []}
            getMain={(row) => `${row.symbol} ${row.side}/${row.order_type} by ${row.trader_id}`}
            getMeta={(row) => `confidence ${number.format((row.confidence || 0) * 100)}% / evidence ${(row.evidence_refs || []).join(", ")}`}
          />
          <ResearchLedger
            title="NEXT QUEUE / 次タスク"
            rows={runtimeQueue || []}
            getMain={(row) => `${row.task} / ${row.status}`}
            getMeta={(row) => row.reason}
          />
        </div>
      </details>
    </section>
  );
}

function ResearchOrganizationDesk({ desk, tasks, evidenceSummary, evidenceRecords, decisionContexts, markdown }) {
  const divisions = desk?.divisions || [];
  return (
    <section className="band organization-band">
      <details open>
        <summary className="virtual-summary">
          <span>
            <span className="section-kicker">EVIDENCE LEDGER / RESEARCH RECORDS</span>
            <span className="section-title">調査・分析台帳</span>
          </span>
          <span className="tiny-label">EVIDENCE {evidenceSummary?.evidenceTotal || 0} / TASKS {evidenceSummary?.openTaskTotal || 0}</span>
        </summary>
        <div className="virtual-safety">{desk?.safety || "Research simulation only. No broker execution."}</div>
        <div className="organization-grid">
          {divisions.map((division) => (
            <div className="organization-division" key={division.name}>
              <div className="tiny-label"><span className="company-agent-ja">{division.labelJa || division.name}</span><br />{division.labelEn || division.name}</div>
              {(division.agents || []).map((agent) => (
                <div className="organization-agent" key={agent.name}>
                  <div className="agent-card-head">
                    <strong>{agent.labelJa || agent.name}<br /><span className="tiny-label">{agent.labelEn || agent.name}</span></strong>
                    <span className={`agent-status status-${agent.status}`}>{agent.status}</span>
                  </div>
                  <div className="agent-counts">
                    <span>tasks {agent.tasks}</span>
                    <span>evidence {agent.evidence}</span>
                    <span>findings {agent.findings}</span>
                  </div>
                  <div className="agent-log">
                    {(agent.logs || []).slice(-3).map((line, idx) => <div key={idx}>{line}</div>)}
                  </div>
                </div>
              ))}
            </div>
          ))}
          {!divisions.length && <div className="organization-division">Research organization is warming up.</div>}
        </div>
        <div className="research-ledger">
          <ResearchLedger title="RESEARCH TASKS" rows={(tasks || []).slice(-5)} getMain={(row) => row.topic} getMeta={(row) => `P${row.priority}`} />
          <ResearchLedger title="EVIDENCE RECORDS" rows={(evidenceRecords || []).slice(-5)} getMain={(row) => row.title} getMeta={(row) => row.duplicate_of ? "DUP" : "SRC"} />
          <ResearchLedger title="DECISION CONTEXT" rows={(decisionContexts || []).slice(-5)} getMain={(row) => `${row.target_symbol} / ${row.decision_type}`} getMeta={(row) => `${number.format((row.confidence || 0) * 100)}%`} />
        </div>
        <details className="markdown-drawer">
          <summary>Markdown Evidence Ledger</summary>
          <pre>{markdown || "No research markdown yet."}</pre>
        </details>
      </details>
    </section>
  );
}

function ResearchLedger({ title, rows, getMain, getMeta }) {
  return (
    <div>
      <div className="tiny-label">{title}</div>
      {(rows || []).map((row) => (
        <div className="ledger-row" key={row.id}>
          <span>{shortId(row.id)}</span>
          <span>{getMain(row)}</span>
          <span>{getMeta(row)}</span>
        </div>
      ))}
      {!rows?.length && <div className="ledger-row"><span>--</span><span>waiting</span><span>--</span></div>}
    </div>
  );
}

function VirtualInfoCard({ label, title, note, tone }) {
  return (
    <div className="virtual-info-card">
      <div className="tiny-label">{label}</div>
      <div className={`virtual-info-value ${tone || ""}`}>{title}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

function VirtualOrderDesk({ desk, markdown }) {
  const orders = desk?.orders || [];
  const executions = desk?.executions || [];
  const riskChecks = desk?.riskChecks || [];
  const traces = desk?.decisionTrace || [];
  const summary = desk?.summary || {};
  const latestOrder = orders[orders.length - 1] || {};
  const latestExecution = executions[executions.length - 1] || {};
  const latestRisk = riskChecks[riskChecks.length - 1] || {};
  return (
    <section className="band virtual-order-band">
      <details open>
        <summary className="virtual-summary">
          <span>
            <span className="section-kicker">ORGANIZATION / VIRTUAL ORDER DESK</span>
            <span className="section-title">仮想注文管理部門</span>
          </span>
          <span className="tiny-label">SIMULATED ONLY / {desk?.marketSession?.phase || desk?.phase} / {summary.latestStatus || "no_virtual_order"}</span>
        </summary>
        <div className="virtual-safety">{desk?.safety || "All orders are virtual and simulated inside this app."}</div>
        <div className="virtual-grid">
          <VirtualInfoCard
            label="VIRTUAL ORDERS"
            title={summary.ordersStored || 0}
            note={`latest: ${latestOrder.symbol || "--"} / ${latestOrder.status || "--"}`}
          />
          <VirtualInfoCard
            label="RISK CHECK"
            title={latestRisk.passed === false ? "STOP" : latestRisk.passed === true ? "PASS" : "WAIT"}
            note={(latestRisk.failed_rules || []).join(", ") || latestRisk.explanation || "virtual risk gate waiting"}
            tone={latestRisk.passed === false ? "negative" : "positive"}
          />
          <VirtualInfoCard
            label="SIMULATED EXECUTIONS"
            title={summary.executionsStored || 0}
            note={latestExecution.execution_price ? `${latestExecution.symbol} ${yen.format(latestExecution.execution_price)}` : "no simulated fill"}
          />
          <VirtualInfoCard
            label="DECISION TRACE"
            title={summary.decisionTracesStored || 0}
            note={traces[traces.length - 1]?.outcome || "decision_log waiting"}
          />
        </div>
        <div className="virtual-table-wrap">
          <table className="virtual-table">
            <thead>
              <tr><th>Virtual ID</th><th>Symbol</th><th>Side / Type</th><th>Qty</th><th>Price</th><th>Status</th><th>Created JST</th><th>Executed JST</th><th>Evidence</th></tr>
            </thead>
            <tbody>
              {orders.slice(-5).map((order) => (
                <tr key={`${order.id}-${order.status}`}>
                  <td>{shortId(order.id)}</td>
                  <td className="row-symbol">{order.symbol}</td>
                  <td>{order.side} / {order.order_type}</td>
                  <td>{number.format(order.quantity || 0)}</td>
                  <td>{yen.format(order.expected_price || order.simulated_execution_price || 0)}</td>
                  <td>{order.displayStatus || order.status}</td>
                  <td>{formatJstDate(order.created_at)}</td>
                  <td>{formatJstDate(order.simulated_executed_at)}</td>
                  <td>{(order.related_evidence_ids || []).join(" / ") || "--"}</td>
                </tr>
              ))}
              {!orders.length && <tr><td colSpan="9">VirtualOrder is waiting for an evidence-backed DecisionContext.</td></tr>}
            </tbody>
          </table>
        </div>
        <details className="markdown-drawer">
          <summary>Markdown Virtual Order History</summary>
          <pre>{markdown || desk?.markdown || "No virtual order markdown yet."}</pre>
        </details>
        <div className="virtual-artifacts">
          <span>orders.jsonl: {desk?.artifactPaths?.orders || "--"}</span>
          <span>trades.csv: {desk?.artifactPaths?.trades || "--"}</span>
          <span>decision_log.jsonl: {desk?.artifactPaths?.decisionLog || "--"}</span>
          <span>orders.md: {desk?.artifactPaths?.markdown || "--"}</span>
        </div>
      </details>
    </section>
  );
}

function shortId(value) {
  if (!value) return "—";
  const text = String(value);
  return text.length > 16 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text;
}

function formatJstDate(value) {
  if (!value) return "pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const parts = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function Metric({ label, title, value, note, signed, expanded, onToggle, detail }) {
  const content = (
    <>
      <div className="metric-label">{label}</div>
      <div style={{ marginTop: 8, fontWeight: 800 }}>{title}</div>
      <div className={`metric-value ${signed === undefined ? "" : clsFor(signed)}`}>{value}</div>
      <div className="metric-note">{note}</div>
      {onToggle && <div className="metric-toggle">{expanded ? "▲ 詳細を閉じる" : "▼ 詳細を見る"}</div>}
      {expanded && detail}
    </>
  );
  return (
    onToggle ? <button className="summary-card summary-card-button" onClick={onToggle}>{content}</button> : <div className="summary-card">{content}</div>
  );
}

function InfoStrip({ focus, quote }) {
  const cells = [
    ["始値", quote.open],
    ["終値", quote.close],
    ["高値", quote.high],
    ["安値", quote.low],
    ["出来高", quote.volume],
    ["PER", quote.trailingPE],
    ["時価総額", quote.marketCap],
    ["52週高値", quote.fiftyTwoWeekHigh],
    ["52週安値", quote.fiftyTwoWeekLow],
    ["平均出来高", quote.averageVolume],
    ["利回り", quote.dividendYield],
    ["EPS", quote.trailingEps],
  ];
  return (
    <div className="info-strip">
      {cells.map(([label, value]) => <div className="info-cell" key={label}><div className="tiny-label">{label}</div><div className="value">{formatInfo(label, value)}</div></div>)}
    </div>
  );
}

function formatInfo(label, value) {
  if (value === null || value === undefined || value === "") return "—";
  if (["時価総額", "出来高", "平均出来高"].includes(label)) return number.format(value);
  if (label === "利回り") return `${number.format(value)}%`;
  if (["PER", "EPS"].includes(label)) return number.format(value);
  return yen.format(value);
}

function AllocationTable({ rows }) {
  return (
    <table className="allocation-table">
      <thead><tr><th>SYMBOL</th><th>セクター</th><th>VALUE</th><th>SHARE</th></tr></thead>
      <tbody>
        {rows.map((row, idx) => (
          <tr key={row.symbol}>
            <td className="row-symbol"><span className="swatch" style={{ background: colors[idx % colors.length] }}></span>{row.symbol}</td>
            <td>{row.sector}</td>
            <td>{yen.format(row.value || 0)}</td>
            <td>{number.format(row.share || 0)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Positions({ rows, setFocusSymbol }) {
  return (
    <table className="positions-table">
      <thead><tr><th>銘柄</th><th>市場</th><th>数量</th><th>平均取得</th><th>現在値</th><th>評価額</th><th>損益</th><th>現在値1ヶ月推移</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.symbol} onClick={() => setFocusSymbol(row.symbol)}>
            <td className="row-symbol">{row.symbol}</td>
            <td>{row.market}</td>
            <td>{number.format(row.quantity)}</td>
            <td>{yen.format(row.averageCost)}</td>
            <td>{yen.format(row.current)}</td>
            <td>{yen.format(row.value)}</td>
            <td className={clsFor(row.pnl)}>{formatSignedYen(row.pnl)}</td>
            <td><Sparkline data={row.sparkline} color={Number(row.pnl) >= 0 ? "#d8d5cc" : "#d65362"} interactive /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PositionCards({ rows, setFocusSymbol }) {
  return (
    <div className="position-card-grid">
      {rows.map((row) => (
        <button className="position-card" key={row.symbol} onClick={() => setFocusSymbol(row.symbol)}>
          <div className="watch-top"><strong>{row.symbol}</strong><span>{row.market}</span></div>
          <div className="watch-name">{row.sector}</div>
          <div className="watch-price">{yen.format(row.current)}</div>
          <div className={clsFor(row.pnl)}>{formatSignedYen(row.pnl)}</div>
          <Sparkline data={row.sparkline} color={Number(row.pnl) >= 0 ? "#d8d5cc" : "#d65362"} interactive />
        </button>
      ))}
    </div>
  );
}

function AgentHealthMonitor({ agents, agentPulse }) {
  const warnings = (agents || []).reduce((sum, agent) => sum + Number(agent.warningCount || 0), 0);
  const errors = (agents || []).reduce((sum, agent) => sum + Number(agent.errorCount || 0), 0);
  return (
    <section className="band">
      <div className="section-head">
        <div>
          <div className="section-kicker">AGENTS / PROCESS</div>
          <div className="section-title">実行中プロセス</div>
        </div>
        <div className="tiny-label">HEALTH W {warnings} / E {errors}</div>
      </div>
      <div className="process-grid">
        {(agents || []).map((item) => (
          <AgentProcessCard item={item} visibleCount={agentPulse} key={item.id || item.label} />
        ))}
      </div>
    </section>
  );
}

function AgentProcessCard({ item, visibleCount }) {
  const logs = (item.logs || []).slice(-Math.max(3, visibleCount));
  const terminal = (item.terminal || []).slice(-50);
  return (
    <div className={`process-card status-${item.status}`}>
      <div className="agent-card-head">
        <div className="tiny-label">{item.label}</div>
        <span className={`agent-status status-${item.status}`}>{item.status}</span>
      </div>
      <div className="agent-status-line">{item.statusLabel}</div>
      <div className="agent-meta">
        <span>最終 {item.lastRunAt ? new Date(item.lastRunAt).toLocaleTimeString("ja-JP") : "—"}</span>
        <span>HB {item.heartbeatAge ?? 0}s</span>
      </div>
      <div className="agent-task">{item.latestTask}</div>
      <div className="agent-counts">
        <span className="positive">S {item.successCount || 0}</span>
        <span className="warning">W {item.warningCount || 0}</span>
        <span className="negative">E {item.errorCount || 0}</span>
      </div>
      <div className="progress"><span style={{ width: `${item.progress}%` }} /></div>
      <div className="agent-log">
        {logs.map((line, idx) => <div className="log-line" key={`${item.label}-log-${idx}`}>{line}</div>)}
      </div>
      <MiniTerminal lines={terminal} agentLabel={item.label} />
    </div>
  );
}

function MiniTerminal({ lines, agentLabel }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);
  return (
    <div className="mini-terminal" ref={ref}>
      {(lines || []).map((line, idx) => {
        const lowered = String(line).toLowerCase();
        const level = lowered.includes("error") ? "terminal-error" : lowered.includes("warning") || lowered.includes("fallback") ? "terminal-warning" : lowered.includes("success") || lowered.includes("completed") ? "terminal-success" : "";
        return <div className={level} key={`${agentLabel}-cmd-${idx}`}>{line}</div>;
      })}
    </div>
  );
}

function AgentChatPanel({ focus, summary, intelligenceFeed, clock, strategyOutput, agents }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [messages, setMessages] = useState([
    { role: "ai", text: "FOCUS銘柄、ポートフォリオ、ニュース、出来高を統合して監視しています。" },
  ]);

  useEffect(() => {
    setMessages((items) => [
      ...items.slice(-5),
      { role: "ai", text: buildAgentNarrative(focus, summary, intelligenceFeed, clock, strategyOutput, agents) },
    ]);
  }, [focus?.symbol, strategyOutput?.tomorrow]);

  const submit = (event) => {
    event.preventDefault();
    const prompt = input.trim();
    if (!prompt) return;
    setMessages((items) => [...items, { role: "user", text: prompt }]);
    setInput("");
    setTyping(true);
    window.setTimeout(() => {
      setMessages((items) => [
        ...items,
        {
          role: "ai",
          text: buildAgentNarrative(focus, summary, intelligenceFeed, clock, strategyOutput, agents),
        },
      ]);
      setTyping(false);
    }, 720);
  };

  return (
    <aside className={`agent-chat ${open ? "open" : ""}`}>
      <button className="agent-chat-tab" onClick={() => setOpen((value) => !value)}>AI AGENT</button>
      {open && (
        <div className="agent-chat-panel">
          <div className="section-kicker">AGENT CHAT / {focus?.symbol}</div>
          <div className="chat-feed">
            {messages.map((message, idx) => <div className={`chat-bubble ${message.role}`} key={idx}>{message.text}</div>)}
            {typing && <div className="chat-bubble ai typing">typing...</div>}
          </div>
          <form onSubmit={submit} className="chat-form">
            <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="この銘柄の今後は？" />
            <button type="submit">SEND</button>
          </form>
        </div>
      )}
    </aside>
  );
}

function DetailDrawer({ focus, onClose }) {
  const q = focus?.quote || {};
  const details = [
    ["現在値", yen.format(q.current || 0)], ["始値", yen.format(q.open || 0)], ["高値", yen.format(q.high || 0)], ["安値", yen.format(q.low || 0)],
    ["終値", yen.format(q.close || 0)], ["出来高", number.format(q.volume || 0)], ["平均出来高", number.format(q.averageVolume || 0)],
    ["時価総額", number.format(q.marketCap || 0)], ["PER", number.format(q.trailingPE || 0)], ["EPS", number.format(q.trailingEps || 0)],
    ["ベータ", number.format(q.beta || 0)], ["利回り", `${number.format(q.dividendYield || 0)}%`],
    ["52週高値", yen.format(q.fiftyTwoWeekHigh || 0)], ["52週安値", yen.format(q.fiftyTwoWeekLow || 0)],
    ["セクター", focus?.sector || "—"], ["業種", focus?.industry || "—"], ["通貨", focus?.currency || "JPY"], ["取引所", focus?.exchange || "TSE"],
  ];
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose}></div>
      <aside className="drawer">
        <button className="drawer-close" onClick={onClose}>×</button>
        <div className="section-kicker">{focus?.symbol}</div>
        <h2 className="focus-name">{focus?.jpName}</h2>
        <div className="subtitle">{focus?.longName}</div>
        <div className="detail-grid">
          {details.map(([label, value]) => <div className="detail-item" key={label}><div className="tiny-label">{label}</div><div style={{ marginTop: 7 }}>{value}</div></div>)}
        </div>
        <div style={{ marginTop: 28 }}>
          <div className="section-kicker">ANALYSIS</div>
          {(focus?.analysis || []).map((line, idx) => <p key={idx}>{line}</p>)}
        </div>
        {focus?.businessSummary && <p className="subtitle">{focus.businessSummary}</p>}
      </aside>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
