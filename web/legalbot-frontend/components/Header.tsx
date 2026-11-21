import Link from "next/link";
import { ChatIcon, MenuIcon, ScaleIcon } from "./Icons";

type Props = {
  title?: string;
  onMenu?: () => void;
  onHistory?: () => void;
};

export default function Header({ title, onMenu, onHistory }: Props) {
  return (
    <header className="header">
      <div className="header-left">
        {onMenu && (
          <button className="icon-btn" aria-label="Menu" onClick={onMenu}>
            <MenuIcon />
          </button>
        )}
        <Link href="/" className="brand">
          <span className="brand-mark"><ScaleIcon width={18} height={18} /></span>
          JustAi
        </Link>
      </div>
      {title && <div className="header-title">{title}</div>}
      {onHistory ? (
        <button className="icon-btn" aria-label="Conversations" onClick={onHistory}>
          <ChatIcon />
        </button>
      ) : (
        <Link href="/chat" className="icon-btn" aria-label="Open chat">
          <ChatIcon />
        </Link>
      )}
    </header>
  );
}
