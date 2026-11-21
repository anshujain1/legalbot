export type Role = "user" | "ai";

/** A statute section the answer was grounded in (from the backend's `sources`). */
export type Source = {
  title: string; // "BNS §103: Punishment for murder"
  label?: string; // "BNS §103"
  snippet?: string;
  via?: string | null; // why an extra context section is here
};

export type Message = {
  id: string;
  role: Role;
  text: string;
  feedback?: "up" | "down";
  // Filled in for answers from the backend; absent for user messages and the mock reply.
  sources?: Source[];
  verified?: boolean; // false => at least one citation could not be checked
  insufficient?: boolean; // true => the indexed law doesn't cover the question
  warnings?: string[];
  notes?: string[];
  disclaimer?: string;
};

export type Conversation = {
  id: string;
  title: string;
  summary: string;
  messages: Message[];
  updatedAt: number;
};

const KEY = "justai.conversations.v1";

export const uid = () =>
  Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

export function newConversation(): Conversation {
  return {
    id: uid(),
    title: "Untitled Conversation",
    summary: "This conversation hasn't been summarized...",
    messages: [],
    updatedAt: Date.now(),
  };
}

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Conversation[]) : [];
  } catch {
    return [];
  }
}

export function saveConversations(list: Conversation[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage full or blocked — ignore */
  }
}

const API = process.env.NEXT_PUBLIC_API_URL;

/** The backend answered, but with an error; the message is safe to show to the user. */
export class BackendError extends Error {}

export type BotReply = Pick<
  Message,
  "text" | "sources" | "verified" | "insufficient" | "warnings" | "notes" | "disclaimer"
>;

/**
 * Sends a message to the LegalBot backend.
 * With NEXT_PUBLIC_API_URL unset it returns a mock reply, so the UI works standalone.
 * Backend contract: POST {API}/chat  body { message, history: [{role, text}] }
 *   -> { raw_answer, reply, sources[], verified, insufficient, warnings[], notes[], disclaimer }
 * (history is sent for forward compatibility; the backend currently answers each question on its own.)
 */
export async function askLegalBot(
  message: string,
  history: Message[]
): Promise<BotReply> {
  if (!API) {
    await new Promise((r) => setTimeout(r, 700));
    return { text: "This is a mock response from AI for your input." };
  }
  const res = await fetch(`${API.replace(/\/$/, "")}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history: history.map((m) => ({ role: m.role, text: m.text })),
    }),
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).detail ?? "";
    } catch {
      /* body wasn't JSON */
    }
    throw new BackendError(
      res.status === 503
        ? "the legal assistant isn't fully set up yet (the backend has no language model key)."
        : `the server returned ${res.status}${typeof detail === "string" && detail ? `: ${detail}` : ""}.`
    );
  }
  const data = await res.json();
  return {
    // Prefer the bare answer: warnings, notes and the disclaimer are shown separately below it.
    text: data.raw_answer ?? data.reply ?? data.response ?? data.answer ?? "",
    sources: Array.isArray(data.sources) ? data.sources : undefined,
    verified: typeof data.verified === "boolean" ? data.verified : undefined,
    insufficient: typeof data.insufficient === "boolean" ? data.insufficient : undefined,
    warnings: Array.isArray(data.warnings) ? data.warnings : undefined,
    notes: Array.isArray(data.notes) ? data.notes : undefined,
    disclaimer: typeof data.disclaimer === "string" ? data.disclaimer : undefined,
  };
}
