import { useRef } from "react";
import { AppShell } from "./components/layout/AppShell";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RunPage } from "./pages/RunPage";
import { UploadPage } from "./pages/UploadPage";
import { ViewerPage } from "./pages/ViewerPage";
import { Routes, useScrollAndFocusOnNavigate, type RouteDef } from "./router/router";

const routes: RouteDef[] = [
  { path: "/", element: <UploadPage /> },
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
