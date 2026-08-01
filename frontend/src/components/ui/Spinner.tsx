export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="ef-row" role="status" aria-live="polite">
      <span className="ef-spinner" aria-hidden="true" />
      <span className="ef-visually-hidden">{label}</span>
    </div>
  );
}
