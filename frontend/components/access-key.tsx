"use client";

/**
 * Where a visitor supplies the access key, when the instance asks for one.
 *
 * Shown in response to a 401 rather than sitting on the form permanently. Most
 * deployments set no key at all — a local run against your own provider key
 * needs none — so a key field on every upload page would ask nearly everyone to
 * think about something that does not apply to them.
 *
 * The trade is that a visitor meets the requirement only after being refused
 * once. That is the right way round: the refusal is what explains why the field
 * exists, and it arrives with the reason attached.
 */

import { useState } from "react";
import { KeyRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getAccessKey, setAccessKey } from "@/lib/api";
import { ApiError } from "@/lib/api";

/** Whether this failure is the server asking for a key. */
export function isAccessKeyError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "access_key_required";
}

export function AccessKeyPrompt({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState(getAccessKey);
  const [saved, setSaved] = useState(false);

  function save() {
    setAccessKey(value);
    setSaved(true);
    onSaved();
  }

  return (
    <section
      aria-labelledby="access-key"
      className="rounded-lg border border-warning/30 bg-warning-subtle p-5"
    >
      <div className="flex items-start gap-3">
        <KeyRound className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 id="access-key" className="font-medium">
            This instance needs an access key
          </h2>
          <p className="mt-1 text-sm text-fg-muted">
            Generating a package costs the person hosting this instance real money, so
            starting a run is gated. Browsing the samples and their evaluations is not —
            those are free to serve and open to everyone.
          </p>
          <p className="mt-2 text-sm text-fg-muted">
            Ask whoever shared this link for the key, or run your own instance with your
            own provider key, where no key is needed. The key is kept in this browser only.
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="access-key-input">
              Access key
            </label>
            <input
              id="access-key-input"
              type="password"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setSaved(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && value.trim()) save();
              }}
              placeholder="Paste the access key"
              className="min-h-11 min-w-0 flex-1 rounded-md border border-input bg-raised px-3"
            />
            <Button size="sm" disabled={!value.trim()} onClick={save}>
              {saved ? "Saved — try again" : "Save key"}
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
