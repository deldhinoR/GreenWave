import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import logo from "../assets/logo.svg";
import { fetchJson } from "../lib/api";

import { FaUser } from "react-icons/fa";

function Icon({ name, className = "" }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

const navItems = [
  { path: "/overview", label: "Overview", icon: "map" },
  { path: "/editor", label: "Editor", icon: "edit_road" },
  { path: "/registered-intersections", label: "Registered Regions", icon: "location_on" },
  { path: "/settings", label: "Settings", icon: "settings" },
];

const pageMeta = {
  "/overview": { title: "Overview", search: "Search regions..." },
  "/dashboard": { title: "Operations Dashboard", search: "Search grid nodes..." },
  "/logs": { title: "System Events", search: "Search events or intersections..." },
  "/analytics": { title: "Grid Intelligence", search: "Search analytics..." },
  "/editor": { title: "Signal Editor", search: "Search intersections..." },
  "/camera-setup": { title: "Camera Setup", search: "Search camera or road..." },
  "/registered-intersections": { title: "Registered Regions", search: "Search regions..." },
  "/settings": { title: "System Settings", search: "Search settings..." },
};

export default function AppLayout() {
  const [navOpen, setNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchFocused, setSearchFocused] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [searchRegions, setSearchRegions] = useState([]);
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

  const meta = useMemo(() => {
    if (location.pathname.startsWith("/region/")) {
      if (location.pathname.includes("/dashboard")) {
        return { title: "Intersection Dashboard", search: "Search intersection dashboard..." };
      }
      if (location.pathname.includes("/analytics")) {
        return { title: "Intersection Analytics", search: "Search intersection analytics..." };
      }
      if (location.pathname.includes("/logs")) {
        return { title: "Intersection System Logs", search: "Search intersection logs..." };
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
                  background: "#fff",
                  border: "1px solid #dfe6ef",
                  borderRadius: "12px",
                  boxShadow: "0 10px 28px rgba(18, 31, 53, 0.12)",
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
                      <div style={{ fontSize: "13px", fontWeight: 700, color: "#18212f" }}>{item.name}</div>
                      <div style={{ fontSize: "12px", color: "#637086" }}>{item.address || "No address"}</div>
                    </button>
                  ))
                ) : (
                  <div style={{ padding: "10px 12px", fontSize: "12px", color: "#637086" }}>No results</div>
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
