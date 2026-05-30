import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FaUser } from "react-icons/fa";
import { fetchJson } from "../lib/api";
import { clearAuthentication } from "../lib/auth";
import { applyEnvironment, environmentEventName, getLanguage } from "../lib/environment";

export default function SettingsPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("Admin");
  const [theme, setTheme] = useState("light");
  const [language, setLanguage] = useState("English (US)");
  const [uiLanguage, setUiLanguage] = useState(getLanguage());
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const t = uiLanguage === "Turkish"
    ? {
        security: "Güvenlik ve Erişim",
        currentPassword: "Mevcut Şifre",
        newPassword: "Yeni Şifre",
        confirmPassword: "Şifreyi Onayla",
        updatePassword: "Şifreyi Güncelle",
        logout: "Çıkış Yap",
        environment: "Ortam Kontrolleri",
        appearance: "Görünüm",
        systemLanguage: "Sistem Dili",
        saveEnvironment: "Ortamı Kaydet",
        envUpdated: "Ortam ayarları güncellendi.",
        passUpdated: "Şifre güncellendi.",
        mismatch: "Yeni şifre ve onay şifresi eşleşmiyor.",
        loadFailed: "Ayarlar yüklenemedi.",
        saveFailed: "Ayarlar kaydedilemedi.",
        passFailed: "Şifre güncellenemedi.",
      }
    : {
        security: "Security & Access",
        currentPassword: "Current Password",
        newPassword: "New Password",
        confirmPassword: "Confirm Password",
        updatePassword: "Update Password",
        logout: "Logout",
        environment: "Environment Controls",
        appearance: "Appearance",
        systemLanguage: "System Language",
        saveEnvironment: "Save Environment",
        envUpdated: "Environment settings updated.",
        passUpdated: "Password updated.",
        mismatch: "New password and confirm password do not match.",
        loadFailed: "Failed to load settings.",
        saveFailed: "Failed to save settings.",
        passFailed: "Failed to update password.",
      };

  useEffect(() => {
    const handler = () => setUiLanguage(getLanguage());
    window.addEventListener(environmentEventName(), handler);
    return () => window.removeEventListener(environmentEventName(), handler);
  }, []);

  useEffect(() => {
    fetchJson("/settings/me")
      .then((data) => {
        setUsername(data.username || "Admin");
        setTheme((data.theme || "light").toLowerCase());
        setLanguage(data.language || "English (US)");
        applyEnvironment((data.theme || "light").toLowerCase(), data.language || "English (US)");
      })
      .catch(() => {
        setError(t.loadFailed);
      });
  }, [t.loadFailed]);

  const saveEnvironment = async () => {
    setError("");
    setMessage("");
    try {
      await fetchJson("/settings/me", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme, language }),
      });
      applyEnvironment(theme, language);
      setMessage(t.envUpdated);
    } catch (err) {
      setError(err.message || t.saveFailed);
    }
  };

  const updatePassword = async () => {
    setError("");
    setMessage("");
    if (newPassword !== confirmPassword) {
      setError(t.mismatch);
      return;
    }
    try {
      await fetchJson("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currentPassword, newPassword }),
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage(t.passUpdated);
    } catch (err) {
      setError(err.message || t.passFailed);
    }
  };

  const logout = async () => {
    try {
      await fetchJson("/auth/logout", { method: "POST" });
    } catch (_err) {
      // ignore logout errors and clear client auth anyway
    } finally {
      clearAuthentication();
      navigate("/login", { replace: true });
    }
  };

  return (
    <div className="page-stack">
      <article className="card profile-card">
        <div className="profile-avatar"><FaUser /></div>
        <h2>{username}</h2>
      </article>

      <section className="settings-grid two-col">
        <article className="card">
          <div className="section-heading compact">
            <h2>{t.security}</h2>
          </div>

          <div className="form-stack">
            <label className="field">
              <span>{t.currentPassword}</span>
              <div className="field-control">
                <span className="material-symbols-outlined">lock</span>
                <input value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} type="password" />
              </div>
            </label>
            <label className="field">
              <span>{t.newPassword}</span>
              <div className="field-control">
                <span className="material-symbols-outlined">lock</span>
                <input value={newPassword} onChange={(e) => setNewPassword(e.target.value)} type="password" />
              </div>
            </label>
            <label className="field">
              <span>{t.confirmPassword}</span>
              <div className="field-control">
                <span className="material-symbols-outlined">lock</span>
                <input value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} type="password" />
              </div>
            </label>

            <button className="primary-button" type="button" onClick={updatePassword}>{t.updatePassword}</button>
            <button className="secondary-button" type="button" onClick={logout}>{t.logout}</button>
          </div>
        </article>

        <section className="settings-grid">
          <article className="card full-span">
            <div className="section-heading compact">
              <h2>{t.environment}</h2>
            </div>

            <div className="settings-form-grid">
              <div>
                <label className="field-label">{t.appearance}</label>
                <div className="segmented-control">
                  <button className={`segment ${theme === "light" ? "active" : ""}`} type="button" onClick={() => setTheme("light")}>Light</button>
                  <button className={`segment ${theme === "dark" ? "active" : ""}`} type="button" onClick={() => setTheme("dark")}>Dark</button>
                </div>
              </div>
              <div>
                <label className="field-label">{t.systemLanguage}</label>
                <select className="select-control" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option>English (US)</option>
                  <option>Turkish</option>
                </select>
              </div>
            </div>
            <button className="primary-button" type="button" onClick={saveEnvironment}>{t.saveEnvironment}</button>
          </article>
        </section>
      </section>
      {message ? <div style={{ color: "#166534", fontWeight: 600 }}>{message}</div> : null}
      {error ? <div style={{ color: "#b91c1c", fontWeight: 600 }}>{error}</div> : null}
    </div>
  );
}
