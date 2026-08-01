import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
      <p className="font-mono text-sm text-fg-faint">404</p>
      <h1 className="text-2xl font-bold tracking-tight">Page not found</h1>
      <p className="text-fg-muted">
        That address does not match anything here. It may have been a link to a run or a package
        that no longer exists — the store is in memory today, so a restart clears both.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link href="/">Back to the homepage</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/upload">Start a new package</Link>
        </Button>
      </div>
    </div>
  );
}
