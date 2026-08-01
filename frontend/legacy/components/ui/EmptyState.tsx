import type { ReactNode } from "react";

export function EmptyState({
  title,
  children,
  tone = "default",
}: {
  title: string;
  children?: ReactNode;
  tone?: "default" | "error";
}) {
  return (
    <div className={`ef-state${tone === "error" ? " ef-state--error" : ""}`} role={tone === "error" ? "alert" : undefined}>
      <p style={{ fontWeight: 700, color: "inherit" }}>{title}</p>
      {children ? <p className={tone === "default" ? "ef-muted" : undefined}>{children}</p> : null}
    </div>
  );
}
