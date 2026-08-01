/**
 * Next.js, exported as static files.
 *
 * `output: "export"` is load-bearing, not a preference. The app deploys as ONE
 * FastAPI process on Azure App Service that serves the built frontend from the
 * same origin — no CORS, no second service, no environment variable pointing
 * one at the other. Next's SSR runtime would need its own Node process and a
 * second deployment, which would undo that.
 *
 * `distDir: "dist"` so the export lands where the backend already looks
 * (`api/main.py::FRONTEND_DIST`) and the Dockerfile already copies from.
 *
 * Everything this UI does is client-side anyway: it talks to a JSON API and an
 * SSE stream, and every route except the landing page is per-job or per-package
 * data that could not be pre-rendered at build time regardless.
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  distDir: "dist",

  // A static host cannot rewrite /run/abc-123 to a parameterised route, so each
  // dynamic route is emitted as its own directory with an index.html. The
  // backend's SPA fallback serves index.html for unmatched paths, which is what
  // makes a hard refresh mid-run resume rather than 404.
  trailingSlash: true,

  images: {
    // No image optimisation server exists in an export.
    unoptimized: true,
  },

  eslint: {
    // Lint is a separate command; a lint warning must not fail a deploy build.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
