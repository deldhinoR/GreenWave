import { useEffect, useRef, useState } from "react";
import logo from "../assets/GW_logo.svg";
import { fetchJson } from "../lib/api";
import { environmentEventName, getLanguage } from "../lib/environment";


// Leaflet'i CDN'den yükle
const loadLeaflet = () => {
  return new Promise((resolve) => {
    if (window.L) {
      resolve(window.L);
      return;
    }

    // CSS yükle
    if (!document.querySelector('link[href*="leaflet.css"]')) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }

    // JS yükle
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = () => resolve(window.L);
    document.head.appendChild(script);
  });
};

export default function OverviewPage() {
  const mapContainer = useRef(null);
  const mapInstance = useRef(null);
  const markersLayer = useRef(null);
  const rectanglesLayer = useRef(null);
  const [regions, setRegions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [L, setL] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [language, setLanguage] = useState(getLanguage());
  const tr = language === "Turkish";

  useEffect(() => {
    const handler = () => setLanguage(getLanguage());
    window.addEventListener(environmentEventName(), handler);
    return () => window.removeEventListener(environmentEventName(), handler);
  }, []);

  useEffect(() => {
    loadLeaflet().then((leaflet) => {
      setL(leaflet);
      initializeMap(leaflet);
      fetchRegions();
      fetchSystemStatus();
    });
  }, []);

  useEffect(() => {
    const id = setInterval(fetchSystemStatus, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (L && mapInstance.current && regions.length > 0) {
      renderRegionsOnMap();
    }
  }, [regions, L, systemStatus]);

  const initializeMap = (leaflet) => {
    if (!mapContainer.current || mapInstance.current) return;

    const map = leaflet.map(mapContainer.current).setView([39.92, 32.85], 12);

    leaflet
      .tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap",
        maxZoom: 19,
      })
      .addTo(map);

    markersLayer.current = leaflet.layerGroup().addTo(map);
    rectanglesLayer.current = leaflet.layerGroup().addTo(map);

    mapInstance.current = map;
  };

  const fetchRegions = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchJson("/regions");
      setRegions(data.regions || []);
    } catch (err) {
      setError(null);
      setRegions([]);
      console.error("Error fetching regions:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchSystemStatus = async () => {
    try {
      const data = await fetchJson("/system/status");
      setSystemStatus(data.status || null);
    } catch (err) {
      console.error("Error fetching system status:", err);
    }
  };

  const isRegionRunning = (regionId) => {
    const status = systemStatus || {};
    const allRunning =
      !!status.greenwave_api?.running &&
      !!status.camera_detection?.running &&
      !!status.algorithm_sumo?.running;
    return allRunning && Number(status.active_region_id) === Number(regionId);
  };

  useEffect(() => {
    window.__gwToggleRegionSystem = async (regionId) => {
      const running = isRegionRunning(regionId);
      try {
        if (running) {
          await fetchJson("/system/stop", { method: "POST" });
        } else {
          await fetchJson("/system/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              region_id: regionId,
              junction_id: String(regionId),
              camera_video: "0",
              camera_model: "yolov8s.pt",
            }),
          });
        }
        await fetchSystemStatus();
      } catch (err) {
        console.error("Error toggling region system:", err);
        alert(tr ? "Sistem durumu güncellenemedi. Backend loglarını kontrol edin." : "Failed to update system state. Check backend logs.");
      }
    };
    return () => {
      delete window.__gwToggleRegionSystem;
    };
  }, [systemStatus, tr]);

  const getRegionCenter = (region) => {
    const centerLat = (region.min_lat + region.max_lat) / 2;
    const centerLon = (region.min_lon + region.max_lon) / 2;
    return [centerLat, centerLon];
  };

 const createCustomMarker = () => {
  const html = `
    <div style="
        width: 52px;
        height: 52px;
        display: flex;
        align-items: center;
        justify-content: center;
    ">
        <img 
          src="${logo}" 
          style="
            width: 42px;
            height: 42px;
            object-fit: contain;
            filter: drop-shadow(0 2px 6px rgba(0,0,0,0.25));
          "
        />
    </div>
  `;

  return L.divIcon({
    html,
    iconSize: [52, 52],
    iconAnchor: [26, 26],
    popupAnchor: [0, -26],
    className: "custom-marker"
  });
};
  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString("tr-TR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const renderRegionsOnMap = () => {
    if (!mapInstance.current || !L) return;

    // Clear existing layers
    markersLayer.current.clearLayers();
    rectanglesLayer.current.clearLayers();

    regions.forEach((region) => {
      const center = getRegionCenter(region);

      // Draw rectangle bounds
      const rectangle = L.rectangle(
        [
          [region.min_lat, region.min_lon],
          [region.max_lat, region.max_lon],
        ],
        {
          color: "#2563eb",
          weight: 2,
          opacity: 0.3,
          fillColor: "#2563eb",
          fillOpacity: 0.08,
        }
      );
      rectanglesLayer.current.addLayer(rectangle);

      // Add marker at center
      const marker = L.marker(center, {
        icon: createCustomMarker(),
      });

      // Create popup content
      const popupContent = `
        <div style="min-width: 200px; font-size: 13px;">
          <strong style="font-size: 14px; color: #18212f; display: block; margin-bottom: 8px;">
            ${region.name}
          </strong>
          <div style="color: #556377; line-height: 1.6;">
            <div><strong>ID:</strong> ${region.id}</div>
            <div><strong>${tr ? "Oluşturulma:" : "Created:"}</strong> ${formatDate(region.createdAt)}</div>
            <div style="margin-top: 8px;">
              <strong>${tr ? "Sınırlar:" : "Bounds:"}</strong><br/>
              <code style="background: #f0f5ff; padding: 4px 6px; border-radius: 4px; font-size: 11px; display: block; word-break: break-all;">
                (${region.min_lat.toFixed(4)}, ${region.min_lon.toFixed(4)}) to (${region.max_lat.toFixed(4)}, ${region.max_lon.toFixed(4)})
              </code>
            </div>
            <div style="margin-top: 14px; text-align: center;">
              <button type="button" class="popup-details-btn" onclick="window.location.href='/region/${region.id}/dashboard'">${tr ? "İstatistik" : "See stats"}</button>
              <button type="button" class="popup-edit-btn" onclick="window.location.href='/editor?regionId=${region.id}&min_lat=${region.min_lat}&min_lon=${region.min_lon}&max_lat=${region.max_lat}&max_lon=${region.max_lon}&regionName=${encodeURIComponent(region.name || "")}'">${tr ? "Sistemi düzenle" : "Edit system"}</button>
              <button type="button" class="${isRegionRunning(region.id) ? "popup-stop-btn" : "popup-start-btn"}" onclick="window.__gwToggleRegionSystem(${region.id})">${isRegionRunning(region.id) ? (tr ? "Durdur" : "Stop") : (tr ? "Başlat" : "Start")}</button>
            </div>
          </div>
      `;

      marker.bindPopup(popupContent, {
        maxWidth: 300,
        className: "region-popup",
      });

      marker.on("click", () => {
        mapInstance.current.setView(center, 14);
      });

      markersLayer.current.addLayer(marker);
    });
  };

  return (
    <div className="overview-container">
      <div className="overview-header">
        <div className="header-intro">
          <h1 className="page-title">{tr ? "Bölge Görünümü" : "Region Overview"}</h1>
          <p className="page-subtitle">{tr ? "Bir bölge işaretçisine tıklayıp İstatistik veya Sistemi düzenle seçin." : "Click a region marker and choose See stats or Edit system."}</p>
          <div className="system-actions">
            <span className="system-status-text">
              {tr ? "Aktif Bölge" : "Active Region"}: {systemStatus?.active_region_id || "-"} | API: {systemStatus?.greenwave_api?.running ? "ON" : "OFF"} | {tr ? "Kamera" : "Camera"}: {systemStatus?.camera_detection?.running ? "ON" : "OFF"} | SUMO: {systemStatus?.algorithm_sumo?.running ? "ON" : "OFF"}
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ Error loading regions: {error}</span>
        </div>
      )}

      {loading && (
        <div className="loading-overlay">
          <div className="spinner"></div>
          <p>{tr ? "Bölgeler yükleniyor..." : "Loading regions..."}</p>
        </div>
      )}

      <div className="map-wrapper" ref={mapContainer}></div>
      <div className="regions-list-section">
        <div className="regions-list-header">
          <h2>{tr ? "Bölgeler Listesi" : "Regions List"}</h2>
          <span>{regions.length} {tr ? "adet" : "total"}</span>
        </div>
        {regions.length === 0 ? (
          <div className="regions-empty">{tr ? "Bölge bulunamadı." : "No regions found."}</div>
        ) : (
          <div className="regions-list">
            {regions.map((region) => (
              <div className="region-row" key={region.id}>
                <div className="region-main">
                  <strong>{region.name}</strong>
                  <span>ID: {region.id}</span>
                  <span>{region.address || (tr ? "Adres yok" : "No address")}</span>
                </div>
                <div className="region-actions">
                  <button
                    type="button"
                    className="row-btn info"
                    onClick={() => (window.location.href = `/region/${region.id}/dashboard`)}
                  >
                    {tr ? "İstatistik" : "See stats"}
                  </button>
                  <button
                    type="button"
                    className="row-btn edit"
                    onClick={() =>
                      (window.location.href = `/editor?regionId=${region.id}&min_lat=${region.min_lat}&min_lon=${region.min_lon}&max_lat=${region.max_lat}&max_lon=${region.max_lon}&regionName=${encodeURIComponent(region.name || "")}`)
                    }
                  >
                    {tr ? "Düzenle" : "Edit"}
                  </button>
                  <button
                    type="button"
                    className={`row-btn ${isRegionRunning(region.id) ? "stop" : "start"}`}
                    onClick={() => window.__gwToggleRegionSystem(region.id)}
                  >
                    {isRegionRunning(region.id) ? (tr ? "Durdur" : "Stop") : (tr ? "Başlat" : "Start")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style jsx>{`
        .overview-container {
          width: 100%;
          height: 100%;
          display: flex;
          flex-direction: column;
          position: relative;
          min-height: calc(100vh - 200px);
        }

        .overview-header {
          padding: 24px;
          border-bottom: 1px solid #e0e7f1;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          text-align: flex-start;
          gap: 16px;
        }

        .header-content {
          width: 100%;
          max-width: 900px;
        }

        .header-stats {
          display: flex;
          gap: 12px;
          justify-content: flex-end;
          width: 100%;
        }

        .page-title {
          font-size: 28px;
          font-weight: 700;
          color: #18212f;
          margin: 0 0 8px 0;
        }

        .page-subtitle {
          font-size: 14px;
          color: #556377;
          margin: 0;
        }

        .system-actions {
          margin-top: 12px;
          display: flex;
          gap: 8px;
          align-items: center;
          flex-wrap: wrap;
        }

        .system-start,
        .system-stop {
          border: none;
          border-radius: 8px;
          padding: 9px 12px;
          font-weight: 700;
          cursor: pointer;
        }

        .system-start {
          background: #0b7a2f;
          color: #fff;
        }

        .system-stop {
          background: #c62828;
          color: #fff;
        }

        .system-status-text {
          font-size: 13px;
          color: #445266;
          font-weight: 600;
        }

        .header-stats {
          display: flex;
          gap: 12px;
        }

        .stat-card {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 12px 20px;
          background: white;
          border: 1px solid #e0e7f1;
          border-radius: 12px;
        }

        .stat-value {
          font-size: 24px;
          font-weight: 700;
          color: #2563eb;
        }

        .stat-label {
          font-size: 12px;
          color: #556377;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .error-banner {
          background-color: rgba(239, 68, 68, 0.1);
          border-bottom: 1px solid rgba(239, 68, 68, 0.3);
          padding: 12px 24px;
          color: #991b1b;
          font-size: 14px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .loading-overlay {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(255, 255, 255, 0.9);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 16px;
          z-index: 100;
          color: #556377;
        }

        .spinner {
          width: 40px;
          height: 40px;
          border: 4px solid rgba(37, 99, 235, 0.2);
          border-top-color: #2563eb;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }

        .map-wrapper {
          flex: 0 0 auto;
          position: relative;
          width: 100%;
          min-height: 340px;
          height: 46vh;
          max-height: 520px;
          border-radius: 12px;
          overflow: hidden;
          border: 1px solid #e0e7f1;
          margin-bottom: 16px;
        }
        .regions-list-section {
          background: #fff;
          border: 1px solid #e0e7f1;
          border-radius: 12px;
          padding: 14px;
          margin-bottom: 18px;
        }
        .regions-list-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 10px;
        }
        .regions-list-header h2 {
          margin: 0;
          font-size: 18px;
          color: #18212f;
        }
        .regions-list-header span {
          color: #556377;
          font-size: 13px;
          font-weight: 600;
        }
        .regions-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 320px;
          overflow: auto;
        }
        .regions-empty {
          color: #556377;
          font-size: 14px;
        }
        .region-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          border: 1px solid #edf2fb;
          border-radius: 10px;
          padding: 10px 12px;
        }
        .region-main {
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
        }
        .region-main strong {
          color: #18212f;
          font-size: 14px;
        }
        .region-main span {
          color: #556377;
          font-size: 12px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 540px;
        }
        .region-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-shrink: 0;
        }
        .row-btn {
          border: none;
          border-radius: 999px;
          padding: 8px 12px;
          color: #fff;
          font-weight: 700;
          cursor: pointer;
          font-size: 12px;
        }
        .row-btn.info { background: #1d4ed8; }
        .row-btn.edit { background: #334155; }
        .row-btn.start { background: #0b7a2f; }
        .row-btn.stop { background: #c62828; }

        .button-panel {
          display: flex;
          gap: 10px;
          margin-bottom: 20px;
          justify-content: center;
        }

        .button-panel.centered {
          justify-content: center;
        }

        .button-panel .primary-button, {
          width: 100%;
          padding: 12px 14px;
          border: none;
          border-radius: 12px;
          font-weight: 700;
          cursor: pointer;
        }



        .button-panel .primary-button {
          background: #0d631b;
          color: white;
        }

       
        

.button-panel .primary-button, {
  width: 100%;
  padding: 12px 14px;
  border: none;
  border-radius: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: 0.2s ease;
}

        .button-panel .primary-button:hover {
  background: #003008;
}



        .selected-region-panel {
          width: 100%;
          max-width: 1100px;
          margin: 20px auto;
          background: white;
          border-radius: 20px;
          box-shadow: 0 16px 50px rgba(25, 52, 98, 0.08);
          border: 1px solid #e0e7f1;
          overflow: hidden;
          animation: slideIn 0.2s ease;
        }

        @keyframes slideIn {
          from {
            transform: translateY(12px);
            opacity: 0;
          }
          to {
            transform: translateY(0);
            opacity: 1;
          }
        }

        .selected-region-panel .sidebar-content {
          padding: 24px;
        }

        .panel-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 18px;
          margin-bottom: 20px;
        }

        .panel-note {
          margin: 8px 0 0;
          color: #556377;
          font-size: 13px;
        }

        .info-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 16px;
        }

        @media (max-width: 820px) {
          .info-grid {
            grid-template-columns: 1fr;
          }

          .panel-header {
            flex-direction: column;
            align-items: stretch;
          }

          .overview-header {
            align-items: center;
          }
        }

        .close-sidebar {
          position: absolute;
          top: 12px;
          right: 12px;
          background: rgba(15, 23, 42, 0.08);
          border: none;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 18px;
          color: #556377;
          transition: all 0.2s ease;
          z-index: 10;
        }

        .close-sidebar:hover {
          background: rgba(15, 23, 42, 0.12);
          color: #18212f;
        }

        .sidebar-content {
          padding: 20px;
          overflow-y: auto;
          max-height: 500px;
        }

        .sidebar-title {
          font-size: 18px;
          font-weight: 700;
          color: #18212f;
          margin: 0 0 16px 0;
          word-break: break-word;
        }

        .info-group {
          margin-bottom: 16px;
          padding-bottom: 16px;
          border-bottom: 1px solid #f0f5ff;
        }

        .info-group:last-child {
          margin-bottom: 0;
          padding-bottom: 0;
          border-bottom: none;
        }

        .info-group label {
          display: block;
          font-size: 12px;
          font-weight: 600;
          color: #556377;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 6px;
        }

        .info-value {
          font-size: 14px;
          color: #18212f;
          font-family: "Courier New", monospace;
          background: #f8faff;
          padding: 8px 10px;
          border-radius: 6px;
          word-break: break-all;
        }

        :global(.region-popup .leaflet-popup-content) {
          font-family: "Segoe UI", sans-serif;
          margin: 0 !important;
        }

        :global(.region-popup .leaflet-popup-content-wrapper) {
          border-radius: 12px;
          box-shadow: 0 8px 24px rgba(25, 52, 98, 0.16) !important;
        }

        :global(.region-popup .popup-details-btn) {
          width: 100%;
          max-width: 220px;
          border: 1px solid rgba(37, 99, 235, 0.15);
          border-radius: 999px;
          padding: 10px 18px;
          background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
          color: white;
          cursor: pointer;
          font-weight: 700;
          letter-spacing: 0.01em;
          box-shadow: 0 10px 20px rgba(37, 99, 235, 0.24);
          transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;
          margin-bottom: 8px;
        }

        :global(.region-popup .popup-details-btn:hover) {
          transform: translateY(-1px) scale(1.01);
          box-shadow: 0 14px 24px rgba(37, 99, 235, 0.3);
          filter: brightness(1.04);
        }

        :global(.region-popup .popup-edit-btn) {
          width: 100%;
          max-width: 220px;
          border: 1px solid #d6d9de;
          border-radius: 999px;
          padding: 10px 18px;
          background: #ffffff;
          color: #1f2937;
          cursor: pointer;
          font-weight: 700;
        }

        :global(.region-popup .popup-start-btn),
        :global(.region-popup .popup-stop-btn) {
          width: 100%;
          max-width: 220px;
          border: none;
          border-radius: 999px;
          padding: 10px 18px;
          color: #fff;
          cursor: pointer;
          font-weight: 700;
          margin-top: 8px;
        }

        :global(.region-popup .popup-start-btn) {
          background: #0b7a2f;
        }

        :global(.region-popup .popup-stop-btn) {
          background: #c62828;
        }

        @media (max-width: 768px) {
          .overview-header {
            padding: 18px 16px;
            align-items: flex-start;
          }

          .map-wrapper {
            min-height: 280px;
            height: 36vh;
            border-radius: 10px;
          }
          .region-row {
            flex-direction: column;
            align-items: flex-start;
          }
          .region-actions {
            width: 100%;
            flex-wrap: wrap;
          }

          .selected-region-panel {
            width: calc(100% - 32px);
            max-height: calc(100vh - 300px);
          }
        }
      `}</style>
    </div>
  );
}
