import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiGet, streamChat } from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { useSessions } from "../context/SessionsContext";
import { useVoice } from "../hooks/useVoice";
import { exportConversationToPdf } from "../utils/exportPdf";
import {
  SendIcon,
  MicIcon,
  DownloadIcon,
  ChatIcon,
} from "../components/Icons";

// Simple auto-detect: Devanagari code points => Hindi, else English.
function detectLanguage(text) {
  return /[\u0900-\u097F]/.test(text) ? "hi" : "en";
}

export default function Chat() {
  const {
    sessions,
    activeId,
    createSession,
    autoNameFromMessage,
  } = useSessions();

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");

  const messagesRef = useRef(null);
  const bottomRef = useRef(null);
  const shouldAutoScrollRef = useRef(true);

  const [showScrollButton, setShowScrollButton] = useState(false);

  // Track which assistant message is currently being spoken.
  const [speakingMessageId, setSpeakingMessageId] = useState(null);

  const voice = useVoice({ language: "en-US" });

  useEffect(() => {
    if (activeId) {
      loadMessages(activeId);
    } else {
      setMessages([]);
    }

    // Stop TTS when changing chats.
    voice.stopSpeaking();
    setSpeakingMessageId(null);
  }, [activeId]);

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return;

    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "end",
      });
    });
  }, [messages, streamingText]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;

    const handleScroll = () => {
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;

      const atBottom = distanceFromBottom < 80;

      setShowScrollButton(!atBottom);
      shouldAutoScrollRef.current = atBottom;
    };

    handleScroll();

    el.addEventListener("scroll", handleScroll, { passive: true });

    return () => {
      el.removeEventListener("scroll", handleScroll);
    };
  }, []);

  // Keep UI state synchronized if TTS ends naturally.
  useEffect(() => {
    if (!voice.isSpeaking) {
      setSpeakingMessageId(null);
    }
  }, [voice.isSpeaking]);

  function scrollToLatest() {
    shouldAutoScrollRef.current = true;

    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }

  async function loadMessages(sessionId) {
    const data = await apiGet(`/sessions/${sessionId}/messages`);
    setMessages(data);

    requestAnimationFrame(() => {
      shouldAutoScrollRef.current = true;

      bottomRef.current?.scrollIntoView({
        behavior: "auto",
        block: "end",
      });
    });
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

    const userMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: input,
      citations: [],
    };

    setMessages((prev) => [...prev, userMessage]);

    const question = input;

    setInput("");
    setStreaming(true);
    setStreamingText("");

    shouldAutoScrollRef.current = true;

    if (isFirstMessage) {
      autoNameFromMessage(sessionId, question);
    }

    let finalText = "";

    await streamChat(
      {
        sessionId,
        message: question,
        language: detectLanguage(question),
      },
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

    voice.startListening((transcript) => {
      setInput((prev) =>
        prev ? `${prev} ${transcript}` : transcript
      );
    });
  }

  function handleSpeech(message) {
    const language =
      detectLanguage(message.content) === "hi"
        ? "hi-IN"
        : "en-US";

    // If this message is currently speaking, stop it.
    if (
      speakingMessageId === message.id &&
      voice.isSpeaking
    ) {
      voice.stopSpeaking();
      setSpeakingMessageId(null);
      return;
    }

    // Starting another message automatically stops the previous one.
    voice.stopSpeaking();

    setSpeakingMessageId(message.id);

    voice.speak(message.content, language);
  }

  function handleExportPdf() {
    const session = sessions.find((s) => s.id === activeId);
    exportConversationToPdf(session?.title, messages);
  }

  const currentTitle =
    sessions.find((s) => s.id === activeId)?.title || "New chat";

  return (
    <div className="chat-main">
      <div className="topbar">
        <h1>{currentTitle}</h1>

        <button
          className="btn-secondary"
          onClick={handleExportPdf}
          disabled={!messages.length}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <DownloadIcon width={15} height={15} />
          Export PDF
        </button>
      </div>

      <div className="messages" ref={messagesRef}>
        {!messages.length && !streaming && (
          <div className="empty-state">
            <ChatIcon width={34} height={34} />

            <p>
              Ask a question about your uploaded documents,
              images, spreadsheets, or videos.
            </p>
          </div>
        )}

        {messages.map((m) => (
          <div
            key={m.id}
            className={`msg-row ${m.role}`}
          >
            <div className="msg-content">
              <div className={`msg-bubble ${m.role}`}>
                <ReactMarkdown>
                  {m.content}
                </ReactMarkdown>
              </div>

              {m.role === "assistant" && (
                <div className="msg-meta">
                  <ConfidenceBadge
                    score={m.confidence_score}
                    label={m.confidence_label}
                  />

                  {m.grounded === false && (
                    <span className="badge badge-low">
                      Not based on your documents
                    </span>
                  )}

                  {m.citations?.map((c, i) => (
                    <span
                      key={i}
                      className="citation-chip"
                      title={c.preview}
                    >
                      {c.source_name} ·{" "}
                      {Math.round(
                        c.relevance_score * 1000
                      ) / 1000}
                    </span>
                  ))}

                  <button
                    className={`icon-btn speech-btn${
                      speakingMessageId === m.id &&
                      voice.isSpeaking
                        ? " speaking"
                        : ""
                    }`}
                    style={{
                      width: 30,
                      height: 30,
                    }}
                    onClick={() => handleSpeech(m)}
                    title={
                      speakingMessageId === m.id &&
                      voice.isSpeaking
                        ? "Stop speaking"
                        : "Read answer aloud"
                    }
                    type="button"
                    aria-label={
                      speakingMessageId === m.id &&
                      voice.isSpeaking
                        ? "Stop speaking"
                        : "Read answer aloud"
                    }
                  >
                    {speakingMessageId === m.id &&
                    voice.isSpeaking
                      ? "⏹"
                      : "🔊"}
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}

        {streaming && (
          <div className="msg-row assistant">
            <div className="msg-content">
              <div className="msg-bubble assistant">
                <ReactMarkdown>
                  {streamingText || "…"}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}

        <div
          ref={bottomRef}
          className="messages-bottom"
          aria-hidden="true"
        />

        {showScrollButton && (
          <button
            className="scroll-latest-btn"
            onClick={scrollToLatest}
            type="button"
            title="Scroll to latest message"
            aria-label="Scroll to latest message"
          >
            ↓
          </button>
        )}
      </div>

      <div className="composer">
        <div className="composer-inner">
          <button
            className={`round-btn mic${
              voice.isRecording ? " recording" : ""
            }`}
            onClick={handleMic}
            disabled={!voice.isSupported}
            title={
              voice.isSupported
                ? "Voice input"
                : "Voice input not supported in this browser"
            }
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
              if (
                e.key === "Enter" &&
                !e.shiftKey
              ) {
                e.preventDefault();
                handleSend();
              }
            }}
          />

          <button
            className="round-btn send"
            onClick={handleSend}
            disabled={
              streaming || !input.trim()
            }
            type="button"
          >
            <SendIcon width={16} height={16} />
          </button>
        </div>
      </div>
    </div>
  );
}