import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { FileIcon } from "../components/Icons";

const TYPE_LABEL = { pdf: "PDF", image: "IMG", csv: "CSV", youtube: "YT", docx: "DOC" };

/**
 * Read-only view of the knowledge base: what's already been added.
 * Deliberately has no upload controls and no chunk/status/delete
 * details -- that's all in the Upload page. This page answers "what do
 * I have", clicking a document answers "what is it", nothing more.
 */
export default function KnowledgeBase() {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    apiGet("/documents").then(setDocs);
  }, []);

  return (
    <div className="content">
      <div className="topbar" style={{ padding: 0, border: "none", marginBottom: 20 }}>
        <h1>Knowledge Base</h1>
      </div>

      <div className="doc-list">
        {docs.map((d) => (
          <div key={d.id} className="doc-row doc-row-clickable" onClick={() => setSelected(d)}>
            <div className="doc-row-left">
              <div className="doc-icon">{TYPE_LABEL[d.source_type]}</div>
              <div style={{ minWidth: 0 }}>
                <div className="doc-name">{d.source_name}</div>
                <div className="doc-sub">Added {new Date(d.uploaded_at).toLocaleDateString()}</div>
              </div>
            </div>
          </div>
        ))}
        {!docs.length && (
          <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: 20 }}>
            No documents yet — add some from the Upload page.
          </p>
        )}
      </div>

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="doc-icon" style={{ width: 44, height: 44, marginBottom: 14 }}>
              <FileIcon width={20} height={20} />
            </div>
            <h2 style={{ margin: "0 0 4px", fontSize: 17 }}>{selected.source_name}</h2>
            <p className="doc-sub" style={{ marginBottom: 18 }}>
              {TYPE_LABEL[selected.source_type]} · Added {new Date(selected.uploaded_at).toLocaleString()}
            </p>
            <button className="btn-secondary" onClick={() => setSelected(null)} style={{ width: "100%" }}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}