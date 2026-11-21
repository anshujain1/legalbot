// Unlike layout.tsx, a template re-mounts on every navigation, which lets each page fade in.
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="page-fade">{children}</div>;
}
