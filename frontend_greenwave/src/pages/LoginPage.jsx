import { useState } from "react";
import { useNavigate } from "react-router-dom";
import logo from "../assets/logo.svg";
import { fetchJson } from "../lib/api";
import { markAuthenticated } from "../lib/auth";
import { getLanguage } from "../lib/environment";

function Icon({ name, className = "" }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const tr = getLanguage() === "Turkish";

  const handleLogin = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await fetchJson("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      markAuthenticated();
      navigate("/overview", { replace: true });
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-orb orb-left" />
      <div className="login-orb orb-right" />

      <section className="login-card">
        <div className="login-brand">
          <img src={logo} className="h-10 w-auto" style={{ height: "130px", width: "auto" }} />
        </div>

        <div className="card">
          <header className="section-heading">
            <h2>{tr ? "Yönetici Girişi" : "Administrator login"}</h2>
            <p>{tr ? "Şehir ızgara yönetimi ve sinyal orkestrasyonu için yetkili erişim." : "Authorized access to city grid management and signal orchestration."}</p>
          </header>

          <form className="form-stack" onSubmit={handleLogin}>
            <label className="field">
              <span>{tr ? "Sistem Kullanıcı Adı" : "System Username"}</span>
              <div className="field-control">
                <Icon name="account_circle" />
                <input value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
            </label>

            <label className="field">
              <span>{tr ? "Şifre" : "Password"}</span>
              <div className="field-control">
                <Icon name="lock" />
                <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" />
              </div>
            </label>

            {error ? <div style={{ color: "#b91c1c", fontSize: "13px" }}>{error}</div> : null}

            <button className="primary-button wide" type="submit" disabled={loading}>
              <span>{loading ? (tr ? "Giriş yapılıyor..." : "Signing in...") : (tr ? "Sistem Erişimini Başlat" : "Initialize System Access")}</span>
              <Icon name="arrow_forward" />
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
