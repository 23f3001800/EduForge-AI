import { Link } from "../router/router";

export function NotFoundPage() {
  return (
    <div className="ef-state">
      <p style={{ fontWeight: 700 }}>Page not found</p>
      <p className="ef-muted">
        <Link to="/">Back to the upload screen</Link>
      </p>
    </div>
  );
}
