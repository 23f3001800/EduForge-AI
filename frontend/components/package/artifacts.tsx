"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FileJson, FileText, FileType } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { artifactUrl, getArtifacts } from "@/lib/api";
import { formatBytes } from "@/lib/format";

const META: Record<string, { title: string; hint: string; icon: typeof FileText }> = {
  lesson_plan_pdf: {
    title: "Lesson plan",
    hint: "Per-period plan with timings and sequencing.",
    icon: FileText,
  },
  teacher_guide_pdf: {
    title: "Teacher guide",
    hint: "Scripts, activities, misconceptions and remediation.",
    icon: FileText,
  },
  assessment_book_pdf: {
    title: "Assessment book",
    hint: "Questions first, answer key behind a page break.",
    icon: FileText,
  },
  markdown_bundle: { title: "Markdown bundle", hint: "The same content as text.", icon: FileType },
  tkp_json: { title: "Package JSON", hint: "The complete structured package.", icon: FileJson },
};

/**
 * The rendered files.
 *
 * These were generated, stored and served by the backend but rendered nowhere,
 * so the thing a teacher actually prints was unreachable from the UI.
 *
 * A row whose artifact came back `failed` is disabled with the reason rather
 * than linked: offering a download that 404s is worse than saying it is absent.
 */
export function ArtifactsPanel({ packageId }: { packageId: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["artifacts", packageId],
    queryFn: () => getArtifacts(packageId),
  });

  if (isError) return null; // the package itself still reads fine without downloads

  return (
    <Card>
      <CardHeader>
        <CardTitle>Downloads</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 sm:grid-cols-2">
        {isPending
          ? Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full" />
            ))
          : data.artifacts.map((artifact) => {
              const meta = META[artifact.kind] ?? {
                title: artifact.kind,
                hint: "",
                icon: FileText,
              };
              const Icon = meta.icon;
              const ready = artifact.status === "ready" && artifact.bytes > 0;
              return (
                <div
                  key={artifact.kind}
                  className="flex items-center gap-3 rounded-md border border-border p-3"
                >
                  <Icon className="size-5 shrink-0 text-fg-faint" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{meta.title}</p>
                    <p className="truncate text-xs text-fg-faint">
                      {ready ? formatBytes(artifact.bytes) : "Not produced for this run"}
                    </p>
                  </div>
                  {ready ? (
                    <Button asChild variant="secondary" size="sm">
                      <a href={artifactUrl(packageId, artifact.kind)} download>
                        <Download /> Get
                      </a>
                    </Button>
                  ) : null}
                </div>
              );
            })}
      </CardContent>
    </Card>
  );
}
