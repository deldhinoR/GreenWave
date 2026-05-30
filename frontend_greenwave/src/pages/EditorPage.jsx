import { useLocation } from "react-router-dom";

export default function EditorPage() {
  const location = useLocation();
  const iframeSrc = `http://127.0.0.1:5000${location.search || ""}`;

  return (
    <div className="page-stack">
      <section className="editor-layout">

        <div className="editor-main">
          <iframe
            src={iframeSrc}
            style={{
              width: "100%",
              height: "78vh",
              minHeight: "760px",
              border: "none",
              borderRadius: "12px"
            }}
          />
        </div>

      </section>
    </div>
  );
}
