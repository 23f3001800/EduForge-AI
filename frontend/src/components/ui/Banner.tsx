import type { ReactNode } from "react";

export type BannerTone = "danger" | "warning" | "info" | "success";

export function Banner({
  tone,
  title,
  children,
  role,
}: {
  tone: BannerTone;
  title?: string;
  children?: ReactNode;
  role?: "alert" | "status";
}) {
  return (
    <div
      className={`ef-banner ef-banner--${tone}`}
      role={role ?? (tone === "danger" ? "alert" : "status")}
    >
      <div className="ef-banner__body">
        {title ? <div className="ef-banner__title">{title}</div> : null}
        {children}
      </div>
    </div>
  );
}
