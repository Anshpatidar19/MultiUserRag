import { useEffect, useRef, useState } from "react";
import { apiGet, apiUpload, apiPost } from "../api/client";
import { UploadIcon } from "../components/Icons";

const TYPE_LABEL = { pdf: "PDF", image: "IMG", csv: "CSV", youtube: "YT", docx: "DOC" };

/**
 * Upload workflow lives here, separate from the read-only Knowledge
 * Base view. The doc list below the upload zone exists to confirm
 * ingestion worked -- it shows name + chunk count so the person can see
 * their document was actually indexed, without the status pill/delete
 * controls that belong to a management view rather than an upload flow.
 * A failed ingestion still surfaces its error inline (fail loudly, per
 * the ingestion pipeline's design) since silently hiding failures would
 * be worse than a slightly busier upload list.
 */
export default function Upload() {
  const [docs, setDocs] = useState([]);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    const data = await apiGet("/documents");
    setDocs(data);
  }

  async function handleFiles(files) {
    setError("");
    setBusy(true);
    for (const file of files) {
      try {
        await apiUpload("/documents/upload", file);
      } catch (err) {
        setError(`${file.name}: ${err.message}`);
      }
    }
    setBusy(false);
    refresh();
  }

  async function handleYoutube() {
    if (!youtubeUrl.trim()) return;
    setError("");
    setBusy(true);
    try {
      await apiPost("/documents/youtube", { url: youtubeUrl });
      setYoutubeUrl("");
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
    refresh();
  }

  return (
    <div className="content">
      <div className="topbar" style={{ padding: 0, border: "none", marginBottom: 20 }}>
        <h1>Upload</h1>
      </div>

      <div
        className="upload-zone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleFiles(Array.from(e.dataTransfer.files));
        }}
      >
        <UploadIcon width={28} height={28} style={{ marginBottom: 10, color: "var(--accent)" }} />
        <p style={{ margin: "0 0 12px" }}>Drag & drop PDF, DOCX, CSV, or image files, or</p>
        <button className="btn-secondary" onClick={() => fileInputRef.current?.click()}>
          Browse files
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.csv,.png,.jpg,.jpeg"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(Array.from(e.target.files))}
        />

        <div style={{ marginTop: 22, display: "flex", gap: 8, justifyContent: "center" }}>
          <input
            style={{ width: 320, padding: "10px 14px", border: "1px solid var(--border)", borderRadius: 8, fontSize: 13.5 }}
            placeholder="Paste a YouTube video URL"
            value={youtubeUrl}
            onChange={(e) => setYoutubeUrl(e.target.value)}
          />
          <button className="btn-secondary" onClick={handleYoutube}>
            Add video
          </button>
        </div>
      </div>

      {busy && <p style={{ color: "var(--text-secondary)", marginTop: 14 }}>Processing…</p>}
      {error && (
        <div style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginTop: 14 }}>
          {error}
        </div>
      )}

      <div className="doc-list">
        {docs.map((d) => (
          <div key={d.id} className="doc-row">
            <div className="doc-row-left">
              <div className="doc-icon">{TYPE_LABEL[d.source_type]}</div>
              <div style={{ minWidth: 0 }}>
                <div className="doc-name">{d.source_name}</div>
                <div className="doc-sub">
                  {d.status === "ready" && `${d.chunk_count} chunks`}
                  {d.status === "processing" && "Processing…"}
                  {d.status === "failed" && <span style={{ color: "var(--danger)" }}>{d.error_message || "Failed to process"}</span>}
                </div>
              </div>
            </div>
          </div>
        ))}
        {!docs.length && <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: 20 }}>No documents uploaded yet.</p>}
      </div>
    </div>
  );
}