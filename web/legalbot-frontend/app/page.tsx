
import Link from "next/link";
import Header from "@/components/Header";

export default function Landing() {
  return (
    <div className="landing">
      <Header />

      <main className="landing-main">
        <div
          className="hero"
          role="img"
          aria-label="Legal AI assistant illustration"
        />

        <h1>Your Legal AI Assistant</h1>

        <p className="tagline">
          Let&apos;s make Legal AI simpler for all!
        </p>

        <div className="cta">
          <Link href="/chat" className="btn btn-primary">
            Start Talking!
          </Link>

          <Link href="/learn" className="btn btn-outline">
            Learn More
          </Link>
        </div>
      </main>
    </div>
  );
}
