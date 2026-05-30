export default function CameraSetupPage() {
  return (
    <div className="page-stack">
      <section className="editor-layout">
        <div className="editor-main">
          <iframe
            src="http://127.0.0.1:5000?cameraSetup=1"
            style={{
              width: "100%",
              height: "78vh",
              minHeight: "760px",
              border: "none",
              borderRadius: "12px",
            }}
          />
        </div>
      </section>
    </div>
  );
}
