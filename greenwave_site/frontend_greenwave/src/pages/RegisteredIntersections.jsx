import { useEffect, useState } from "react";
import { fetchJson } from "../lib/api";

export default function RegisteredIntersections() {
  const [regions, setRegions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  useEffect(() => {
    fetchRegions();
  }, []);

  const fetchRegions = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchJson("/regions");
      setRegions(data.regions || []);
    } catch (err) {
      setError(err.message);
      console.error("Error fetching regions:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteRegion = async (regionId) => {
    try {
      await fetchJson(`/regions/${regionId}`, {
        method: "DELETE",
      });

      // Remove the region from the local state
      setRegions(regions.filter(region => region.id !== regionId));
      setDeleteConfirm(null);
    } catch (err) {
      setError(err.message);
      console.error("Error deleting region:", err);
    }
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString("tr-TR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const formatLocationAddress = (region) => {
    return `(${region.min_lat.toFixed(4)}, ${region.min_lon.toFixed(4)}) - (${region.max_lat.toFixed(4)}, ${region.max_lon.toFixed(4)})`;
  };

  return (
    <div className="page-content">
      <div className="page-header">
        <h1 className="page-title">Registered Regions</h1>
        <p className="page-subtitle">All saved intersection regions from SUMO project exports</p>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ Error loading regions: {error}</span>
        </div>
      )}

      {loading ? (
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading regions...</p>
        </div>
      ) : regions.length === 0 ? (
        <div className="empty-state">
          <span className="material-symbols-outlined empty-icon">location_off</span>
          <h3>No Regions Found</h3>
          <p>No saved regions yet. Create a SUMO project from the Editor to register a region.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Region Name (Cache Key)</th>
                <th>Created At</th>
                <th>Location Bounds</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {regions.map((region) => (
                <tr key={region.id}>
                  <td className="id-cell">{region.id}</td>
                  <td className="name-cell">
                    <span className="region-name">{region.name}</span>
                  </td>
                  <td className="date-cell">{formatDate(region.createdAt)}</td>
                  <td className="location-cell">
                    <code className="location-code">{formatLocationAddress(region)}</code>
                  </td>
                  <td className="actions-cell">
                    <button 
                      className="delete-button"
                      onClick={() => setDeleteConfirm(region)}
                      title="Delete Region"
                    >
                      <span className="material-symbols-outlined">delete</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteConfirm && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3>Delete Region</h3>
              <button 
                className="close-modal"
                onClick={() => setDeleteConfirm(null)}
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="modal-body">
              <p>Are you sure you want to delete the region <strong>"{deleteConfirm.name}"</strong>?</p>
              <p className="warning-text">This action cannot be undone.</p>
            </div>
            <div className="modal-footer">
              <button 
                className="cancel-button"
                onClick={() => setDeleteConfirm(null)}
              >
                Cancel
              </button>
              <button 
                className="confirm-delete-button"
                onClick={() => handleDeleteRegion(deleteConfirm.id)}
              >
                Yes, Delete
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .page-content {
          padding: 24px;
          min-height: 100%;
        }

        .page-header {
          margin-bottom: 32px;
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

        .error-banner {
          background-color: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 12px;
          padding: 12px 16px;
          margin-bottom: 20px;
          color: #991b1b;
          font-size: 14px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .loading-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 60px 20px;
          gap: 16px;
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

        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 60px 20px;
          text-align: center;
          color: #556377;
        }

        .empty-icon {
          font-size: 48px;
          color: #b8c7e4;
          margin-bottom: 16px;
        }

        .empty-state h3 {
          font-size: 20px;
          font-weight: 600;
          color: #18212f;
          margin: 0 0 8px 0;
        }

        .empty-state p {
          font-size: 14px;
          margin: 0;
        }

        .table-wrapper {
          border-radius: 16px;
          box-shadow: 0 2px 8px rgba(25, 52, 98, 0.08);
          overflow: hidden;
          border: 1px solid #e0e7f1;
        }

        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 14px;
        }

        .data-table thead {
          background: linear-gradient(135deg, #f0f5ff 0%, #f8faff 100%);
          border-bottom: 2px solid #e0e7f1;
        }

        .data-table th {
          padding: 16px;
          text-align: left;
          font-weight: 600;
          color: #18212f;
          letter-spacing: 0.5px;
        }

        .data-table tbody tr {
          border-bottom: 1px solid #f0f5ff;
          transition: background-color 0.2s ease;
        }

        .data-table tbody tr:hover {
          background-color: #f8faff;
        }

        .data-table tbody tr:last-child {
          border-bottom: none;
        }

        .data-table td {
          padding: 14px 16px;
          color: #556377;
        }

        .id-cell {
          font-weight: 600;
          color: #2563eb;
          font-family: "Courier New", monospace;
          font-size: 13px;
        }

        .name-cell {
          max-width: 200px;
          word-break: break-word;
        }

        .region-name {
          display: inline-block;
          background: rgba(37, 99, 235, 0.08);
          padding: 4px 8px;
          border-radius: 6px;
          color: #1e40af;
          font-family: "Courier New", monospace;
          font-size: 13px;
        }

        .date-cell {
          font-family: "Courier New", monospace;
          font-size: 13px;
          color: #18212f;
          white-space: nowrap;
        }

        .location-cell {
          max-width: 350px;
        }

        .location-code {
          display: block;
          background: rgba(15, 23, 42, 0.04);
          padding: 8px 12px;
          border-radius: 8px;
          font-family: "Courier New", monospace;
          font-size: 12px;
          color: #0f172a;
          word-break: break-all;
        }

        .actions-cell {
          text-align: center;
          width: 80px;
        }

        .delete-button {
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 8px;
          padding: 8px;
          cursor: pointer;
          color: #dc2626;
          transition: all 0.2s ease;
        }

        .delete-button:hover {
          background: #dc2626;
          color: #ffffff;
          border-color: #dc2626;
          transform: translateY(-1px);
        }

        .delete-button .material-symbols-outlined {
          font-size: 18px;
        }

        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .modal-content {
          background: white;
          border-radius: 16px;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
          max-width: 400px;
          width: 90%;
          overflow: hidden;
        }

        .modal-header {
          padding: 20px 24px;
          border-bottom: 1px solid #e0e7f1;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .modal-header h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
          color: #18212f;
        }

        .close-modal {
          background: none;
          border: none;
          cursor: pointer;
          color: #556377;
          padding: 4px;
          border-radius: 50%;
          transition: background-color 0.2s ease;
        }

        .close-modal:hover {
          background: rgba(85, 99, 119, 0.18);
          color: #18212f;
        }

        .modal-body {
          padding: 24px;
        }

        .modal-body p {
          margin: 0 0 8px 0;
          color: #556377;
          line-height: 1.5;
        }

        .warning-text {
          color: #dc2626;
          font-weight: 500;
        }

        .modal-footer {
          padding: 16px 24px 24px;
          border-top: 1px solid #e0e7f1;
          display: flex;
          gap: 12px;
          justify-content: flex-end;
        }

        .cancel-button {
          background: #f3f4f6;
          color: #374151;
          border: 1px solid #d1d5db;
          border-radius: 8px;
          padding: 10px 16px;
          cursor: pointer;
          font-weight: 500;
          transition: all 0.2s ease;
        }

        .cancel-button:hover {
          background: #d1d5db;
          color: #111827;
        }

        .confirm-delete-button {
          background: #dc2626;
          color: white;
          border: 1px solid #dc2626;
          border-radius: 8px;
          padding: 10px 16px;
          cursor: pointer;
          font-weight: 500;
          transition: all 0.2s ease;
        }

        .confirm-delete-button:hover {
          background: #b91c1c;
          border-color: #b91c1c;
        }

        @media (max-width: 1024px) {
          .page-content {
            padding: 16px;
          }

          .table-wrapper {
            overflow-x: auto;
          }

          .data-table {
            min-width: 900px;
          }
        }

        @media (max-width: 768px) {
          .page-header {
            margin-bottom: 20px;
          }

          .page-title {
            font-size: 24px;
          }

          .modal-content {
            width: calc(100% - 24px);
          }

          .modal-header,
          .modal-body,
          .modal-footer {
            padding-left: 16px;
            padding-right: 16px;
          }

          .modal-footer {
            flex-direction: column-reverse;
          }

          .cancel-button,
          .confirm-delete-button {
            width: 100%;
          }
        }
      `}</style>
    </div>
  );
}
