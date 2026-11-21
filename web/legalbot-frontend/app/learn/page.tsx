import Link from "next/link";
import Header from "@/components/Header";
import { AlertIcon, BoltIcon } from "@/components/Icons";

export default function Learn() {
  return (
    <div className="learn">
      <Header />
      <main className="learn-main">
        <div>
          <div className="cards">
            <section className="card">
              <h2><AlertIcon /> Capabilities</h2>
              <p>
                Answers come only from sections of Indian law that have been indexed, and every
                answer shows the sections it relied on. Citations are checked against those
                sections, and anything that can&apos;t be verified is flagged instead of hidden.
                Ask about an offence, a definition, or an old IPC section and see what it maps to
                in the BNS.
              </p>
            </section>
            <section className="card">
              <h2><BoltIcon /> Limitations</h2>
              <p>
                It only knows the Acts that have been indexed so far, and it doesn&apos;t cover
                case law yet. Each question is answered on its own, so it won&apos;t remember
                earlier messages. Some IPC to BNS mappings are still unverified. This is general
                legal information, not legal advice.
              </p>
            </section>
          </div>
          <div className="back-link">
            <Link href="/chat" className="btn btn-primary">Start Talking!</Link>
          </div>
        </div>
      </main>
    </div>
  );
}
