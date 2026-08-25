import { useEffect, useState } from "react";
import { apiGet, apiDelete } from "../api/client";
import { FileIcon, TrashIcon } from "../components/Icons";

const TYPE_LABEL = { pdf: "PDF", image: "IMG", csv: "CSV", youtube: "YT", docx: "DOC" };

/**
 * View of the knowledge base: what's already been added, plus the
 * ability to open the original file or delete an entry entirely.
 * Upload controls still live on the Upload page -- this page answers
 * "what do I have", clicking a document answers "what is it", and now
 * also lets you remove it.
 *
 * "Open file" fetches a short-lived signed URL from the backend
 * (GET /documents/{id}/url) rather than storing/using any direct
 * storage URL client-side -- the bucket is private, so this is the
 * only way to actually view the original file.
 *
 * "Delete" calls DELETE /documents/{id}, which removes the DB row,
 * the vectors, the BM25 chunk mirror, AND the stored file in one go
 * (see backend/app/routers/documents.py) -- so there's nothing left
 * to clean up client-side beyond refreshing the list.
 */
export default function KnowledgeBase() {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState("");
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    const data = await apiGet("/documents");
    setDocs(data);
  }

  function openSelected() {
    setSelected(null);
  }

  async function handleOpenFile(doc) {
    setOpenError("");
    setOpening(true);
    try {
      const { url } = await apiGet(`/documents/${doc.id}/url`);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setOpenError("Couldn't open this file. It may not have a stored copy.");
    } finally {
      setOpening(false);
    }
  }

  async function handleDelete(doc, e) {
    e?.stopPropagation();
    if (!window.confirm(`Delete "${doc.source_name}"? This can't be undone.`)) return;
    setDeletingId(doc.id);
    try {
      await apiDelete(`/documents/${doc.id}`);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
      if (selected?.id === doc.id) setSelected(null);
    } catch (err) {
      setOpenError("Couldn't delete this document. Please try again.");
    } finally {
      setDeletingId(null);
    }
  }

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
            <button
              className="icon-btn"
              title="Delete document"
              disabled={deletingId === d.id}
              onClick={(e) => handleDelete(d, e)}
            >
              <TrashIcon width={15} height={15} />
            </button>
          </div>
        ))}
        {!docs.length && (
          <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: 20 }}>
            No documents yet — add some from the Upload page.
          </p>
        )}
      </div>

      {selected && (
        <div className="modal-backdrop" onClick={openSelected}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="doc-icon" style={{ width: 44, height: 44, marginBottom: 14 }}>
              <FileIcon width={20} height={20} />
            </div>
            <h2 style={{ margin: "0 0 4px", fontSize: 17 }}>{selected.source_name}</h2>
            <p className="doc-sub" style={{ marginBottom: 18 }}>
              {TYPE_LABEL[selected.source_type]} · Added {new Date(selected.uploaded_at).toLocaleString()}
            </p>
            {openError && (
              <p className="doc-sub" style={{ color: "var(--danger, #d33)", marginBottom: 10 }}>
                {openError}
              </p>
            )}
            <div style={{ display: "flex", gap: 10 }}>
              {selected.storage_path && (
                <button
                  className="btn-primary"
                  style={{ flex: 1 }}
                  disabled={opening}
                  onClick={() => handleOpenFile(selected)}
                >
                  {opening ? "Opening…" : "Open file"}
                </button>
              )}
              <button
                className="btn-secondary"
                style={{ flex: 1, color: "var(--danger, #d33)" }}
                disabled={deletingId === selected.id}
                onClick={(e) => handleDelete(selected, e)}
              >
                {deletingId === selected.id ? "Deleting…" : "Delete"}
              </button>
              <button className="btn-secondary" style={{ flex: 1 }} onClick={openSelected}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}