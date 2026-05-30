import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import logo from "../assets/logo.svg";
import { fetchJson } from "../lib/api";
import { environmentEventName, getLanguage } from "../lib/environment";

import { FaUser } from "react-icons/fa";

function Icon({ name, className = "" }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

const labels = {
  "English (US)": {
    nav: {
      overview: "Overview",
      editor: "Editor",
      regions: "Registered Regions",
      settings: "Settings",
    },
    page: {
      overview: { title: "Overview", search: "Search regions..." },
      dashboard: { title: "Operations Dashboard", search: "Search grid nodes..." },
      logs: { title: "System Events", search: "Search events or intersections..." },
      analytics: { title: "Grid Intelligence", search: "Search analytics..." },
      editor: { title: "Signal Editor", search: "Search intersections..." },
      camera: { title: "Camera Setup", search: "Search camera or road..." },
      regions: { title: "Registered Regions", search: "Search regions..." },
      settings: { title: "System Settings", search: "Search settings..." },
      noResult: "No results",
      noAddress: "No address",
    },
  },
  Turkish: {
    nav: {
      overview: "Genel Bakış",
      editor: "Editör",
      regions: "Kayıtlı Bölgeler",
      settings: "Ayarlar",
    },
    page: {
      overview: { title: "Genel Bakış", search: "Bölge ara..." },
      dashboard: { title: "Operasyon Paneli", search: "Düğüm ara..." },
      logs: { title: "Sistem Kayıtları", search: "Olay veya kavşak ara..." },
      analytics: { title: "Analitik", search: "Analitik ara..." },
      editor: { title: "Sinyal Editörü", search: "Kavşak ara..." },
      camera: { title: "Kamera Kurulumu", search: "Kamera veya yol ara..." },
      regions: { title: "Kayıtlı Bölgeler", search: "Bölge ara..." },
      settings: { title: "Sistem Ayarları", search: "Ayar ara..." },
      noResult: "Sonuç yok",
      noAddress: "Adres yok",
      intersectionDashboard: { title: "Kavşak Paneli", search: "Kavşak panelinde ara..." },
      intersectionAnalytics: { title: "Kavşak Analitiği", search: "Kavşak analitiğinde ara..." },
      intersectionLogs: { title: "Kavşak Sistem Kayıtları", search: "Kavşak kayıtlarında ara..." },
    },
  },
};

export default function AppLayout() {
  const [navOpen, setNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchFocused, setSearchFocused] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [searchRegions, setSearchRegions] = useState([]);
  const [language, setLanguage] = useState(getLanguage());
  const location = useLocation();
  const navigate = useNavigate();
  const isOverview = location.pathname === "/overview";
  const isIntersectionPage = location.pathname.startsWith("/region/");
  const isSearchEnabled = isOverview || isIntersectionPage;
  const searchValue = useMemo(() => {
    if (!isOverview) return searchInput;
    const params = new URLSearchParams(location.search);
    return params.get("q") ?? "";
  }, [isOverview, location.search, searchInput]);

  const l10n = labels[language] || labels["English (US)"];
  const navItems = [
    { path: "/overview", label: l10n.nav.overview, icon: "map" },
    { path: "/editor", label: l10n.nav.editor, icon: "edit_road" },
    { path: "/registered-intersections", label: l10n.nav.regions, icon: "location_on" },
    { path: "/settings", label: l10n.nav.settings, icon: "settings" },
  ];
  const pageMeta = {
    "/overview": l10n.page.overview,
    "/dashboard": l10n.page.dashboard,
    "/logs": l10n.page.logs,
    "/analytics": l10n.page.analytics,
    "/editor": l10n.page.editor,
    "/camera-setup": l10n.page.camera,
    "/registered-intersections": l10n.page.regions,
    "/settings": l10n.page.settings,
  };

  useEffect(() => {
    const handler = () => setLanguage(getLanguage());
    window.addEventListener(environmentEventName(), handler);
    return () => window.removeEventListener(environmentEventName(), handler);
  }, []);

  const meta = useMemo(() => {
    if (location.pathname.startsWith("/region/")) {
      if (location.pathname.includes("/dashboard")) {
        return l10n.page.intersectionDashboard || { title: "Intersection Dashboard", search: "Search intersection dashboard..." };
      }
      if (location.pathname.includes("/analytics")) {
        return l10n.page.intersectionAnalytics || { title: "Intersection Analytics", search: "Search intersection analytics..." };
      }
      if (location.pathname.includes("/logs")) {
        return l10n.page.intersectionLogs || { title: "Intersection System Logs", search: "Search intersection logs..." };
      }
    }
    return pageMeta[location.pathname] ?? pageMeta["/overview"];
  }, [location.pathname]);

  const suggestions = useMemo(() => {
    if (!isSearchEnabled || !searchValue.trim()) return [];
    const q = searchValue.toLowerCase();
    return searchRegions
      .filter((item) => {
        const id = String(item.id || "").toLowerCase();
        const blob = `${item.name || ""} ${item.address || ""} ${id}`.toLowerCase();
        return blob.includes(q);
      })
      .slice(0, 8);
  }, [isSearchEnabled, searchRegions, searchValue]);

  useEffect(() => {
    if (!isSearchEnabled) return;
    fetchJson("/regions")
      .then((data) => setSearchRegions(data.regions || []))
      .catch(() => setSearchRegions([]));
  }, [isSearchEnabled]);

  useEffect(() => {
    if (!isOverview) return;
    const params = new URLSearchParams(location.search);
    setSearchInput(params.get("q") ?? "");
  }, [isOverview, location.search]);

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <button className="mobile-nav-toggle" onClick={() => setNavOpen((value) => !value)} type="button">
        <Icon name="menu" />
      </button>

      <aside className={`sidebar ${navOpen ? "is-open" : ""}`}>
        <img src={logo} className="h-10 w-auto" />
        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              className={({ isActive }) => `nav-item ${isActive ? "is-active" : ""}`}
              onClick={() => setNavOpen(false)}
              to={item.path}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

      </aside>
      <button
        className="sidebar-toggle-desktop"
        type="button"
        onClick={() => setSidebarCollapsed((value) => !value)}
        aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
        title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
      >
        {sidebarCollapsed ? "›" : "‹"}
      </button>

      {navOpen ? <button className="mobile-backdrop" onClick={() => setNavOpen(false)} type="button" /> : null}

      <div className="content-area">
        <header className="topbar">
          <div className="search-wrap" style={{ position: "relative" }}>
            <Icon name="search" className="search-icon" />
            <input
              aria-label="Search"
              placeholder={meta.search}
              value={searchValue}
              onFocus={() => setSearchFocused(true)}
              onBlur={() => setTimeout(() => setSearchFocused(false), 120)}
              onChange={(event) => {
                if (!isSearchEnabled) return;
                const next = event.target.value;
                setSearchInput(next);
                if (!isOverview) return;
                const params = new URLSearchParams(location.search);
                if (next.trim()) {
                  params.set("q", next);
                } else {
                  params.delete("q");
                }
                const qs = params.toString();
                navigate(`${location.pathname}${qs ? `?${qs}` : ""}`, { replace: true });
              }}
            />
            {isSearchEnabled && searchFocused && searchValue.trim() && (
              <div
                style={{
                  position: "absolute",
                  top: "44px",
                  left: 0,
                  width: "100%",
                  background: "var(--surface-card)",
                  border: "1px solid var(--surface-outline)",
                  borderRadius: "12px",
                  boxShadow: "var(--shadow)",
                  zIndex: 4000,
                  maxHeight: "320px",
                  overflowY: "auto",
                }}
              >
                {suggestions.length > 0 ? (
                  suggestions.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        const targetId = String(item.id || "1");
                        setSearchFocused(false);
                        navigate(`/region/${targetId}/dashboard`);
                      }}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        border: "none",
                        background: "transparent",
                        padding: "10px 12px",
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ fontSize: "13px", fontWeight: 700, color: "var(--text)" }}>{item.name}</div>
                  <div style={{ fontSize: "12px", color: "var(--muted)" }}>{item.address || l10n.page.noAddress}</div>
                    </button>
                  ))
                ) : (
                  <div style={{ padding: "10px 12px", fontSize: "12px", color: "var(--muted)" }}>{l10n.page.noResult}</div>
                )}
              </div>
            )}
          </div>

          

          <div className="topbar-actions">
            <div className="profile-pill" role="button" onClick={() => navigate("/settings")}>
              <div className="avatar-circle small">
                <FaUser />
              </div>
              <strong>Admin Root</strong>
            </div>
          </div>
        </header>

        <main className="page-frame">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
