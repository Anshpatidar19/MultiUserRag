import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiGet, apiPost, apiPatch, apiDelete, streamChat } from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { useVoice } from "../hooks/useVoice";
import { exportConversationToPdf } from "../utils/exportPdf";
import { PlusIcon, TrashIcon, SendIcon, MicIcon, DownloadIcon, ChatIcon } from "../components/Icons";

// Simple auto-detect: Devanagari code points => Hindi, else English.
// Backend also auto-detects from the raw message; this hint just makes
// voice-output language selection snappier without waiting on a round trip.
function detectLanguage(text) {
  return /[\u0900-\u097F]/.test(text) ? "hi" : "en";
}

export default function Chat() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const bottomRef = useRef(null);
  const voice = useVoice({ language: "en-US" });

  useEffect(() => {
    loadSessions();
  }, []);

  useEffect(() => {
    if (activeId) loadMessages(activeId);
  }, [activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  async function loadSessions() {
    const data = await apiGet("/sessions");
    setSessions(data);
    if (data.length && !activeId) setActiveId(data[0].id);
  }

  async function loadMessages(sessionId) {
    const data = await apiGet(`/sessions/${sessionId}/messages`);
    setMessages(data);
  }

  async function newSession() {
    const s = await apiPost("/sessions", { title: "New chat" });
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
    setMessages([]);
  }

  async function renameSession(id, title) {
    await apiPatch(`/sessions/${id}`, { title });
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
  }

  async function deleteSession(id) {
    await apiDelete(`/sessions/${id}`);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeId === id) {
      const remaining = sessions.filter((s) => s.id !== id);
      setActiveId(remaining[0]?.id ?? null);
      setMessages([]);
    }
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;
    let sessionId = activeId;
    if (!sessionId) {
      const s = await apiPost("/sessions", { title: input.slice(0, 40) });
      setSessions((prev) => [s, ...prev]);
      sessionId = s.id;
      setActiveId(s.id);
    }

    const userMessage = { id: `local-${Date.now()}`, role: "user", content: input, citations: [] };
    setMessages((prev) => [...prev, userMessage]);
    const question = input;
    setInput("");
    setStreaming(true);
    setStreamingText("");

    let finalText = "";
    await streamChat(
      { sessionId, message: question, language: detectLanguage(question) },
      {
        onToken: (delta) => {
          finalText += delta;
          setStreamingText((prev) => prev + delta);
        },
        onDone: (payload) => {
          setMessages((prev) => [
            ...prev,
            {
              id: `assistant-${Date.now()}`,
              role: "assistant",
              content: finalText,
              citations: payload.citations,
              confidence_score: payload.confidence_score,
              confidence_label: payload.confidence_label,
              grounded: payload.grounded,
            },
          ]);
          setStreaming(false);
          setStreamingText("");
        },
        onError: () => setStreaming(false),
      }
    );
  }

  function handleMic() {
    if (voice.isRecording) {
      voice.stopListening();
      return;
    }
    voice.startListening((transcript) => setInput((prev) => (prev ? `${prev} ${transcript}` : transcript)));
  }

  function handleExportPdf() {
    const session = sessions.find((s) => s.id === activeId);
    exportConversationToPdf(session?.title, messages);
  }

  return (
    <div className="chat-layout">
      <div className="session-rail">
        <button className="btn-primary" style={{ width: "100%", marginBottom: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }} onClick={newSession}>
          <PlusIcon width={16} height={16} /> New chat
        </button>
        <div style={{ overflowY: "auto", flex: 1 }}>
          {sessions.map((s) => (
            <div key={s.id} className={`session-item${s.id === activeId ? " active" : ""}`} onClick={() => setActiveId(s.id)}>
              <span
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  const title = prompt("Rename chat", s.title);
                  if (title) renameSession(s.id, title);
                }}
              >
                {s.title}
              </span>
              <button
                className="icon-mini"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm("Delete this chat?")) deleteSession(s.id);
                }}
              >
                <TrashIcon width={14} height={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="chat-main">
        <div className="topbar">
          <h1>{sessions.find((s) => s.id === activeId)?.title || "New chat"}</h1>
          <button className="btn-secondary" onClick={handleExportPdf} disabled={!messages.length} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <DownloadIcon width={15} height={15} /> Export PDF
          </button>
        </div>

        <div className="messages">
          {!messages.length && !streaming && (
            <div className="empty-state">
              <ChatIcon width={34} height={34} />
              <p>Ask a question about your uploaded documents, images, spreadsheets, or videos.</p>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={`msg-row ${m.role}`}>
              <div style={{ maxWidth: "68%" }}>
                <div className={`msg-bubble ${m.role}`}>
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                </div>
                {m.role === "assistant" && (
                  <div className="msg-meta">
                    <ConfidenceBadge score={m.confidence_score} label={m.confidence_label} />
                    {m.grounded === false && <span className="badge badge-low">Not based on your documents</span>}
                    {m.citations?.map((c, i) => (
                      <span key={i} className="citation-chip" title={c.preview}>
                        {c.source_name} · {Math.round(c.relevance_score * 1000) / 1000}
                      </span>
                    ))}
                    <button className="icon-btn" style={{ width: 26, height: 26 }} onClick={() => voice.speak(m.content, detectLanguage(m.content) === "hi" ? "hi-IN" : "en-US")}>
                      🔊
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {streaming && (
            <div className="msg-row assistant">
              <div className="msg-bubble assistant">
                <ReactMarkdown>{streamingText || "…"}</ReactMarkdown>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="composer">
          <div className="composer-inner">
            <button className={`round-btn mic${voice.isRecording ? " recording" : ""}`} onClick={handleMic} disabled={!voice.isSupported} title={voice.isSupported ? "Voice input" : "Voice input not supported in this browser"}>
              <MicIcon width={17} height={17} />
            </button>
            <textarea
              rows={1}
              placeholder="Ask about your documents… (English or Hindi)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <button className="round-btn send" onClick={handleSend} disabled={streaming || !input.trim()}>
              <SendIcon width={16} height={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
