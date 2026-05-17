import { useNavigate } from "react-router-dom";
import { FaUser } from "react-icons/fa";


export default function SettingsPage() {
  const navigate = useNavigate();

  return (
    <div className="page-stack">
      <article className="card profile-card">
          <div className="profile-avatar"><FaUser /></div>
          <h2>Admin Root</h2>
      </article>
    
      <section className="settings-grid two-col">
        

        <article className="card">
          <div className="section-heading compact">
            <h2>Security & Access</h2>
          </div>

          <div className="form-stack">
            <label className="field">
              <span>Current Password</span>
              <div className="field-control">
                <span className="material-symbols-outlined">lock</span>
                <input defaultValue="••••••••••••" type="password" />
              </div>
            </label>
            <label className="field">
              <span>New Password</span>
              <div className="field-control">
                <span className="material-symbols-outlined">lock</span>
                <input defaultValue="••••••••••••" type="password" />
              </div>
            </label>
            <label className="field">
              <span>Confirm Password</span>
              <div className="field-control">
                <span className="material-symbols-outlined">lock</span>
                <input defaultValue="••••••••••••" type="password" />
              </div>
            </label>

            <button className="primary-button" type="button">Update Password</button>

            <button className="secondary-button" type="button" onClick={() => navigate("/login")}>Logout</button>
          </div>
        </article>

        <section className="settings-grid">

          <article className="card full-span">
            <div className="section-heading compact">
              <h2>Environment Controls</h2>
            </div>

            <div className="settings-form-grid">
              <div>
                <label className="field-label">Appearance</label>
                <div className="segmented-control">
                  <button className="segment active" type="button">Light</button>
                  <button className="segment" type="button">Dark</button>
                </div>
              </div>
              <div>
                <label className="field-label">System Language</label>
                <select className="select-control" defaultValue="English (US)">
                  <option>English (US)</option>
                  <option>Turkish</option>
                </select>
              </div>
            </div>
          </article>
        </section>

      </section>


    </div>
  );
}
