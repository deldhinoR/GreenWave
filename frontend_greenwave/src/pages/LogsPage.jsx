import { useEffect, useState } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { buildIntersectionId, fetchJson } from "../lib/api";
import { getLanguage } from "../lib/environment";

export default function LogsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { regionId } = useParams();

  const [intersectionName, setIntersectionName] = useState("");
  const [logs, setLogs] = useState([]);

  const currentPage = location.pathname.split("/").pop();
  const navButtonClass = (page) => `secondary-button ${currentPage === page ? "active-tab" : ""}`;

  useEffect(() => {
    let mounted = true;
    const loadLogs = async () => {
      try {
        const intersectionId = buildIntersectionId(regionId);
        const data = await fetchJson(`/intersections/${intersectionId}/system-logs?limit=120`);
        if (!mounted) return;
        setIntersectionName(data.intersection?.name || intersectionId);
        setLogs(data.logs || []);
      } catch (err) {
        console.error("Error loading system logs:", err);
      }
    };

    loadLogs();
    const id = setInterval(loadLogs, 5000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [regionId]);

  return (
    <div className="page-stack" style={{ gap: "1rem" }}>
      <div className="page-frame-header">
        <button className="secondary-button" type="button" onClick={() => navigate("/overview")}>{tr ? "Haritaya Dön" : "Back to Map"}</button>
        <div className="section-heading compact">
          <span className="eyebrow">{tr ? "Sistem Kayıtları" : "System Logs"}</span>
          <h2>{intersectionName || `${tr ? "Kavşak" : "Intersection"} ${regionId}`}</h2>
        </div>
      </div>

      <div className="section-tabs">
        <button className={navButtonClass("dashboard")} type="button" onClick={() => navigate(`/region/${regionId}/dashboard`)}>{tr ? "Panel" : "Dashboard"}</button>
        <button className={navButtonClass("runtime")} type="button" onClick={() => navigate(`/region/${regionId}/runtime`)}>{tr ? "Çalışma" : "Runtime"}</button>
        <button className={navButtonClass("logs")} type="button" onClick={() => navigate(`/region/${regionId}/logs`)}>{tr ? "Sistem Kayıtları" : "System Logs"}</button>
      </div>

      <section className="card">
        <div className="card-header">
          <div className="section-heading compact">
            <span className="eyebrow">{tr ? "Olay Listesi" : "Event List"}</span>
            <h2>{tr ? "Hatalar ve Olaylar" : "Failures and Events"}</h2>
          </div>
        </div>

        <div className="incident-list">
          {logs.map((item, idx) => (
            <div key={`${item.eventTime}-${idx}`} className="incident-item" style={{ borderBottom: "1px solid #eef1f5", paddingBottom: "0.65rem" }}>
              <div>
                <strong>{item.eventTime}</strong>
                <p>{item.issue}</p>
              </div>
            </div>
          ))}
          {logs.length === 0 && <p>{tr ? "Kayıt bulunamadı." : "No logs found."}</p>}
        </div>
      </section>
    </div>
  );
}
  const tr = getLanguage() === "Turkish";
