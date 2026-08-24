import { useCallback, useRef, useState } from "react";

/**
 * Thin wrapper around the browser's Web Speech API (SpeechRecognition +
 * SpeechSynthesis). Kept as a hook rather than a component so both the
 * mic button and the "read answer aloud" action can share one instance
 * without prop drilling. Falls back gracefully (isSupported=false) in
 * browsers without SpeechRecognition (e.g. Firefox) so voice mode is
 * additive, not a hard requirement to use the app.
 */
export function useVoice({ language = "en-US" } = {}) {
  const [isRecording, setIsRecording] = useState(false);
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

  const speak = useCallback((text, lang = language) => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    window.speechSynthesis.speak(utterance);
  }, [language]);

  return { isSupported, isRecording, startListening, stopListening, speak };
}
