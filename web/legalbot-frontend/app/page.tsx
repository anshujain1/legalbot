import Link from "next/link";
import Header from "@/components/Header";

const CODE = `const verdict = await court.review(case);
if (verdict.valid) {
  this.dispatch({ type: "UPHOLD" });
} else {
  alert("Appeal filed");
}
export default function Justice() {
  return <Scales balanced />;
}`;

export default function Landing() {
  return (
    <div className="landing">
      <Header />
      <main className="landing-main">
        {/* Drop your own image at public/hero.jpg to replace this artwork */}
        <div className="hero" role="img" aria-label="Lady Justice beside lines of code">
          <div className="hero-code">{CODE}</div>
          <svg className="hero-scales" viewBox="0 0 200 300" fill="none" stroke="#c9d3e0" strokeWidth="3" strokeLinecap="round">
            <path d="M100 30v250M60 280h80M40 70h120" />
            <path d="M40 70 15 140a25 25 0 0 0 50 0zM160 70l-25 70a25 25 0 0 0 50 0z" />
            <circle cx="100" cy="22" r="8" />
          </svg>
        </div>
        <h1>Your Legal AI assistant</h1>
        <p className="tagline">Let&apos;s make Legal AI simpler for all!</p>
        <div className="cta">
          <Link href="/chat" className="btn btn-primary">Start Talking!</Link>
          <Link href="/learn" className="btn btn-outline">Learn More</Link>
        </div>
      </main>
    </div>
  );
}
