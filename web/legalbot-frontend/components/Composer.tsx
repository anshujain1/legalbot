"use client";

import { useRef, useState } from "react";
import { MicIcon, PlusIcon, SendIcon } from "./Icons";

type Props = {
  disabled?: boolean;
  onSend: (text: string) => void;
};

// Minimal typing for the browser speech API (not in lib.dom for all targets)
type SpeechRec = {
  lang: string;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

export default function Composer({ disabled, onSend }: Props) {
  const [value, setValue] = useState("");
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRec | null>(null);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
  };

  const toggleMic = () => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const w = window as unknown as {
      SpeechRecognition?: new () => SpeechRec;
      webkitSpeechRecognition?: new () => SpeechRec;
    };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "en-IN";
    rec.interimResults = false;
    rec.onresult = (e) => {
      const t = Array.from(e.results).map((r) => r[0].transcript).join(" ");
      setValue((v) => (v ? v + " " : "") + t);
    };
    rec.onend = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  return (
    <div className="composer-wrap">
      <div className="composer">
        <button className="icon-btn" aria-label="Attach file" title="Attach (coming soon)">
          <PlusIcon />
        </button>
        <textarea
          placeholder="Type your message..."
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          className="icon-btn"
          aria-label="Voice input"
          onClick={toggleMic}
          style={listening ? { color: "#14b8a6" } : undefined}
        >
          <MicIcon />
        </button>
        <button className="icon-btn" aria-label="Send" onClick={submit} disabled={disabled}>
          <SendIcon />
        </button>
      </div>
      <p className="disclaimer">
        AI may make mistakes. For professional legal advice, consult a qualified legal expert.
      </p>
    </div>
  );
}
