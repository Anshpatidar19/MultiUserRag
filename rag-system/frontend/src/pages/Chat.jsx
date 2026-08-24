import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiGet, streamChat } from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { useSessions } from "../context/SessionsContext";
import { useVoice } from "../hooks/useVoice";
import { exportConversationToPdf } from "../utils/exportPdf";
import { SendIcon, MicIcon, DownloadIcon, ChatIcon } from "../components/Icons";

// Simple auto-detect: Devanagari code points => Hindi, else English.
function detectLanguage(text) {
  return /[\u0900-\u097F]/.test(text) ? "hi" : "en";
}

export default function Chat() {
  const { sessions, activeId, setActiveId, createSession, autoNameFromMessage } = useSessions();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const bottomRef = useRef(null);
  const voice = useVoice({ language: "en-US" });

  useEffect(() => {
    if (activeId) loadMessages(activeId);
    else setMessages([]);
  }, [activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  async function loadMessages(sessionId) {
    const data = await apiGet(`/sessions/${sessionId}/messages`);
    setMessages(data);
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;

    let sessionId = activeId;
    let isFirstMessage = false;
    if (!sessionId) {
      const s = await createSession("New chat");
      sessionId = s.id;
      isFirstMessage = true;
    } else if (!messages.length) {
      // Session exists but has no messages yet (e.g. freshly created via
      // sidebar "+ New chat") -- this is still its first message.
      isFirstMessage = true;
    }

    const userMessage = { id: `local-${Date.now()}`, role: "user", content: input, citations: [] };
    setMessages((prev) => [...prev, userMessage]);
    const question = input;
    setInput("");
    setStreaming(true);
    setStreamingText("");

    // Give the chat a real name from its first message, ChatGPT-style,
    // instead of leaving it as "New chat" forever.
    if (isFirstMessage) {
      autoNameFromMessage(sessionId, question);
    }

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

  const currentTitle = sessions.find((s) => s.id === activeId)?.title || "New chat";

  return (
    <div className="chat-main">
      <div className="topbar">
        <h1>{currentTitle}</h1>
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
  );
}