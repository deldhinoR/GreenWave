import { Link } from "react-router-dom";
import logo from "../assets/logo.svg";


function Icon({ name, className = "" }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

export default function LoginPage() {
  return (
    <div className="login-page">
      <div className="login-orb orb-left" />
      <div className="login-orb orb-right" />

      <section className="login-card">
        <div className="login-brand">
        <img src={logo} className="h-10 w-auto" 
        style={{ height: "130px", width: "auto" }}/>
        </div>

        <div className="card">
          <header className="section-heading">
            <h2>Administrator login</h2>
            <p>Authorized access to city grid management and signal orchestration.</p>
          </header>

          <div className="form-stack">
            <label className="field">
              <span>System Username</span>
              <div className="field-control">
                <Icon name="account_circle" />
                <input defaultValue="admin_green_01" />
              </div>
            </label>

            <label className="field">
              <span>Access Token</span>
              <div className="field-control">
                <Icon name="lock" />
                <input defaultValue="••••••••••••" type="password" />
                <button className="field-action" type="button">
                  <Icon name="visibility" />
                </button>
              </div>
            </label>

            <div className="inline-row">
              <div className="toggle">
                <div className="toggle-thumb" />
              </div>
              <span>Persistent session (30 days)</span>
            </div>

            <Link className="primary-button wide" to="/overview">
              <span>Initialize System Access</span>
              <Icon name="arrow_forward" />
            </Link>
          </div>

          <footer className="login-footer">
            <div className="inline-row muted">
              <Icon name="shield_with_heart" />
              <span>ISO 27001 certified security infrastructure</span>
            </div>
            <div className="inline-links">
              <a href="/">Security Policy</a>
              <a href="/">Terminal Log</a>
              <a href="/">Support</a>
            </div>
          </footer>
        </div>

        <div className="system-pulse">
          <span className="pulse-dot" />
          <span>SYSTEM NODE #882: OPTIMIZED TRAFFIC FLOW ACTIVE</span>
        </div>
      </section>
    </div>
  );
}
