import { useRef } from "react";
import { AppShell } from "./components/layout/AppShell";
import { LandingPage } from "./pages/LandingPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RunPage } from "./pages/RunPage";
import { UploadPage } from "./pages/UploadPage";
import { ViewerPage } from "./pages/ViewerPage";
import { Routes, useScrollAndFocusOnNavigate, type RouteDef } from "./router/router";

/**
 * `/` is the landing page; `/upload` is the app.
 *
 * It used to drop a first-time visitor straight into a file picker, which
 * assumes they already know what this produces and whether to trust it.
 */
const routes: RouteDef[] = [
  { path: "/", element: <LandingPage /> },
  { path: "/upload", element: <UploadPage /> },
  { path: "/run/:jobId", element: <RunPage /> },
  { path: "/packages/:packageId", element: <ViewerPage /> },
];

function App() {
  const mainRef = useRef<HTMLElement>(null);
  useScrollAndFocusOnNavigate(mainRef);

  return (
    <AppShell mainRef={mainRef}>
      <Routes routes={routes} notFound={<NotFoundPage />} />
    </AppShell>
  );
}

export default App;
