"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FileStack } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { getSamples } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { titleCase } from "@/lib/format";

/**
 * The preloaded reference packages.
 *
 * These exist so the product is useful on the first click: a full run takes
 * five to seven minutes and a slice of a fifty-request daily quota, which is a
 * poor and rationed first impression. They are also the clearest demonstration
 * the system has — one quantitative, one narrative, same code path.
 */
export default function SamplesPage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["samples"],
    queryFn: getSamples,
  });

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Sample packages</h1>
        <p className="mt-2 max-w-2xl text-fg-muted">
          Finished packages you can read immediately — no upload, no waiting, no quota. One
          quantitative and one narrative, produced by the same pipeline.
        </p>
      </div>

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : isError ? (
        <ErrorState title={describeError(error).title}>{describeError(error).body}</ErrorState>
      ) : data.samples.length === 0 ? (
        <EmptyState icon={FileStack} title="No samples loaded">
          The server seeds these at startup from the repository. If none appear, the samples
          directory was not shipped with the deployment.
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {data.samples.map((sample) => (
            <Card key={sample.package_id} className="flex flex-col">
              <CardContent className="flex flex-1 flex-col pt-5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="accent">{titleCase(sample.pedagogy_profile)}</Badge>
                  <Badge>{sample.subject}</Badge>
                </div>
                <h2 className="mt-3 text-lg font-semibold">{sample.title}</h2>
                <p className="mt-1 text-sm text-fg-muted">
                  {sample.periods} periods · validation {titleCase(sample.validation_status)}
                </p>
                <div className="mt-4 flex-1" />
                <Button asChild variant="secondary" className="mt-4 w-full">
                  <Link href={`/packages?id=${sample.package_id}`}>
                    Open package <ArrowRight />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardContent className="pt-5">
          <h2 className="font-semibold">What to compare</h2>
          <p className="mt-2 text-sm leading-relaxed text-fg-muted">
            Open both and look at the assessment mix. The physics package carries numerical
            questions and a formula; the history package carries neither — not because anything
            failed, but because its content is classified <em>narrative</em>, and that profile
            weights numerical items at zero. The validator is profile-conditioned, so it scores
            that absence as correct rather than flagging a gap.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
