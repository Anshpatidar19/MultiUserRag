import { useCallback, useRef, useState } from "react";

/**
 * Thin wrapper around the browser's Web Speech API (SpeechRecognition +
 * SpeechSynthesis). Kept as a hook rather than a component so both the
 * mic button and the "read answer aloud" action can share one instance
 * without prop drilling. Falls back gracefully (isSupported=false) in
 * browsers without SpeechRecognition (e.g. Firefox) so voice mode is
 * additive, not a hard requirement to use the app.
 *
 * isSpeaking / stopSpeaking exist so a caller (e.g. Chat.jsx) can show
 * which message is currently being read aloud and let the user stop it
 * mid-sentence, or automatically stop playback when switching chats.
 */
export function useVoice({ language = "en-US" } = {}) {
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const recognitionRef = useRef(null);

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const isSupported = !!SpeechRecognition;

  const startListening = useCallback(
    (onResult) => {
      if (!isSupported) return;
      const recognition = new SpeechRecognition();
      recognition.lang = language;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        onResult(transcript);
      };
      recognition.onend = () => setIsRecording(false);
      recognition.onerror = () => setIsRecording(false);
      recognitionRef.current = recognition;
      recognition.start();
      setIsRecording(true);
    },
    [isSupported, language]
  );

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setIsRecording(false);
  }, []);

  const speak = useCallback(
    (text, lang = language) => {
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.onstart = () => setIsSpeaking(true);
      utterance.onend = () => setIsSpeaking(false);
      utterance.onerror = () => setIsSpeaking(false);
      window.speechSynthesis.speak(utterance);
    },
    [language]
  );

  const stopSpeaking = useCallback(() => {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  return { isSupported, isRecording, startListening, stopListening, speak, isSpeaking, stopSpeaking };
}