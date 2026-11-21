"use client";

import { useState } from "react";
import type { Message } from "@/lib/chat";
import { CopyIcon, LinkIcon, SpeakerIcon, ThumbDownIcon, ThumbUpIcon } from "./Icons";

type Props = {
  message: Message;
  onFeedback: (id: string, f: "up" | "down") => void;
};

export default function MessageView({ message, onFeedback }: Props) {
  const [copied, setCopied] = useState(false);
  const [openSource, setOpenSource] = useState<number | null>(null);

  if (message.role === "user") {
    return <div className="msg-user">{message.text}</div>;
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  };

  const speak = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(message.text));
  };

  const share = async () => {
    try {
      await navigator.clipboard.writeText(`${location.href}#${message.id}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  };

  const sources = message.sources ?? [];
  const warnings = message.warnings ?? [];
  const notes = message.notes ?? [];
  // Only answers that came from the backend carry these fields; the mock reply shows no badge.
  const fromBackend = message.verified !== undefined;

  return (
    <div className="msg-ai" id={message.id}>
      <div className="bubble">{message.text}</div>

      {fromBackend && (
        <div className="status-row">
          {message.insufficient ? (
            <span className="badge badge-neutral">Not covered by the indexed law</span>
          ) : message.verified ? (
            <span className="badge badge-ok">Citations checked against the retrieved sections</span>
          ) : (
            <span className="badge badge-warn">Some citations could not be verified</span>
          )}
        </div>
      )}

      {warnings.map((w) => (
        <p key={w} className="warn-text">{w}</p>
      ))}

      {sources.length > 0 && (
        <div className="sources">
          <div className="sources-label">Sources</div>
          <div className="chips">
            {sources.map((s, i) => (
              <button
                key={`${s.label ?? s.title}-${i}`}
                className={`chip${openSource === i ? " active" : ""}`}
                aria-expanded={openSource === i}
                onClick={() => setOpenSource(openSource === i ? null : i)}
              >
                {s.title}
              </button>
            ))}
          </div>
          {openSource !== null && sources[openSource]?.snippet && (
            <blockquote className="source-text">
              {sources[openSource].snippet}
              {sources[openSource].via ? (
                <span className="source-via"> (added as context, referred to by {sources[openSource].via})</span>
              ) : null}
            </blockquote>
          )}
        </div>
      )}

      {notes.map((n) => (
        <p key={n} className="small-note">{n}</p>
      ))}
      {message.disclaimer && <p className="small-note">{message.disclaimer}</p>}

      <div className="msg-actions">
        <button aria-label="Read aloud" onClick={speak}><SpeakerIcon /></button>
        <button aria-label="Copy" title={copied ? "Copied!" : "Copy"} onClick={copy}><CopyIcon /></button>
        <button
          aria-label="Good response"
          className={message.feedback === "up" ? "active" : ""}
          onClick={() => onFeedback(message.id, "up")}
        ><ThumbUpIcon /></button>
        <button
          aria-label="Bad response"
          className={message.feedback === "down" ? "active" : ""}
          onClick={() => onFeedback(message.id, "down")}
        ><ThumbDownIcon /></button>
        <button aria-label="Copy link" onClick={share}><LinkIcon /></button>
      </div>
    </div>
  );
}
