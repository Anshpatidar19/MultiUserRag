import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPost, apiUpload } from "../api/client";

/**
 * Shared documents state, mirroring SessionsContext.jsx: mounted once at
 * the ProtectedRoute layout level so Knowledge Base, Upload, and the
 * sidebar (visible from Chat too) all read/write the same list instead
 * of each page fetching its own copy on mount.
 *
 * The backend now returns from /documents/upload and /documents/youtube
 * the instant a "processing" row exists -- the actual chunk/embed work
 * runs afterwards as a background task (see routers/documents.py). That
 * means a single fetch-after-upload is no longer enough to reflect
 * reality: this context polls GET /documents on a short interval
 * *whenever at least one document is still "processing"*, and stops
 * polling the moment nothing is (so it isn't hammering the API all the
 * time, just during the window where something could change).
 */
const DocumentsContext = createContext(null);

const POLL_INTERVAL_MS = 2500;

export function DocumentsProvider({ children }) {
  const [documents, setDocuments] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const pollRef = useRef(null);

  const refresh = useCallback(async () => {
    const data = await apiGet("/documents");
    setDocuments(data);
    setLoaded(true);
    return data;
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll only while something is still processing; this is what makes a
  // document flip from "Processing…" to "N chunks" (or a failure) on its
  // own, on every page that reads this context, without a manual refresh.
  useEffect(() => {
    const anyProcessing = documents.some((d) => d.status === "processing");

    if (anyProcessing && !pollRef.current) {
      pollRef.current = setInterval(refresh, POLL_INTERVAL_MS);
    } else if (!anyProcessing && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [documents, refresh]);

  // Uploads a batch of files. Each one appears in `documents` (status
  // "processing") as soon as its own request returns, rather than
  // waiting for the whole batch -- so a slow file doesn't hold up the
  // UI update for a fast one alongside it.
  const uploadFiles = useCallback(
    async (files) => {
      const errors = [];
      for (const file of files) {
        try {
          const doc = await apiUpload("/documents/upload", file);
          setDocuments((prev) => [doc, ...prev]);
        } catch (err) {
          errors.push(`${file.name}: ${err.message}`);
        }
      }
      return errors;
    },
    []
  );

  const addYoutube = useCallback(async (url) => {
    const doc = await apiPost("/documents/youtube", { url });
    setDocuments((prev) => [doc, ...prev]);
    return doc;
  }, []);

  const deleteDocument = useCallback(async (id) => {
    await apiDelete(`/documents/${id}`);
    setDocuments((prev) => prev.filter((d) => d.id !== id));
  }, []);

  const processingCount = documents.filter((d) => d.status === "processing").length;

  return (
    <DocumentsContext.Provider
      value={{ documents, loaded, processingCount, refresh, uploadFiles, addYoutube, deleteDocument }}
    >
      {children}
    </DocumentsContext.Provider>
  );
}

export function useDocuments() {
  const ctx = useContext(DocumentsContext);
  if (!ctx) throw new Error("useDocuments must be used within DocumentsProvider");
  return ctx;
}