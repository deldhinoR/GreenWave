import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { buildIntersectionId, fetchJson } from "../lib/api";
import { getLanguage } from "../lib/environment";

export default function RuntimeMonitorPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { regionId } = useParams();
  const [runtime, setRuntime] = useState(null);
  const [error, setError] = useState("");

  const currentPage = location.pathname.split("/").pop();
  const navButtonClass = (page) => `secondary-button ${currentPage === page ? "active-tab" : ""}`;

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      try {
        const intersectionId = buildIntersectionId(regionId);
        const data = await fetchJson(`/intersections/${intersectionId}/runtime-monitor?limit=20`);
        if (mounted) {
          setRuntime(data);
          setError("");
        }
      } catch (_err) {
        if (mounted) setError(tr ? "Çalışma izleme yüklenemedi." : "Failed to load runtime monitor.");
      }
    };

    load();
    const id = setInterval(load, 2000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [regionId, tr]);

  const latest = runtime?.latest || {};

  return (
    <div className="page-stack" style={{ gap: "1rem" }}>
      <div className="page-frame-header">
        <button className="secondary-button" type="button" onClick={() => navigate("/overview")}>{tr ? "Haritaya Dön" : "Back to Map"}</button>
        <div className="section-heading compact">
          <span className="eyebrow">{tr ? "Canlı SUMO Çalışması" : "Live SUMO Runtime"}</span>
          <h2>{runtime?.intersection?.name || `${tr ? "Kavşak" : "Intersection"} ${regionId}`}</h2>
        </div>
      </div>

      <div className="section-tabs">
        <button className={navButtonClass("dashboard")} type="button" onClick={() => navigate(`/region/${regionId}/dashboard`)}>{tr ? "Panel" : "Dashboard"}</button>
        <button className={navButtonClass("runtime")} type="button" onClick={() => navigate(`/region/${regionId}/runtime`)}>{tr ? "Çalışma" : "Runtime"}</button>
        <button className={navButtonClass("logs")} type="button" onClick={() => navigate(`/region/${regionId}/logs`)}>{tr ? "Sistem Kayıtları" : "System Logs"}</button>
      </div>

      {error ? <section className="card"><p>{error}</p></section> : null}

      <section className="metric-grid">
        <article className="metric-card tone-alert">
          <div className="metric-top"><span className="eyebrow">Current Step</span><strong>Live</strong></div>
          <div className="metric-value"><h3>{latest.step ?? "-"}</h3><span>tick</span></div>
        </article>
        <article className="metric-card tone-alert">
          <div className="metric-top"><span className="eyebrow">Queue</span><strong>Live</strong></div>
          <div className="metric-value"><h3>{latest.queueLength ?? "-"}</h3><span>veh</span></div>
        </article>
        <article className="metric-card tone-positive">
          <div className="metric-top"><span className="eyebrow">Selected Phase</span><strong>Decision</strong></div>
          <div className="metric-value"><h3>{latest.selectedPhase ?? "-"}</h3><span>phase</span></div>
        </article>
        <article className="metric-card tone-positive">
          <div className="metric-top"><span className="eyebrow">Green Time</span><strong>Decision</strong></div>
          <div className="metric-value"><h3>{latest.greenSeconds ?? "-"}</h3><span>sec</span></div>
        </article>
      </section>

      <section className="card">
        <div className="card-header">
          <div className="section-heading compact">
            <span className="eyebrow">Recent Decisions</span>
            <h2>Phase + Signal Times</h2>
          </div>
        </div>
        <div className="incident-list">
          {(runtime?.recentDecisions || []).map((d) => (
            <div key={`d-${d.step}-${d.createdAt}`} className="incident-item">
              <div>
                <strong>Step {d.step}</strong>
                <p>P{d.selectedPhase} | {d.greenSeconds}s green | {d.redSeconds}s red</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <div className="section-heading compact">
            <span className="eyebrow">Recent Simulation</span>
            <h2>Queue / Waiting / Density</h2>
          </div>
        </div>
        <div className="incident-list">
          {(runtime?.recentSimulation || []).map((s) => (
            <div key={`s-${s.step}-${s.createdAt}`} className="incident-item">
              <div>
                <strong>Step {s.step}</strong>
                <p>Queue: {s.queueLength} | Wait: {s.avgWaitingSeconds}s | Density: {s.densityLevel}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
  const tr = getLanguage() === "Turkish";
