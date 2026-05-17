import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { buildIntersectionId, fetchJson } from "../lib/api";

export default function DashboardPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { regionId } = useParams();

  const [intersectionName, setIntersectionName] = useState("");
  const [dashboardCards, setDashboardCards] = useState({
    congestionImprovement: 0,
    avgCongestion: 0,
    todayAvgCongestion: 0,
    signalTimes: { greenSeconds: 0, redSeconds: 0 },
  });
  const [signalPlanCompact, setSignalPlanCompact] = useState([]);
  const [range, setRange] = useState("24h");
  const [series, setSeries] = useState([]);
  const [summary, setSummary] = useState({ average: 0, peak: 0 });
  const [hovered, setHovered] = useState(null);

  const currentPage = location.pathname.split("/").pop();
  const navButtonClass = (page) => `secondary-button ${currentPage === page ? "active-tab" : ""}`;

  useEffect(() => {
    let mounted = true;
    const loadDashboard = async () => {
      try {
        const intersectionId = buildIntersectionId(regionId);
        const data = await fetchJson(`/intersections/${intersectionId}/live-dashboard`);
        if (!mounted) return;
        setIntersectionName(data.intersection?.name || intersectionId);

        setDashboardCards({
          congestionImprovement: Number(data.cards?.liveCongestionImprovement || 0),
          avgCongestion: Number(data.cards?.avgCongestion || 0),
          todayAvgCongestion: Number(data.cards?.todayAvgCongestion || 0),
          signalTimes: {
            greenSeconds: Number(data.signalPlan?.[0]?.greenSeconds || 0),
            redSeconds: Number(data.signalPlan?.[0]?.redSeconds || 0),
          },
        });

        const rawPlan = data.signalPlan || [];
        const seen = new Set();
        const compact = [];
        for (const row of rawPlan) {
          const key = String(row.phaseCode || "");
          if (!key || seen.has(key)) continue;
          seen.add(key);
          compact.push(row);
        }
        setSignalPlanCompact(compact);
      } catch (err) {
        console.error("Error loading dashboard:", err);
      }
    };

    loadDashboard();
    const id = setInterval(loadDashboard, 3000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [regionId]);

  useEffect(() => {
    let mounted = true;
    const loadAnalytics = async () => {
      try {
        const intersectionId = buildIntersectionId(regionId);
        const data = await fetchJson(`/intersections/${intersectionId}/analytics?range=${range}`, {
          cache: "no-store",
        });
        if (!mounted) return;
        setSeries(data.series || []);
        setSummary(data.summary || { average: 0, peak: 0 });
        setHovered(null);
      } catch (err) {
        console.error("Error loading analytics:", err);
        if (!mounted) return;
        // Keep the section deterministic on transient startup failures.
        setSeries([]);
        setSummary({ average: 0, peak: 0 });
      }
    };

    loadAnalytics();
    const id = setInterval(loadAnalytics, 3000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [regionId, range]);

  const maxValue = useMemo(() => {
    const max = Math.max(...series.map((item) => Number(item.value || 0)), 1);
    return Math.max(100, max);
  }, [series]);

  const yTicks = [0, 20, 40, 60, 80, 100];

  const liveMetrics = [
    {
      label: "Congestion Improvement",
      value: `${dashboardCards.congestionImprovement.toFixed(1)}`,
      suffix: "%",
      trend: "Live Calculated",
      tone: "positive",
    },
    {
      label: "Avg Congestion",
      value: `${dashboardCards.avgCongestion}`,
      suffix: "/100",
      trend: "Live",
      tone: "alert",
    },
    {
      label: "Today's Avg Congestion",
      value: `${dashboardCards.todayAvgCongestion.toFixed(1)}`,
      suffix: "/100",
      trend: "Today",
      tone: "accent",
    },
  ];

  return (
    <div className="page-stack" style={{ gap: "1rem" }}>
      <div className="page-frame-header">
        <button className="secondary-button" type="button" onClick={() => navigate("/overview")}>Back to Map</button>
        <div className="section-heading compact">
          <span className="eyebrow">Live Intersection Monitor</span>
          <h2>{intersectionName || `Intersection ${regionId}`}</h2>
        </div>
      </div>

      <div className="section-tabs">
        <button className={navButtonClass("dashboard")} type="button" onClick={() => navigate(`/region/${regionId}/dashboard`)}>Dashboard</button>
        <button className={navButtonClass("runtime")} type="button" onClick={() => navigate(`/region/${regionId}/runtime`)}>Runtime</button>
        <button className={navButtonClass("logs")} type="button" onClick={() => navigate(`/region/${regionId}/logs`)}>System Logs</button>
      </div>

      <section className="metric-grid">
        {liveMetrics.map((metric) => (
          <article key={metric.label} className={`metric-card tone-${metric.tone}`}>
            <div className="metric-top">
              <span className="eyebrow">{metric.label}</span>
              <strong>{metric.trend}</strong>
            </div>
            <div className="metric-value">
              <h3>{metric.value}</h3>
              <span>{metric.suffix}</span>
            </div>
          </article>
        ))}
      </section>

      <section className="card">
        <div className="card-header">
          <div className="section-heading compact">
            <span className="eyebrow">Optimized Signal Plan</span>
            <h2>Phase Durations</h2>
          </div>
        </div>
        <div className="incident-list" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem" }}>
          {signalPlanCompact.map((phase) => (
            <div key={phase.phaseCode} className="incident-item" style={{ border: "1px solid var(--outline-variant)", borderRadius: "12px", padding: "0.8rem 1rem" }}>
              <div>
                <strong>{phase.phaseCode}</strong>
                <p>{phase.greenSeconds}s green | {phase.redSeconds}s red</p>
              </div>
            </div>
          ))}
          {signalPlanCompact.length === 0 && <p>No signal plan data</p>}
        </div>
      </section>

      <section className="hero-row">
        <div className="section-heading">
          <span className="eyebrow live">Average Congestion History</span>
          <h2>{range === "24h" ? "Last 24 Hours (Hourly)" : range === "7d" ? "Last 7 Days (Daily)" : "Last 30 Days (Daily)"}</h2>
        </div>

        <div className="button-group">
          <button className={`secondary-button ${range === "24h" ? "active-tab" : ""}`} type="button" onClick={() => setRange("24h")}>Last 24 Hours</button>
          <button className={`secondary-button ${range === "7d" ? "active-tab" : ""}`} type="button" onClick={() => setRange("7d")}>Last 7 Days</button>
          <button className={`secondary-button ${range === "30d" ? "active-tab" : ""}`} type="button" onClick={() => setRange("30d")}>Last 30 Days</button>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card tone-alert">
          <div className="metric-top">
            <span className="eyebrow">Average Congestion</span>
            <strong>0-100 Index</strong>
          </div>
          <div className="metric-value">
            <h3>{Number(summary.average || 0).toFixed(1)}</h3>
            <span>/100</span>
          </div>
        </article>

        <article className="metric-card tone-accent">
          <div className="metric-top">
            <span className="eyebrow">Peak Congestion</span>
            <strong>Selected Range</strong>
          </div>
          <div className="metric-value">
            <h3>{Number(summary.peak || 0).toFixed(1)}</h3>
            <span>/100</span>
          </div>
        </article>
      </section>

      <section className="card">
        <div className="card-header" style={{ alignItems: "center" }}>
          <div className="section-heading compact">
            <span className="eyebrow">Congestion Chart</span>
            <h2>{range === "24h" ? "Hourly" : "Daily"} Averages</h2>
          </div>
          <div>
            {hovered ? (
              <strong>{hovered.label}: {Number(hovered.value).toFixed(1)} /100</strong>
            ) : (
              <strong>Hover a bar to see value</strong>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "48px 1fr", gap: "10px", alignItems: "end" }}>
          <div style={{ display: "flex", flexDirection: "column-reverse", height: "240px", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted, #64748b)" }}>
            {yTicks.map((tick) => (
              <span key={tick}>{tick}</span>
            ))}
          </div>

          <div>
            <div className="bar-chart" style={{ minHeight: "240px", alignItems: "end", borderLeft: "1px solid #d6d9de", borderBottom: "1px solid #d6d9de", paddingLeft: "8px", paddingBottom: "8px" }}>
              {series.map((item) => {
                const value = Number(item.value || 0);
                const height = Math.max(6, (value / maxValue) * 100);
                return (
                  <div
                    key={`${item.label}-${item.timestamp}`}
                    className={`chart-bar ${value >= Number(summary.average) ? "is-strong" : ""}`}
                    style={{ height: `${height}%` }}
                    title={`${item.label}: ${value.toFixed(1)}`}
                    onMouseEnter={() => setHovered(item)}
                    onFocus={() => setHovered(item)}
                  />
                );
              })}
            </div>
          </div>
        </div>
      </section>

    </div>
  );
}
