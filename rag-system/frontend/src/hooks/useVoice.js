import { useCallback, useRef, useState } from "react";

/**
 * Thin wrapper around the browser's Web Speech API
 * (SpeechRecognition + SpeechSynthesis).
 */
export function useVoice({ language = "en-US" } = {}) {
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);

  const recognitionRef = useRef(null);

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

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

      recognition.onend = () => {
        setIsRecording(false);
      };

      recognition.onerror = () => {
        setIsRecording(false);
      };

      recognitionRef.current = recognition;

      recognition.start();
      setIsRecording(true);
    },
    [isSupported, language]
  );

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setIsRecording(false);
  }, []);

  const speak = useCallback(
    (text, lang = language) => {
      if (!window.speechSynthesis) return;

      // Stop anything currently playing first.
      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);

      utterance.lang = lang;
      utterance.rate = 1;
      utterance.pitch = 1;
      utterance.volume = 1;

      utterance.onstart = () => {
        setIsSpeaking(true);
      };

      utterance.onend = () => {
        setIsSpeaking(false);
      };

      utterance.onerror = () => {
        setIsSpeaking(false);
      };

      window.speechSynthesis.speak(utterance);
    },
    [language]
  );

  const stopSpeaking = useCallback(() => {
    if (!window.speechSynthesis) return;

    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  const toggleSpeaking = useCallback(
    (text, lang = language) => {
      if (!window.speechSynthesis) return;

      if (window.speechSynthesis.speaking) {
        stopSpeaking();
        return;
      }

      speak(text, lang);
    },
    [language, speak, stopSpeaking]
  );

  return {
    isSupported,
    isRecording,
    startListening,
    stopListening,

    // TTS
    isSpeaking,
    speak,
    stopSpeaking,
    toggleSpeaking,
  };
}