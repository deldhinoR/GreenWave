import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import AnalyticsPage from "./pages/AnalyticsPage";
import DashboardPage from "./pages/DashboardPage";
import RuntimeMonitorPage from "./pages/RuntimeMonitorPage";
import EditorPage from "./pages/EditorPage";
import CameraSetupPage from "./pages/CameraSetupPage";
import LoginPage from "./pages/LoginPage";
import LogsPage from "./pages/LogsPage";
import SettingsPage from "./pages/SettingsPage";
import RegisteredIntersections from "./pages/RegisteredIntersections";
import OverviewPage from "./pages/OverviewPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/region/:regionId/dashboard" element={<DashboardPage />} />
        <Route path="/region/:regionId/runtime" element={<RuntimeMonitorPage />} />
        <Route path="/region/:regionId/analytics" element={<AnalyticsPage />} />
        <Route path="/region/:regionId/logs" element={<LogsPage />} />
        <Route path="/editor" element={<EditorPage />} />
        <Route path="/camera-setup" element={<CameraSetupPage />} />
        <Route path="/registered-intersections" element={<RegisteredIntersections />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  );
}
