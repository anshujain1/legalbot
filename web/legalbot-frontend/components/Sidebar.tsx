import type { Conversation } from "@/lib/chat";
import { PlusCircleIcon } from "./Icons";

type Props = {
  conversations: Conversation[];
  activeId: string;
  onNew: () => void;
  onSelect: (id: string) => void;
};

export default function Sidebar({ conversations, activeId, onNew, onSelect }: Props) {
  return (
    <aside className="sidebar" aria-label="Conversations">
      <button className="new-chat" onClick={onNew}>
        <PlusCircleIcon /> New Chat
      </button>
      {conversations.map((c) => (
        <button
          key={c.id}
          className={`conv${c.id === activeId ? " active" : ""}`}
          onClick={() => onSelect(c.id)}
        >
          <div className="conv-title">{c.title}</div>
          <div className="conv-sub">{c.summary}</div>
        </button>
      ))}
    </aside>
  );
}
