import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiGet, streamChat } from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { useSessions } from "../context/SessionsContext";
import { useVoice } from "../hooks/useVoice";
import { exportConversationToPdf } from "../utils/exportPdf";
import { SendIcon, MicIcon, DownloadIcon, ChatIcon, ChevronDownIcon } from "../components/Icons";

// Simple auto-detect: Devanagari code points => Hindi, else English.
function detectLanguage(text) {
  return /[\u0900-\u097F]/.test(text) ? "hi" : "en";
}

export default function Chat() {
  const { sessions, activeId, createSession, autoNameFromMessage } = useSessions();

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  // Citations are hidden by default and only shown per-message on click.
  const [expandedSources, setExpandedSources] = useState({});
  // Tracks which message's answer is currently being read aloud, so the
  // speaker icon can flip to a "stop" state for that message only.
  const [speakingMessageId, setSpeakingMessageId] = useState(null);
  // Shows a "jump to latest" button once the user has scrolled up away
  // from the bottom of the conversation.
  const [showScrollButton, setShowScrollButton] = useState(false);

  const bottomRef = useRef(null);
  const citationRefs = useRef({});
  const messagesRef = useRef(null);
  // Whether new content should auto-scroll the view -- true while the
  // user is at (or near) the bottom, false once they've scrolled up to
  // read earlier messages, so streaming tokens don't yank them back down.
  const shouldAutoScrollRef = useRef(true);

  const voice = useVoice({ language: "en-US" });

  useEffect(() => {
    if (activeId) {
      loadMessages(activeId);
    } else {
      setMessages([]);
    }
    // Stop any in-progress TTS when switching chats.
    voice.stopSpeaking();
    setSpeakingMessageId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return;
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }, [messages, streamingText]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;

    const handleScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      const atBottom = distanceFromBottom < 80;
      setShowScrollButton(!atBottom);
      shouldAutoScrollRef.current = atBottom;
    };

    handleScroll();
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  // Keep UI state synced if TTS finishes on its own (not via the stop button).
  useEffect(() => {
    if (!voice.isSpeaking) setSpeakingMessageId(null);
  }, [voice.isSpeaking]);

  function scrollToLatest() {
    shouldAutoScrollRef.current = true;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  async function loadMessages(sessionId) {
    const data = await apiGet(`/sessions/${sessionId}/messages`);
    setMessages(data);
    requestAnimationFrame(() => {
      shouldAutoScrollRef.current = true;
      bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    });
  }

  function toggleSources(messageId) {
    setExpandedSources((prev) => ({ ...prev, [messageId]: !prev[messageId] }));
    setTimeout(() => {
      citationRefs.current[messageId]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, 60);
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
      isFirstMessage = true;
    }

    const userMessage = { id: `local-${Date.now()}`, role: "user", content: input, citations: [] };
    setMessages((prev) => [...prev, userMessage]);
    const question = input;
    setInput("");
    setStreaming(true);
    setStreamingText("");

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
          shouldAutoScrollRef.current = true;
        },
        onError: () => {
          setStreaming(false);
          setStreamingText("");
        },
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

  function handleSpeech(message) {
    const language = detectLanguage(message.content) === "hi" ? "hi-IN" : "en-US";

    // Clicking the speaker icon on the message currently playing stops it.
    if (speakingMessageId === message.id && voice.isSpeaking) {
      voice.stopSpeaking();
      setSpeakingMessageId(null);
      return;
    }

    // Starting a new message's speech automatically stops the previous one.
    voice.stopSpeaking();
    setSpeakingMessageId(message.id);
    voice.speak(message.content, language);
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

      <div className="messages" ref={messagesRef}>
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
                <>
                  <div className="msg-meta">
                    <ConfidenceBadge score={m.confidence_score} label={m.confidence_label} />
                    {m.grounded === false && <span className="badge badge-low">Not based on your documents</span>}
                    {!!m.citations?.length && (
                      <button className="sources-toggle" onClick={() => toggleSources(m.id)}>
                        Sources ({m.citations.length})
                        <ChevronDownIcon width={13} height={13} style={{ transform: expandedSources[m.id] ? "rotate(180deg)" : "none", transition: "transform 0.15s ease" }} />
                      </button>
                    )}
                    <button
                      className="icon-btn"
                      style={{ width: 26, height: 26 }}
                      onClick={() => handleSpeech(m)}
                      title={speakingMessageId === m.id && voice.isSpeaking ? "Stop speaking" : "Read aloud"}
                    >
                      {speakingMessageId === m.id && voice.isSpeaking ? "⏹" : "🔊"}
                    </button>
                  </div>

                  {expandedSources[m.id] && !!m.citations?.length && (
                    <div className="citations-panel" ref={(el) => (citationRefs.current[m.id] = el)}>
                      {m.citations.map((c, i) => (
                        <div key={i} className="citation-row">
                          <div>
                            <span className="citation-name">{c.source_name}</span>
                            <span className="citation-score">relevance {c.relevance_score}</span>
                          </div>
                          {c.preview && <p className="citation-preview">{c.preview}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                </>
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

        <div ref={bottomRef} className="messages-bottom" aria-hidden="true" />

        {showScrollButton && (
          <button className="scroll-latest-btn" onClick={scrollToLatest} type="button" title="Scroll to latest message" aria-label="Scroll to latest message">
            ↓
          </button>
        )}
      </div>

      <div className="composer">
        <div className="composer-inner">
          <button
            className={`round-btn mic${voice.isRecording ? " recording" : ""}`}
            onClick={handleMic}
            disabled={!voice.isSupported}
            title={voice.isSupported ? "Voice input" : "Voice input not supported in this browser"}
            type="button"
          >
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
          <button className="round-btn send" onClick={handleSend} disabled={streaming || !input.trim()} type="button">
            <SendIcon width={16} height={16} />
          </button>
        </div>
      </div>
    </div>
  );
}