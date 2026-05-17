import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { buildIntersectionId, fetchJson } from "../lib/api";

export default function AnalyticsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { regionId } = useParams();

  const [intersectionName, setIntersectionName] = useState("");
  const [range, setRange] = useState("24h");
  const [series, setSeries] = useState([]);
  const [summary, setSummary] = useState({ average: 0, peak: 0 });
  const [hovered, setHovered] = useState(null);
  const [selectedDailyBar, setSelectedDailyBar] = useState(null);
  const [selectedDayHourlySeries, setSelectedDayHourlySeries] = useState([]);
  const [selectedDayLoading, setSelectedDayLoading] = useState(false);

  const currentPage = location.pathname.split("/").pop();
  const navButtonClass = (page) => `secondary-button ${currentPage === page ? "active-tab" : ""}`;

  useEffect(() => {
    const loadAnalytics = async () => {
      try {
        const intersectionId = buildIntersectionId(regionId);
        const data = await fetchJson(`/intersections/${intersectionId}/analytics?range=${range}`);
        setIntersectionName(data.intersection?.name || intersectionId);
        setSeries(data.series || []);
        setSummary(data.summary || { average: 0, peak: 0 });
        setHovered(null);
        setSelectedDailyBar(null);
      } catch (err) {
        console.error("Error loading analytics:", err);
      }
    };

    loadAnalytics();
  }, [regionId, range]);

  const maxValue = useMemo(() => {
    const max = Math.max(...series.map((item) => Number(item.value || 0)), 1);
    return Math.max(100, max);
  }, [series]);

  const yTicks = [0, 20, 40, 60, 80, 100];

  const labelStep = useMemo(() => {
    if (series.length <= 8) return 1;
    if (series.length <= 14) return 2;
    return Math.ceil(series.length / 10);
  }, [series.length]);

  useEffect(() => {
    const loadSelectedDayDetails = async () => {
      if (!selectedDailyBar || range === "24h") {
        setSelectedDayHourlySeries([]);
        return;
      }
      try {
        setSelectedDayLoading(true);
        const intersectionId = buildIntersectionId(regionId);
        const data = await fetchJson(
          `/intersections/${intersectionId}/analytics/day?date=${selectedDailyBar.timestamp}`
        );
        setSelectedDayHourlySeries(data.series || []);
      } catch (_err) {
        setSelectedDayHourlySeries([]);
      } finally {
        setSelectedDayLoading(false);
      }
    };

    loadSelectedDayDetails();
  }, [selectedDailyBar, range, regionId]);

  const selectedDayMax = useMemo(() => {
    const max = Math.max(...selectedDayHourlySeries.map((item) => item.value), 1);
    return Math.max(100, max);
  }, [selectedDayHourlySeries]);

  return (
    <div className="page-stack" style={{ gap: "1rem" }}>
      <div className="page-frame-header">
        <button className="secondary-button" type="button" onClick={() => navigate("/overview")}>Back to Map</button>
        <div className="section-heading compact">
          <span className="eyebrow">Congestion Analytics</span>
          <h2>{intersectionName || `Intersection ${regionId}`}</h2>
        </div>
      </div>

      <div className="section-tabs">
        <button className={navButtonClass("dashboard")} type="button" onClick={() => navigate(`/region/${regionId}/dashboard`)}>Dashboard</button>
        <button className={navButtonClass("runtime")} type="button" onClick={() => navigate(`/region/${regionId}/runtime`)}>Runtime</button>
        <button className={navButtonClass("logs")} type="button" onClick={() => navigate(`/region/${regionId}/logs`)}>System Logs</button>
      </div>

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
                    style={{ height: `${height}%`, cursor: "pointer" }}
                    title={`${item.label}: ${value.toFixed(1)}`}
                    role={range === "24h" ? undefined : "button"}
                    tabIndex={range === "24h" ? -1 : 0}
                    onMouseEnter={() => setHovered(item)}
                    onFocus={() => setHovered(item)}
                    onClick={() => {
                      if (range === "24h") return;
                      setSelectedDailyBar(item);
                    }}
                    onKeyDown={(event) => {
                      if (range === "24h") return;
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedDailyBar(item);
                      }
                    }}
                  />
                );
              })}
            </div>

            <div className="axis-row" style={{ display: "grid", gridTemplateColumns: `repeat(${Math.max(series.length, 1)}, minmax(24px, 1fr))`, gap: "6px", marginTop: "8px" }}>
              {series.map((item, idx) => (
                <span key={`lbl-${item.label}-${item.timestamp}`} style={{ fontSize: "10px", textAlign: "center", opacity: idx % labelStep === 0 ? 1 : 0.25 }}>
                  {idx % labelStep === 0 ? item.label : "."}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {range !== "24h" && selectedDailyBar && (
        <section className="card">
          <div className="card-header" style={{ alignItems: "center", gap: "10px" }}>
            <div className="section-heading compact">
              <span className="eyebrow">Selected Day Detail</span>
              <h2>{selectedDailyBar.label} - Hourly View</h2>
            </div>
            <button className="secondary-button" type="button" onClick={() => setSelectedDailyBar(null)}>
              Close
            </button>
          </div>

          {selectedDayLoading ? (
            <p>Loading selected day hourly data...</p>
          ) : selectedDayHourlySeries.length === 0 ? (
            <p>No hourly data found for {selectedDailyBar.label}.</p>
          ) : (
          <div style={{ display: "grid", gridTemplateColumns: "48px 1fr", gap: "10px", alignItems: "end" }}>
            <div style={{ display: "flex", flexDirection: "column-reverse", height: "240px", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted, #64748b)" }}>
              {yTicks.map((tick) => (
                <span key={`selected-${tick}`}>{tick}</span>
              ))}
            </div>

            <div>
              <div className="bar-chart" style={{ minHeight: "240px", alignItems: "end", borderLeft: "1px solid #d6d9de", borderBottom: "1px solid #d6d9de", paddingLeft: "8px", paddingBottom: "8px" }}>
                {selectedDayHourlySeries.map((item) => {
                  const height = Math.max(6, (item.value / selectedDayMax) * 100);
                  return (
                    <div
                      key={`hour-${item.label}`}
                      className={`chart-bar ${item.value >= Number(selectedDailyBar.value || 0) ? "is-strong" : ""}`}
                      style={{ height: `${height}%` }}
                      title={`${item.label}: ${item.value.toFixed(1)}`}
                    />
                  );
                })}
              </div>

              <div className="axis-row" style={{ display: "grid", gridTemplateColumns: "repeat(24, minmax(16px, 1fr))", gap: "4px", marginTop: "8px" }}>
                {selectedDayHourlySeries.map((item, idx) => (
                  <span key={`hour-lbl-${item.label}`} style={{ fontSize: "10px", textAlign: "center", opacity: idx % 3 === 0 ? 1 : 0.2 }}>
                    {idx % 3 === 0 ? item.label.slice(0, 2) : "."}
                  </span>
                ))}
              </div>
            </div>
          </div>
          )}
        </section>
      )}
    </div>
  );
}
