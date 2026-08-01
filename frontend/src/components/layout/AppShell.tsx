import { useSyncExternalStore, type ReactNode, type RefObject } from "react";
import { isMockMode, setMockMode, subscribeMockMode } from "../../api";
import { Link, usePathname } from "../../router/router";

function useMockMode(): boolean {
  return useSyncExternalStore(subscribeMockMode, isMockMode, isMockMode);
}

export function AppShell({ children, mainRef }: { children: ReactNode; mainRef: RefObject<HTMLElement> }) {
  const pathname = usePathname();
  const mockMode = useMockMode();
  const onUpload = pathname === "/";

  return (
    <div className="ef-shell">
      <a href="#ef-main-content" className="ef-skip-link">
        Skip to main content
      </a>
      <header className="ef-header">
        <div className="ef-header__inner">
          <Link to="/" className="ef-brand">
            EduForge <span className="ef-brand__mark">AI</span>
          </Link>
          <nav className="ef-nav" aria-label="Primary">
            <Link to="/" className="ef-nav__link" aria-current={onUpload ? "page" : undefined}>
              New package
            </Link>
          </nav>
          <label className="ef-demo-toggle">
            <input
              type="checkbox"
              checked={mockMode}
              onChange={(e) => setMockMode(e.target.checked)}
            />
            <span>Demo data (no backend)</span>
          </label>
        </div>
      </header>
      <main id="ef-main-content" className="ef-main" ref={mainRef} tabIndex={-1}>
        {children}
      </main>
      <footer className="ef-footer">
        EduForge AI — converts a document into a classroom-ready Teacher Knowledge Package.
      </footer>
    </div>
  );
}
