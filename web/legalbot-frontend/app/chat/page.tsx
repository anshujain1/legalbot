"use client";

import { useEffect, useRef, useState } from "react";
import Header from "@/components/Header";
import Sidebar from "@/components/Sidebar";
import Composer from "@/components/Composer";
import MessageView from "@/components/MessageView";
import {
  askLegalBot,
  BackendError,
  loadConversations,
  newConversation,
  saveConversations,
  uid,
  type BotReply,
  type Conversation,
  type Message,
} from "@/lib/chat";

const SUGGESTIONS = [
  "What is the punishment for cheating?",
  "What replaced IPC section 420 in the BNS?",
  "Explain section 103 of the BNS in simple terms",
];

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load saved conversations once on the client.
  useEffect(() => {
    const saved = loadConversations();
    if (saved.length) {
      setConversations(saved);
      setActiveId(saved[0].id);
    } else {
      const c = newConversation();
      setConversations([c]);
      setActiveId(c.id);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) saveConversations(conversations);
  }, [conversations, ready]);

  const active = conversations.find((c) => c.id === activeId);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages.length, loading]);

  const update = (id: string, fn: (c: Conversation) => Conversation) =>
    setConversations((list) => list.map((c) => (c.id === id ? fn(c) : c)));

  const startNew = () => {
    // Reuse an existing empty conversation instead of piling up blanks.
    const empty = conversations.find((c) => c.messages.length === 0);
    if (empty) {
      setActiveId(empty.id);
    } else {
      const c = newConversation();
      setConversations((l) => [c, ...l]);
      setActiveId(c.id);
    }
    setSidebarOpen(false);
  };

  const send = async (text: string) => {
    if (!active) return;
    const id = active.id;
    const history = active.messages;
    const userMsg: Message = { id: uid(), role: "user", text };

    update(id, (c) => ({
      ...c,
      title: c.messages.length === 0 ? text.slice(0, 40) : c.title,
      summary: c.messages.length === 0 ? text : c.summary,
      messages: [...c.messages, userMsg],
      updatedAt: Date.now(),
    }));

    setLoading(true);
    let reply: BotReply;
    try {
      reply = await askLegalBot(text, history);
    } catch (e) {
      reply = {
        text:
          e instanceof BackendError
            ? `Sorry, ${e.message}`
            : "Sorry, I couldn't reach the server. Please try again.",
      };
    }
    update(id, (c) => ({
      ...c,
      messages: [...c.messages, { id: uid(), role: "ai", ...reply }],
      updatedAt: Date.now(),
    }));
    setLoading(false);
  };

  const feedback = (msgId: string, f: "up" | "down") => {
    if (!active) return;
    update(active.id, (c) => ({
      ...c,
      messages: c.messages.map((m) =>
        m.id === msgId ? { ...m, feedback: m.feedback === f ? undefined : f } : m
      ),
    }));
  };

  return (
    <div className="chat">
      <Header
        title={active?.title ?? "Untitled Conversation"}
        onMenu={() => setSidebarOpen((o) => !o)}
        onHistory={() => setSidebarOpen((o) => !o)}
      />

      {sidebarOpen && (
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onNew={startNew}
          onSelect={(id) => {
            setActiveId(id);
            setSidebarOpen(false);
          }}
        />
      )}

      <div className="chat-body">
        <div className="chat-inner">
          {active && active.messages.length === 0 ? (
            <div className="empty">
              <h2>Greetings, let&apos;s get started</h2>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="suggestion" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {active?.messages.map((m) => (
                <MessageView key={m.id} message={m} onFeedback={feedback} />
              ))}
              {loading && (
                <div className="msg-ai">
                  <div className="typing"><span /><span /><span /></div>
                </div>
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <Composer onSend={send} disabled={loading} />
    </div>
  );
}
