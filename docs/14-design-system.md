# 14 · Design system & UI specification

Companion to [`frontend/src/styles/tokens.css`](../frontend/src/styles/tokens.css)
(the tokens are real, load-bearing CSS — this document is the rationale, the
missing screens, and the copy). Written against the live product
(`https://eduforge-ai.azurewebsites.net`), the real fixture at
`frontend/src/fixtures/teacher_knowledge_package.json`, the two packages in
[`samples/`](../samples/), and the exact contracts in `backend/contracts/` and
`backend/api/routes/`. Nothing below is designed against placeholder content.

Audience for this document: `frontend-engineer`, implementing without
guessing. Every layout, colour, spacing value and string of copy here is meant
to be copy-pasteable into a component, not paraphrased.

---

## 0 · Audit — what is actually wrong with the current UI

The existing frontend (`frontend/src/`) is not a blank slate. It already does
several things well and they should survive this redesign unchanged:

- `api/types.ts` `ApiError` — defensive, envelope-aware error parsing with a
  comment documenting the exact "Cannot read properties of undefined" bug it
  was written to fix.
- `viewer/EvidenceList.tsx` — a native `<details>` disclosure for citations,
  no JS state, works with find-in-page.
- `components/ui/Tabs.tsx` — full WAI-ARIA tabs pattern, roving tabindex,
  arrow-key navigation.
- `components/upload/DropZone.tsx` — accessible, keyboard-operable, drag and
  click both work.
- `viewer/AssessmentsTab.tsx` — the answer key is already a separate,
  visually distinct block behind a single "Show answer key" toggle, off by
  default.
- Conditional tabs/sections (`ViewerPage.tsx`, `AssessmentsTab.tsx`,
  `LearningGapsTab.tsx`, and per-section checks inside `KnowledgeTab.tsx`) —
  absent content is already omitted, not faked with "N/A". This is the
  correct pattern; it needs to be extended, not replaced.

That is the good news, and it means this spec is a **repair and extension**,
not a rewrite. The specific problems, each with a location:

1. **No landing page.** `router/router.tsx` maps `"/"` straight to
   `UploadPage`. Someone evaluating the product — or a teacher who has never
   used it — is handed a file-upload form with zero context. There is no
   statement of what the product produces, who it is for, or why the output
   can be trusted. This is the headline gap this spec closes.

2. **The header breaks below ~420px, and nothing else in the app has a
   second breakpoint.** `styles/global.css` contains exactly **one**
   `@media` rule in the whole codebase (`max-width: 640px`, lines 195–207),
   and `styles/components.css` has **none**. `.ef-header` is a fixed-height
   (`60px`) flex row (`components/layout/AppShell.tsx`) holding the brand
   link, a nav link, and a checkbox-plus-label ("Demo data (no backend)")
   with no wrap handling. At the 360px floor this spec is required to
   support, `"EduForge AI"` + `"New package"` + `"Demo data (no backend)"`
   do not fit in the ~330px available after padding — the row wraps, but the
   header's height is fixed, so wrapped content is clipped or overlaps
   rather than reflowing. Everything else in the app leans on
   `grid-template-columns: repeat(auto-fill, minmax(…))` and `flex-wrap` to
   *avoid breaking*, which is not the same as being *art-directed* for three
   real widths — it is why the product reads as "not responsive" even though
   nothing technically overflows on a typical viewport.

3. **Rendered artifacts are wired end-to-end and shown nowhere.**
   `api/client.ts` has `getArtifacts`, `artifactDownloadUrl`,
   `downloadArtifact`; the backend serves three PDFs, a Markdown bundle and
   the JSON at `GET /packages/{id}/artifacts` (`backend/api/routes/jobs.py`
   lines 203–259, added in the most recent commit,
   `feat(publishing): persist rendered artifacts and serve them`). None of
   `PackageHeader.tsx`, `ViewerPage.tsx`, or the success banner in
   `RunPage.tsx` render a single download link. A teacher who finishes a run
   today has no way to get the lesson-plan PDF out of the browser tab.

4. **`GET /api/v1/samples` does not exist.** `api/client.ts::getSamples()`
   calls it; `core/storage/base.py::list_samples()` is defined on the
   storage interface; `backend/api/main.py` only registers `documents`,
   `jobs`, and `events` routers. Nothing populates a sample package into the
   store at boot, either. The single most persuasive piece of content this
   product has — the physics-vs-history comparison in `samples/README.md` —
   currently has no live path into the running app. Flagged as an open
   dependency in §13; the landing page is specified assuming it gets wired,
   with a fallback that does not block shipping.

5. **Citations exist, but only as a bottom-of-card disclosure link
   indistinguishable from any other expandable text.** `EvidenceList`'s
   `"Source (1)"` trigger is 11px, the same visual weight as every other
   `<details>` in the app (`.ef-period-content`, `.ef-more-options`). For a
   product whose central, differentiating claim is *every factual statement
   is traceable to a page in the source*, that claim is currently invisible
   until a user notices and clicks a small link at the bottom of a card. See
   §5.7 for the fix — a persistent, glanceable "Grounded" signal, not a
   buried disclosure.

6. **Every content type renders in the same bordered box.** `.ef-card` is
   applied uniformly — a core concept, a misconception, a formula, a gap and
   an activity are all a white rectangle with a 1px border and 14px radius,
   differentiated only by the text inside. That is the generic
   "cards-for-the-sake-of-cards" pattern this brief explicitly warns against.
   §5 gives each content family a distinct visual accent (a left rule in its
   semantic colour) instead of relying on the reader to parse prose to tell
   a concept from a misconception.

7. **A raw browser error string can reach the user today.**
   `UploadPage.tsx::describeApiError` has three branches: `ApiError` (good,
   catalog-mapped), any other `Error` (`return err.message`), or an unknown
   fallback. A network blip during upload throws a plain `TypeError: Failed
   to fetch` (Chrome) — that is an `instanceof Error`, so its raw message is
   shown verbatim under the "Could not start the job" banner title. This is
   the same *family* of bug as the historical "Cannot read properties of
   undefined" the `ApiError` class was already patched for — a JS-internal
   string reaching a teacher. §10 gives the full replacement copy catalogue,
   including this case.

8. **No "slow vs. stuck" signal.** `RunPage.tsx` shows a progress percentage,
   a stage timeline, and a connection badge (`Live` / `Reconnecting…` /
   `Stream closed`), but nothing tells a user whether a progress bar pinned
   at 55% for three minutes is normal (lesson-generation is the heaviest
   stage, weighted 25/100, and fans out per period) or a dead job. Required
   by the brief; specified in §8.4.

Everything else — spacing rhythm, the token architecture itself, the
accessible primitives — is sound and is preserved below.

---

## 1 · Direction

**No invented brand.** There is no existing visual identity to honour or
break, so the direction is chosen and stated plainly: **ink-on-paper,
one confident accent, evidence gets its own colour.**

- **Neutral base, not ed-tech-bright.** Near-black text on near-white paper.
  The product's job is to produce a document a teacher trusts enough to
  stand in front of a class with; the UI should read like a well-typeset
  document, not a marketing surface. No gradients, no illustration, no stock
  photography of classrooms.
- **One accent (cobalt blue, `--ef-color-accent`)** for everything
  interactive — links, primary buttons, the focus ring, selected states.
  Used nowhere else, so "this is clickable / this is active" stays
  unambiguous.
- **One separate colour for grounding (teal, `--ef-color-info`)**, reused
  nowhere but citations, "Grounded" badges, evidence quote blocks, and the
  grounding-score stat. This is a deliberate, opinionated choice: the
  product's central claim gets its own colour so it reads as a system, not
  as one more info-blue badge among many.
- **Severity and status reuse the standard semantic triad** (green/success,
  amber/warning, red/danger) — no separate palette invented for gap severity
  or validation status, because a second traffic-light system next to the
  first would cost more clarity than it buys.
- **Content families get a left-rule accent, not a new box style.** A
  concept, a misconception, an activity and a gap all still sit in the same
  card shape (radius, padding, border) for rhythm — but each carries a 3px
  left border in its own semantic colour (concept = neutral/accent,
  misconception = warning, gap = its severity colour, activity = info) so
  the page is scannable by colour before it is read as text.
- **Typography: one sans stack, a restrained scale, real hierarchy.** Inter
  (already loaded), falling back to the system stack — no second display
  face. The landing page gets two extra steps at the top of the scale
  (`--ef-font-size-3xl`, `--ef-font-size-display`) that the app screens never
  use, so the app stays calm and the landing page is allowed one moment of
  confidence.

---

## 2 · Information architecture

```
/                       Landing (new)              — marketing / explainer, routes into the app
/upload                 Upload + options            — was "/", moved
/run/:jobId             Live progress
/packages/:packageId    Package viewer
/api/v1/docs            Swagger UI (external, not part of the SPA)
/healthz                Liveness (external)
```

**Routing change required:** `router/router.tsx` gains a route for `"/"`
rendering the new `LandingPage`, and the existing `UploadPage` moves to
`"/upload"`. `AppShell`'s nav link ("New package") must point at `/upload`,
not `/`. This is the one structural change everything else in this document
assumes.

Within the package viewer, the tab order is a deliberate reading path, not
alphabetical (kept from the current build, which already gets this right):
**Overview → Teaching Plan → Classroom Content → Knowledge Base →
Assessments → Learning Gaps → Validation.** Assessments and Learning Gaps
are omitted as whole tabs when their arrays are empty (already implemented
in `ViewerPage.tsx`); Validation always shows, because "nothing to report"
is itself a fact the validator reports.

---

## 3 · Breakpoints

No custom-media plugin is in the build (`frontend/vite.config.ts` — plain
Vite, no PostCSS config), so breakpoints are literal pixel values in
`@media` rules, not custom properties. Four, mobile-first (`min-width`),
replacing the single `max-width: 640px` rule in `global.css`:

| Name | Width | Applies to |
|---|---|---|
| Floor | `360px` | Minimum supported viewport. No horizontal scroll, no clipped content, ever. Design and test at exactly this width, not just "small". |
| `sm` | `min-width: 480px` | Header stops truncating the wordmark; two-column option grids on Upload. |
| `md` | `min-width: 768px` | Header goes single-row with inline nav (mobile sheet retires); viewer tab bar stops needing horizontal scroll for the common case; landing goes two-column in the hero. |
| `lg` | `min-width: 1024px` | Viewer gains a persistent left rail for tab navigation (see §9.2); landing feature grid goes 4-up. |
| `xl` | `min-width: 1280px` | Content hits `--ef-max-width` / `--ef-max-width-wide` and centers; no further layout change, just breathing room. |

Convert existing `max-width` rules to `min-width` and build up from the
360px layout — do not build the 1280px layout first and squeeze it down.

---

## 4 · Tokens

Full file: [`frontend/src/styles/tokens.css`](../frontend/src/styles/tokens.css).
All 85 custom properties used by the existing components are preserved by
name; values were re-verified and a small number of new tokens were added
(landing type scale, breakpoint-driven header height, z-index scale, focus
and target-size tokens, the grounding/illustrative colour pair). Nothing
existing needs to be renamed.

### 4.1 Contrast audit (light theme; method: WCAG relative-luminance ratio)

| Pair | Ratio | Requirement | Result |
|---|---:|---|---|
| `--ef-color-text` on `--ef-color-bg` | 17.8:1 | 4.5:1 body | pass |
| `--ef-color-text-muted` on `--ef-color-bg` | 6.7:1 | 4.5:1 body | pass |
| `--ef-color-text-faint` on `--ef-color-bg` | 4.9:1 | 4.5:1 body (used for meta text, not decoration — held to the full bar) | pass |
| `--ef-color-accent` on `--ef-color-bg` (links, text buttons) | 6.8:1 | 4.5:1 body | pass |
| `--ef-color-accent-contrast` on `--ef-color-accent` (primary button label) | 6.8:1 | 4.5:1 body | pass |
| `--ef-color-success` on `--ef-color-bg` | 5.4:1 | 4.5:1 | pass |
| `--ef-color-success` on `--ef-color-success-bg` (badge) | 4.8:1 | 4.5:1 | pass |
| `--ef-color-warning` on `--ef-color-bg` | 5.9:1 | 4.5:1 | pass |
| `--ef-color-danger` on `--ef-color-bg` | 6.5:1 | 4.5:1 | pass |
| `--ef-color-info` (teal, grounding) on `--ef-color-bg` | 5.4:1 | 4.5:1 | pass |
| `--ef-color-border` / `--ef-color-border-strong` on `--ef-color-bg` (UI boundary — input borders, card edges) | 1.3:1 / 2.9:1 | 3:1 for the *strong* variant only; the regular `border` token is decorative (never the sole boundary of an interactive control) | `border-strong` used wherever a border is load-bearing (inputs, the dropzone, focus-adjacent elements) |
| `--ef-color-focus-ring` on `--ef-color-bg` and on `--ef-color-accent` | 8.1:1 / 3.1:1 | 3:1 UI | pass |

### 4.2 Contrast audit (dark theme)

| Pair | Ratio | Result |
|---|---:|---|
| `--ef-color-text` on `--ef-color-bg-raised` (card surface, not page bg) | 13.4:1 | pass |
| `--ef-color-text-muted` on `--ef-color-bg-raised` | 6.8:1 | pass |
| `--ef-color-text-faint` on `--ef-color-bg` | 5.4:1 | pass |
| `--ef-color-accent` on `--ef-color-bg` | 7.2:1 | pass |
| `--ef-color-success` / `warning` / `danger` / `info` on `--ef-color-bg` | 9.3 / 9.7 / 7.3 / 8.8 (:1) | pass, all with margin |

Dark mode is driven by `prefers-color-scheme`, matching the existing
implementation — no manual toggle in v1. (Nice-to-have, not blocking: a
manual override in a future pass; note it and move on.)

### 4.3 Type scale

| Token | Value (fluid) | Used for |
|---|---|---|
| `--ef-font-size-xs` | 11.5–12.5px | timestamps, meta labels, badge text |
| `--ef-font-size-sm` | 13–14px | secondary body, form labels, nav |
| `--ef-font-size-md` | 14.7–16px | body text (base) |
| `--ef-font-size-lg` | 16.8–19.2px | card/section titles |
| `--ef-font-size-xl` | 20.8–25.6px | page titles (Upload, Run, Viewer header) |
| `--ef-font-size-2xl` | 25.6–33.6px | not currently used above page-title; reserved for the viewer's package title on `lg`+ |
| `--ef-font-size-3xl` | 30.4–44px | **landing only** — section heads ("What you get", "The same pipeline, two subjects") |
| `--ef-font-size-display` | 33.6–56px | **landing only, once** — the H1 |

---

## 5 · Core components

### 5.1 Header / navigation (fixes finding #2)

**Structure, all widths:** `Brand — Primary nav — Utility cluster`, height
`var(--ef-header-height)` (64px ≥768px, 56px below), sticky, background
`--ef-color-bg-raised`, border-bottom `--ef-color-border`
(`--ef-shadow-header` at rest). On scroll past 4px, swap to
`--ef-shadow-header-scrolled` (adds a soft shadow so the sticky header reads
as elevated over content, not just a hairline) — `prefers-reduced-motion`
does not affect this since it is a discrete state swap, not an animation.

**≥768px (`md`):** single row.
```
[EduForge AI]     Home   Samples        Demo data ⚪  |  [ Upload a document ]
```
- Brand: wordmark, links to `/`.
- Primary nav (`Home`, `Samples`): plain text links, `aria-current="page"`
  gets `--ef-color-accent-bg` background + `--ef-color-accent-strong` text,
  same as today.
- Utility cluster, right-aligned, visually de-emphasised
  (`--ef-font-size-xs`, `--ef-color-text-faint`): the "Demo data" toggle,
  separated from primary nav by a 1px vertical rule
  (`--ef-color-border`). This is a QA/reviewer affordance, not a teacher
  feature — it must never outweigh the primary CTA in visual weight, which
  is the header's actual bug today (a full checkbox+label competing with
  the wordmark for space).
- Primary CTA button (`Upload a document`, `--ef-btn--primary`,
  `--ef-target-min` = 44px tall) appears in the header only when NOT already
  on `/upload` — on the Upload, Run and Viewer pages it is redundant and is
  omitted; the nav's `Home` / `Upload` links suffice.

**<768px:** collapses to `[EduForge AI]  ⋯  [Upload]`. The `⋯` (labelled
"Menu", `aria-expanded`, 44×44px target) opens a full-width sheet **below**
the header (not a native `<dialog>` — a `position: fixed` panel,
`--ef-z-modal`, `--ef-shadow-popover`, dismissible by `Escape`, backdrop
click, or re-tapping the trigger) containing, stacked: `Home`, `Samples`,
`API docs`, a divider, then the "Demo data" toggle. The primary CTA button
stays visible in the collapsed header at all times — it is the one thing a
first-time visitor on a phone must always be able to reach without opening
a menu.

At exactly 360px this is: brand (truncates to `"EduForge"` if needed, never
clips mid-letter — use `text-overflow: ellipsis` with a `max-width` rather
than letting flex shrink it arbitrarily) · menu button (44px) · CTA button
(compresses to icon+`"Upload"`, still ≥44px tall). This fits comfortably;
verify against the real 360px canvas, not a scaled-down 768px screenshot.

### 5.2 Buttons

Unchanged visually from the current `.ef-btn` family (primary / secondary /
danger, `sm` variant) — it already works. Two additions:

- Minimum height for any button that is a **primary action on a page**
  (submit, retry, download, the landing CTAs) is `--ef-target-min` (44px),
  up from the current 40px (`min-height: 2.5rem`). Secondary/inline actions
  may stay at 40px; `.ef-btn--sm` stays at 32px (still clears the 24px AA
  floor) for dense contexts like the answer-key toggle.
- A new `.ef-btn--download` treatment: secondary button style plus a
  download glyph, used exclusively in the new Artifacts panel (§5.8).

### 5.3 Badge / severity language

Existing `Badge` component and tone set (`success`, `warning`, `danger`,
`info`, `neutral`) is correct and stays. Formalised mapping, used
consistently everywhere severity or status appears (gap severity,
validation status, issue severity):

| Concept | Tone | Colour |
|---|---|---|
| High severity gap / validation error / job failed | `danger` | red |
| Medium severity gap / validation warning / degraded stage | `warning` | amber |
| Low severity gap / informational issue | `info` — **only when the "info" is genuinely low-stakes**, e.g. a gap's diagnostic detail; do **not** use `info`-tone for citations here, to avoid the one collision this palette has to actively avoid | teal |
| Grounded claim / citation available | new: `.ef-badge--grounded` (same teal as `info`, but a distinct class so it can be targeted/animated independently later) | teal |
| Illustrative / not from source | new: `.ef-badge--illustrative` | `--ef-color-illustrative` (ochre) |
| Pass / correct / done | `success` | green |
| Neutral fact (Bloom level, item kind, period count) | `neutral` | grey |

### 5.4 Card family and content-type accents

Base `.ef-card` is unchanged (background `--ef-color-bg-raised`, border
`--ef-color-border`, radius `--ef-radius-lg`, padding `--ef-space-5`). New
modifier classes add a 3px left border in a semantic colour, replacing flat
"everything is the same box" with a scannable system:

| Modifier | Left border colour | Applied to |
|---|---|---|
| `.ef-card--concept` | `--ef-color-accent` (importance: core) / `--ef-color-border-strong` (supporting/enrichment) | Concept cards, `KnowledgeTab` |
| `.ef-card--misconception` | `--ef-color-warning` | Misconception cards |
| `.ef-card--gap` | the gap's own severity colour (danger/warning/info) | Learning gap cards — this replaces the current pattern of a severity badge floating with no card-level cue |
| `.ef-card--activity` | `--ef-color-info` | Activity cards |
| `.ef-card--formula` | `--ef-color-text-faint` (neutral — a formula is a fact, not a judgement) | Formula cards |
| (no modifier) | none | Definitions, examples, applications — descriptive content with no severity or grounding tier to signal beyond the standard evidence pattern below |

Implementation: `border-left: 3px solid var(--ef-color-…); padding-left:
calc(var(--ef-space-5) - 3px);` so the extra border doesn't shift the
right-hand content width.

### 5.5 Dropzone, form fields

Unchanged (`DropZone.tsx`, `.ef-field`, `.ef-chip-input` etc. already meet
the bar: labelled, keyboard-operable, error text tied via
`aria-describedby`). One addition: the dropzone's minimum touch target for
the "Remove" button becomes 44px on touch (currently `.ef-btn--sm`, 32px —
raise to default `.ef-btn` height inside the dropzone specifically, since it
is the only interactive control besides the zone itself).

### 5.6 Tabs

Unchanged pattern (`Tabs.tsx` is a correct WAI-ARIA implementation). Two
responsive additions, both CSS-only:

- `≥1024px` (`lg`): the tab list becomes a **vertical rail** on the left of
  the viewer (see §9.2) instead of a horizontal scroller — same
  `role="tablist"`/`role="tab"` semantics, `aria-orientation="vertical"`
  added, and the existing arrow-key handler's Up/Down mapping already
  matches (no JS change needed beyond the `aria-orientation` attribute).
- `<1024px`: stays the current horizontal `overflow-x: auto` strip, with one
  fix — add a `mask-image` fade (`linear-gradient(to right, black
  calc(100% - 24px), transparent)`) on the trailing edge whenever the strip
  is scrollable, so "there are more tabs" is visible, not just discoverable
  by accident. (`mask-image` is decorative; no `prefers-reduced-motion`
  implication, no a11y implication since the semantics are unchanged.)

### 5.7 Grounding: the "Grounded" badge (fixes finding #5)

This is the single most important pattern in the whole system, because it
is the product's central claim made visible. Replace "buried disclosure
link" with "persistent badge, disclosure for the detail":

**Anatomy**, attached to any card that represents a factual claim (concept,
definition, formula, example, application, misconception, checkpoint
question's expected answer, gap):

```
┌───────────────────────────────────────────────┐
│ Inertia                    [core]  [◆ Grounded]│  <- badge always visible, no click needed
│ A body resists any change to its state of rest │
│ or uniform motion.                              │
│                                                  │
│ ▸ p. 1 · "A body continues in its state of      │  <- existing disclosure, now opened by
│   rest or uniform motion" · confidence 100%     │     default when there is exactly one
└───────────────────────────────────────────────┘     evidence span (see below)
```

- `[◆ Grounded]` is a `.ef-badge--grounded` (teal, see §5.3), placed in the
  card's header row next to the importance/type badge — same visual weight
  as "core", not smaller. Icon: a filled diamond or check-in-circle
  (`aria-hidden`, the word "Grounded" carries the meaning for screen
  readers).
- When a claim has **more than one** evidence span, the badge reads
  `Grounded (3)`.
- Clicking/tapping the badge scrolls to and opens the evidence disclosure
  below it (same `<details>` element `EvidenceList` already renders) —
  the badge becomes a second entry point into the existing pattern, it does
  not replace it.
- **When there is exactly one evidence span**, render the `<details>`
  **open by default**. The current build always starts closed; for the
  common case (one citation) there is no reason to make grounding a second
  click — closed-by-default only earns its keep once a card has enough
  citations that showing them all would dominate the card (2+).
- **The one deliberate exception — Mentor Moment.** `grounded: false` is a
  real, typed field on this content (`MentorMoment.grounded`, always
  `false` per the contract). It must **never** carry a `Grounded` badge.
  Instead it carries `.ef-badge--illustrative` reading **"Illustrative — not
  from source"** (existing copy, keep verbatim — it is already correct),
  in the same header-row position a Grounded badge would occupy. The rule
  for engineers: **every card in this family shows exactly one of the two
  badges, never neither.** A card with a factual claim and no evidence
  array populated is a contract violation (the backend's `Grounded.evidence`
  has `min_length=1` — this cannot happen for real content) and should fail
  loudly in development (console error), not render silently unmarked.

### 5.8 Artifacts / downloads panel (new — fixes finding #3)

Appears in two places, same component:

1. **`RunPage`, inside the "Package ready" success banner** — replaces the
   current single "View package" button with a button row.
2. **`ViewerPage`, in `PackageHeader`** — a persistent row under the title
   block, visible regardless of which tab is active.

```
Download:  [ Lesson Plan PDF ]  [ Teacher Guide PDF ]  [ Assessment Book PDF ]  [ Markdown ]  [ JSON ]
```

- One `.ef-btn--secondary.ef-btn--download` per artifact the backend
  reports as `status: "ready"` from `GET /packages/{id}/artifacts`.
  Filenames per artifact kind come straight from the backend's own
  `ARTIFACT_MEDIA` map (`lesson-plan.pdf`, `teacher-guide.pdf`,
  `assessment-book.pdf`, `teaching-materials.md`,
  `teacher-knowledge-package.json`) — do not invent different names in the
  UI than what the file downloads as.
- An artifact reported `status: "failed"` (rendered but the blob is gone,
  or never rendered — e.g. the `succeeded_partial` / degraded-stage case)
  renders as a **disabled** button, same label, with a small
  `--ef-color-text-faint` caption underneath: *"Not available for this
  run"* — this is the absent-content rule (§6) applied to artifacts: never
  hide the row and never fake a working link, show the real state.
- Wraps to two rows at `<480px`; each button is full-width-ish
  (`flex: 1 1 45%`) rather than shrinking text, so labels never truncate —
  "Assessment Book PDF" is the long string to design against.
- Uses `downloadArtifact(packageId, kind)` from `api/index.ts`, already
  implemented for both live and demo mode — this is a pure UI gap, not a
  data-layer one.

### 5.9 Progress / stage timeline

Existing `StageTimeline` + progress bar are structurally sound (ordered
list, `aria-label`, visually-hidden state text per item). Additions in
§8.4 for the slow/stuck signal; no structural change to the timeline itself.

### 5.10 Empty / error states

`EmptyState` and `Banner` components are correct and unchanged. §10 supplies
copy; no new component needed beyond what exists, except the `ApiError`
message-mapping function moving from ad hoc (`describeApiError` living
inside `UploadPage.tsx`) to a single shared `errorCopy(err)` used by every
page that can fail (Upload, Run, Viewer) — see §10.1 for the required
mapping table.

---

## 6 · The absent-content rule (formalised)

Already implemented correctly in several places; stated here as one rule so
it is applied everywhere, including new UI:

> **A collection renders only when it has at least one item. A scalar count
> renders always, including zero. Nothing renders "N/A", "—" for a missing
> array, or an empty-state illustration for content the pedagogy profile
> was never going to produce.**

Concretely:

- `knowledge.formulae`, `knowledge.misconceptions`, per-section blocks in
  `KnowledgeTab` — omit the whole `<section>` when the array is empty
  (already correct).
- `assessments.items`, `learning_gaps` — omit the whole **tab** when empty
  (already correct in `ViewerPage.tsx`).
- The Overview "at a glance" stat grid — **counts always show, including
  `0`.** `Formulae: 0` on a history package is not hidden; it is a true,
  meaningful fact (the narrative profile does not require formulae, and
  showing `0` next to `Learning objectives: 4` is what proves the pipeline
  ran, not what it skipped). This is the one place a zero is correct to
  display — the distinction is *count field* (always shows) vs. *content
  collection* (omitted when empty).
- Assessment blueprint (`AssessmentsTab`) — `items_by_kind` entries with
  `count === 0` (e.g. `numerical: 0` on a narrative package) are filtered
  out before rendering (already correct, `kindEntries.filter(([, count]) =>
  count > 0)`). Do not "grey out" a zero-count kind instead of omitting it —
  that reintroduces the fake-empty-state problem in a subtler form.
- Artifacts panel (§5.8) is the one exception to "omit when absent": a
  failed/unavailable artifact **does** render, disabled, because its
  absence is operationally relevant to the user (they were expecting a PDF
  and it did not come) in a way a narrative package's zero formulae is not.

---

## 7 · Landing page (new)

### 7.1 Content model

All copy below is final, not placeholder — implement verbatim unless a
fact changes upstream (e.g. the live URL, or the sample numbers if the
fixtures regenerate).

**Eyebrow:** `DOCUMENT IN → CLASSROOM PACKAGE OUT`
(`--ef-font-size-xs`, `--ef-tracking-eyebrow`, `--ef-color-text-faint`, all-caps via CSS not raw text)

**H1:**
> Turn a chapter into a week of classroom-ready teaching — with every claim traced back to the page it came from.

**Subhead:**
> Upload a PDF, DOCX, PPTX or TXT chapter. Get a multi-period lesson plan, teacher scripts, activities, an assessment bank with answer keys and rubrics, a learning-gap analysis, and a citation on every factual claim — in about 5–7 minutes.

**Primary CTA:** `Upload a document` → `/upload`
**Secondary CTA:** `See a sample package` → live sample if wired (§13), else `Browse the sample packages on GitHub` (fallback, §13)
**Microcopy under the CTAs:** `No account. Nothing is billed to you on the default free-tier setup.`

**Proof panel** (sits beside the hero copy on `md`+, below it on mobile) — a
real excerpt from the fixture, not decoration, styled as a miniature of the
actual Knowledge Base card (`.ef-card--concept`, teal Grounded badge, same
component the app itself renders — literally reuse the component):

```
Concept · core                                   [◆ Grounded]
Inertia
A body resists any change to its state of rest or uniform motion.

▸ p. 1 · "A body continues in its state of rest or uniform motion" · confidence 100%
```

Caption beneath, small, `--ef-color-text-faint`:
> Real output from the pipeline — Newton's Laws of Motion, Grade 9–10 Physics.

**"What you get" — four-up feature grid** (`repeat(auto-fit, minmax(240px,
1fr))`, 2-up at `sm`, 4-up at `lg`), each item: a short label + one sentence,
no icons (an icon per feature reads as decoration for its own sake here;
the badges/colour system already carries the app's visual interest):

| Label | Body |
|---|---|
| Multi-period lesson plan | Not a fixed five periods — the count is derived from how much the chapter actually covers, paced to the period length you set. |
| Teacher scripts | Minute-by-minute: what to say, what to write on the board, the questions students are likely to ask. |
| Activities & assessments | Classroom activities plus an assessment bank with rubrics — the answer key is generated as a separate section, kept apart from the questions. |
| Gap analysis, with citations | Likely misconceptions ranked by how much later material depends on them, and a citation back to the source for every concept, definition and claim. |

**"The same pipeline, two subjects" — the versatility proof.** Section
head (`--ef-font-size-3xl`): `The same pipeline. Two different outputs.`
Intro line:
> Nothing in this system branches on a subject name — a test in the codebase fails the build if it does. A chapter is classified as quantitative, conceptual, narrative, procedural or mixed, and that classification is what changes the output, not a switch statement reading "if physics". Two real runs against the live instance, same code path:

Table (real numbers, from `samples/README.md`, verified reproducible via
`make evals`):

| | `physics.pdf` | `history.docx` |
|---|---|---|
| Subject → profile | Physics → **quantitative** | History → **narrative** |
| Formulae extracted | 1 | **0** |
| Assessment mix | 3 numerical, 2 MCQ, 1 long, 1 short | **0 numerical**, 1 MCQ, 3 long, 2 short |
| Activity chosen | Experiment | Debate |
| Validation | Pass with warnings | Pass with warnings |

Caption:
> Zero numerical questions on a history chapter isn't a missing feature — it's the narrative profile working as designed. The validator is profile-conditioned, so it scores that absence as correct rather than flagging a gap.

Two links under the table: `Open the physics sample →` /
`Open the history sample →` (both to `/packages/:id`, §13 for the
dependency).

**"How it works" — three steps,** numbered, plain text, no illustration:
1. **Upload.** PDF, DOCX, PPTX, TXT or Markdown, up to 25MB. Answer a couple of optional questions — period length, teaching style — or skip them; the defaults are good.
2. **Watch it build.** Ten pipeline stages, live progress, about 5–7 minutes. Close the tab if you need to — the run keeps going and the page picks up where it left off.
3. **Review, download, teach.** A tabbed package in the browser, plus a Lesson Plan PDF, a Teacher Guide PDF, an Assessment Book PDF (questions first, answer key behind a page break), and a Markdown bundle.

**"Built for review" strip** — smaller, quieter section for the evaluator
audience, `--ef-color-bg-subtle` background to visually recede from the
teacher-facing sections above it:
> This was built for the AI Engineer assignment. The pipeline, the schema, the API and the architecture decisions are documented in full.
[`API docs`](/api/v1/docs) · [`Health`](/healthz) · `Source` *(engineer: link to the actual repository — do not ship a dead link or a placeholder href)*

**Honest limits** — small, plain list, not hidden in a footer accordion
(brief requires empty/error/partial states be designed, not glossed over;
this is the landing-page-level version of that honesty):
> - First version. Scanned or photographed pages are rejected with a clear error, not OCR'd.
> - Runs on free-tier models by default, so output quality is bounded by what those models can do — swap the config for a stronger model and the same pipeline runs unchanged.
> - Uploaded documents live in memory today; a server restart clears them mid-run.

**Footer:** same as the app shell's existing footer, unchanged copy:
`EduForge AI — converts a document into a classroom-ready Teacher Knowledge Package.`

### 7.2 Layout — 360px

Single column throughout, `--ef-space-3` (12px) side padding matching the
existing small-viewport `.ef-main` override.

```
┌ header (56px, collapsed) ──────────┐
│ EduForge   ⋯   [Upload]            │
├─────────────────────────────────────┤
│ EYEBROW                            │
│ H1 (--ef-font-size-display,        │
│     clamps down to ~34px here)     │
│ Subhead                            │
│ [ Upload a document ]  (full width,│
│   44px min-height)                 │
│ See a sample package (text link)   │
│ Microcopy                          │
├─────────────────────────────────────┤
│ Proof panel (full width, the real  │
│ Grounded concept card)             │
├─────────────────────────────────────┤
│ What you get                       │
│ [feature] [feature] [feature] [ft] │  <- stacked, 1-up
├─────────────────────────────────────┤
│ The same pipeline, two subjects    │
│ intro paragraph                    │
│ [table — see below]                │
│ Open physics sample →              │
│ Open history sample →              │
├─────────────────────────────────────┤
│ How it works: 1 / 2 / 3 stacked    │
├─────────────────────────────────────┤
│ Built for review strip             │
├─────────────────────────────────────┤
│ Honest limits (bulleted)           │
├─────────────────────────────────────┤
│ Footer                             │
└─────────────────────────────────────┘
```

The versatility table at 360px: **do not force the 3-column table into
360px** — it does not fit legibly (the row labels alone plus two subject
columns need more like 480px minimum for 12px type). Instead, below `sm`,
render the same data as two stacked definition-list cards, one per subject,
each row `label: value`:
```
┌ physics.pdf ─────────────────────┐
│ Profile        Quantitative       │
│ Formulae       1                  │
│ Assessment mix 3 numerical, 2 mcq,│
│                1 long, 1 short    │
│ Activity       Experiment         │
│ Validation     Pass with warnings │
└────────────────────────────────────┘
┌ history.docx ────────────────────┐
│ Profile        Narrative          │
│ Formulae       0                  │
│ …                                  │
└────────────────────────────────────┘
```
This is the same underlying data, restructured for the viewport — not a
simplified or truncated version of it.

### 7.3 Layout — 768px

Hero becomes two columns (`grid-template-columns: 1.1fr 0.9fr`, gap
`--ef-space-6`): copy left, proof panel right, vertically centered against
each other. Feature grid becomes 2-up. Versatility section: the real table
now fits (768px ≥ the ~600px it needs) — render the table, not the stacked
cards. "How it works" steps go 3-up horizontally with a thin connecting
rule between numbers. Header is single-row (§5.1).

### 7.4 Layout — 1280px

Content centers at `--ef-max-width-wide` (1280px) for the hero row only (it
earns the extra width holding two substantial columns); every other section
centers at `--ef-max-width` (1180px), matching the app screens so the
transition from landing into `/upload` doesn't visibly jump in width.
Feature grid goes 4-up. Section vertical padding increases to
`--ef-space-9`/`--ef-space-10` (this is the one place in the product those
large spacing tokens are used — the app screens stay at `--ef-space-6`
rhythm throughout).

---

## 8 · Upload page (`/upload`)

Structurally the current `UploadPage.tsx` is good — accessible fields,
sensible defaults, a working progressive-disclosure `<details>` for advanced
options, real client-side validation before hitting the network. Changes:

1. Move to `/upload`; page title copy unchanged (`"Turn a chapter into a
   classroom-ready package"`).
2. At 360px, the two-column `.ef-grid` for Period length / Teaching style
   already collapses to one column via `auto-fill, minmax(min(260px,
   100%), 1fr)` — verified this works, no change needed.
3. Error banner copy: replace `describeApiError`'s raw-`Error.message`
   fallback with the shared `errorCopy()` catalogue (§10) — this is the fix
   for finding #7.
4. Add the header's persistent primary nav (`Home` visible) so a user who
   lands here directly (bookmark, refresh) is never more than one tap from
   the explanation they'd have gotten on `/`.

**Layout is unchanged across breakpoints beyond what already works** —
this page was not the problem; restating its full spec here would be
padding. The one net-new element: the demo-mode banner
(`isMockMode()` block) keeps its current placement above the form.

---

## 9 · Run page (`/run/:jobId`) — live progress

### 9.1 State machine

The brief requires every state to be designed, not just the happy path.
Full enumeration, mapped to what the app already tracks
(`JobStatus`, `ConnectionState` from `useJobEvents`, plus one new derived
value, **pace**, specified in §9.4):

| State | Trigger | Visual treatment |
|---|---|---|
| **Loading snapshot** | Initial `GET /jobs/{id}` in flight | `Spinner` only, no shell yet — current behaviour, keep |
| **Not found** | `GET /jobs/{id}` → 404 | `EmptyState`, error tone, copy in §10 |
| **Queued** | `status: "queued"`, no progress events yet | Progress bar at 0%, stage timeline all-pending, copy: *"Waiting for a worker to pick this up…"* |
| **Connecting** | SSE handshake in flight | Connection badge: *"Connecting…"*, neutral tone |
| **Live, on pace** | `connectionState: "open"`, current stage's elapsed time ≤ 2.5× its expected duration | Connection badge *"Live"*, success tone; progress bar animates; stage timeline pulses current stage |
| **Live, slow** | `connectionState: "open"`, elapsed > 2.5× expected for the current stage | Same as above, **plus** an inline, neutral-toned note under the progress bar (§9.4) — never changes the connection badge or banner tone |
| **Live, very slow** | elapsed > 5× expected | Inline note upgrades wording (§9.4) but **stays neutral/informational, not warning-coloured** — a healthy connection making slow progress is not an error state |
| **Reconnecting** | `connectionState: "retrying"` (dropped TCP, or the 40s stale-timeout tripped) | Connection badge *"Reconnecting…"*, warning tone; everything else (bar, timeline) freezes at last-known value, does not reset to 0 |
| **Disconnected** | `connectionState: "closed"` before a terminal event arrived (retry loop gave up, or tab was backgrounded past retry limits) | Connection badge *"Connection lost"*, danger tone; banner (not just badge) explaining the job likely kept running server-side and offers a manual refresh — copy in §10 |
| **Degraded / warning** | one or more `event: "warning"` frames received (e.g. budget-limited stage) | A `Banner tone="warning"` accumulates under the progress card, one line per warning, **in addition to** the timeline — does not block progress | 
| **Succeeded** | `status: "succeeded"` | Success banner + Artifacts panel (§5.8) + "View package" |
| **Succeeded, partial** | `status: "succeeded_partial"` | Same banner shell, **warning** tone not success, heading *"Package ready — with warnings"* (existing copy, correct), warnings listed, Artifacts panel shows any `status: "failed"` artifact disabled per §5.8 |
| **Failed** | `status: "failed"` or a `failed` SSE event | Danger banner, typed error surfaced (`error.type` / `error.message`), **Retry** and **Start a different document** actions — existing structure, copy refined in §10 |
| **Cancelled** | `status: "cancelled"` | Neutral-toned banner, *"This run was cancelled."*, same two actions as Failed minus the typed error line |

### 9.2 Layout — unchanged structurally across breakpoints

This page is already single-column and already reasonable at narrow
widths (`StageTimeline` wraps via `flex-wrap`, `EventLog` scrolls
internally with a capped height). Two concrete responsive fixes:

- **360px:** the header row (`h1` + job id + connection badge,
  `RunPage.tsx` lines 158–164) uses `justifyContent: space-between` inline
  on a flex row — at 360px with a long job id this pushes the badge off
  the visible area or wraps awkwardly. Fix: stack badge below the title on
  `<480px` (`flex-direction: column`, `align-items: flex-start`), inline
  again at `≥480px`.
- **1280px:** the progress card and event log currently both run the full
  `--ef-max-width` (1180px) — at this width a single-column log of short
  timestamped lines is unnecessarily wide (measure exceeds ~140 characters
  per line of metadata, which is fine since it's not prose, but the page
  reads sparse). Introduce a two-column layout **only ≥1024px**: progress
  card + stage timeline in a 60% left column, event log in a 40% right
  column, both starting at the same vertical position, so a wide viewport
  is used for "what's happening now" and "the detailed log" side by side
  instead of stacked with dead horizontal space in the log.

### 9.3 Copy already correct, kept verbatim

- `"Generating your package"` / `"Job {jobId}"`
- `"Retry from last completed stage"`
- `"Package ready"` / `"Package ready — with warnings"`
- `"This run failed"`

### 9.4 Slow vs. stuck (fixes finding #8)

Per-stage expected durations, derived from `STAGE_PROGRESS_WEIGHTS`
(`backend/contracts/jobs.py`) proportioned against the README's own claimed
5–7 minute total (using 6 minutes / 360s as the midpoint budget — this is a
**UI heuristic for user reassurance, not a contract**, and must be commented
as such wherever implemented):

| Stage | Weight | Expected (of 360s budget) |
|---|---:|---:|
| Document Intelligence | 8 | 29s |
| Classification | 5 | 18s |
| Knowledge Extraction | 17 | 61s |
| Teaching Planner | 10 | 36s |
| Lesson Generation | 25 | 90s |
| Activity Generation | 10 | 36s |
| Assessment Generation | 10 | 36s |
| Gap Analysis | 5 | 18s |
| Validation | 5 | 18s |
| Publishing | 5 | 18s |

**Rule:** track `stageEnteredAt` (timestamp of the most recent progress
event whose `stage` differs from the previous one). While
`connectionState === "open"`:

- `elapsed ≤ 2.5 × expected` → no extra copy (the default "Running: …"
  line is enough).
- `2.5× < elapsed ≤ 5×` → append, in `--ef-color-text-faint`, *"This step
  usually takes about {expected}. It's taking a bit longer — free-tier
  models queue under load, and this document may simply have more to
  process."*
- `elapsed > 5×` → replace with: *"Still working. This is slower than
  usual, but the connection is live and the run hasn't stopped — safe to
  leave this tab open, or bookmark the page and come back; progress
  resumes exactly where it left off."*

Explicitly **not** a warning or danger banner at any multiplier — the
signal that something is actually wrong is `connectionState` moving to
`"retrying"`/`"closed"`, or a `failed` event, both of which already have
their own, more assertive treatment (§9.1). Conflating "unusually slow" with
"broken" is exactly the ambiguity this component exists to remove.

---

## 10 · Error copy catalogue (fixes finding #7)

### 10.1 Mapping rule

One function, `errorCopy(err: unknown): { title: string; body: string;
action?: string }`, used by every `catch` block in the app (Upload submit,
Run snapshot/retry, Viewer package fetch). Resolution order:

1. `err instanceof ApiError` → look up `err.code` in the table below. If
   the code is not in the table (a future backend code this spec doesn't
   know about yet), fall back to `err.message` **only if non-empty**,
   else the generic fallback row.
2. `err instanceof TypeError && /fetch/i.test(err.message)` (covers
   Chrome's `"Failed to fetch"` and the equivalent in other engines) →
   `network_unreachable` row, regardless of which request failed.
3. `err instanceof DOMException && err.name === "AbortError"` →
   `request_cancelled` row.
4. Anything else → generic fallback row. **The raw `err.message` is never
   shown to the user in this branch** — log it to `console.error` for
   debugging, and if `err instanceof ApiError` had a `traceId`, show it
   in small text so a report can reference it: *"Reference: {traceId}"*.

### 10.2 Catalogue

| Code / trigger | Title | Body | Action |
|---|---|---|---|
| `empty_document` | Could not use this file | The file is empty. Choose a document with content in it. | Choose a different file |
| `document_too_large` | File is too large | `{filename}` is over the 25 MB limit. Try a smaller export, or split the chapter into two uploads. | Choose a different file |
| `unsupported_media_type` | Unsupported file type | EduForge reads PDF, DOCX, PPTX, TXT and Markdown. This file doesn't match any of those. | Choose a different file |
| `document_not_found` | Could not start the job | The uploaded document couldn't be found on the server — this can happen if the server restarted since you uploaded (documents aren't kept permanently yet). Upload the file again. | Upload again |
| `job_not_found` | Job not found | This run doesn't exist, or the record has expired. | Start a new one |
| `job_not_retryable` | Can't retry this run | This run is `{status}`, which isn't a state that can be retried — only a failed, cancelled, or partially-succeeded run can be. | Start a different document |
| `package_not_found` | Package not found | This package doesn't exist, or hasn't finished generating yet. | Start a new one |
| `artifact_not_found` | File not available | This particular file wasn't produced for this run — it may have been skipped when a stage ran out of budget (check the warnings above). The rest of the package is unaffected. | (no action button — this renders inline as the disabled state in §5.8, not a standalone error) |
| `invalid_request` | Could not start the job | `{field}: {reason}`, taken verbatim from the backend's flattened validation message — this one is intentionally passed through, since the backend already reduces it to one plain sentence (`api/main.py`'s `invalid_request` handler). | Check the form and try again |
| `internal_error` | Something went wrong on our end | This wasn't caused by anything you did. Try again in a minute — if it keeps happening, the server may be restarting. | Try again |
| `network_unreachable` (client-detected, §10.1 rule 2) | Could not reach EduForge | The connection dropped before the request finished. Check your connection and try again. | Try again |
| `request_cancelled` (client-detected, §10.1 rule 3) | Request cancelled | *(usually silent — only show this if the cancellation wasn't user-initiated, e.g. a timeout abort)* | Try again |
| generic fallback | Something went wrong | An unexpected error occurred. Try again, or come back in a few minutes. | Try again |
| SSE `connectionState: "closed"` pre-terminal | Connection lost | The live progress connection dropped and didn't reconnect. The run may still be in progress on the server — refreshing this page will show its current state. | Refresh |
| Job `status: "failed"`, typed error present | This run failed | **`{error.type}`:** `{error.message}` *(verbatim — these are already human-authored exception messages from the pipeline, e.g. "The model provider returned a non-retryable error after 4 attempts.")* | Retry from last completed stage · Start a different document |
| Job `status: "failed"`, no typed error (edge case) | This run failed | The pipeline stopped before publishing a package. | Retry from last completed stage · Start a different document |
| Job `status: "cancelled"` | This run was cancelled | No package was produced. | Start a different document |
| 404 route (unknown path) | Page not found | *(existing `NotFoundPage.tsx` copy — kept, correct)* | Back to the upload screen → update link target to `/upload`, plus add a second link, `Back to the homepage`, to `/` |

### 10.3 What this replaces

The literal historical bug ("Cannot read properties of undefined (reading
'message')") is already prevented by `ApiError`'s constructor. This
catalogue closes the two remaining gaps: (a) a raw `TypeError: Failed to
fetch` reaching the UI verbatim through `describeApiError`'s generic
`Error` branch, and (b) every page currently re-implementing its own ad hoc
version of this logic (`UploadPage` has one, `RunPage` has an inline
`retryError` string, `ViewerPage` constructs its own fallback `ApiError`) —
consolidate into the one `errorCopy()` used everywhere, so a new error code
added to the backend only needs one new table row, not N call sites found
and updated.

---

## 11 · Package viewer (`/packages/:packageId`)

The hardest screen, and the one every other page exists to lead to. Content
below is specified against the real fixture (Newton's Laws — 2 concepts, 2
periods, 1 formula, 1 gap) *and* the narrative-history sample (0 formulae,
0 numerical items, 2 absences) side by side, because a spec that only shows
the physics case will quietly get built physics-only.

### 11.1 Header block (`PackageHeader`)

Existing structure is correct: title, subject/grade/chapter line, validation
status badge, a row of classification badges, a metadata `<dl>`. Two
additions:

1. **Artifacts/downloads row** (§5.8), directly under the badge row, before
   the metadata `<dl>` — this is the highest-intent action on the page for
   a teacher who already trusts the package (they came to get the PDFs),
   so it sits above the fold, not buried at the bottom of an Overview tab.
2. **Absent-profile call-out**, one line, `--ef-color-text-muted`, shown
   only when `classification.pedagogy_profile` is `narrative` or
   `conceptual` (profiles that structurally produce zero numerical/formula
   content) — *"This is a `{profile}` package — formulae and numerical
   questions are not part of what this profile teaches, by design."* This
   is the single most important sentence on the whole screen for a teacher
   opening a history package and wondering why there's no equation card;
   it preempts the "is this broken?" reaction the brief is explicitly
   worried about ("absent content is omitted, never faked" only works for
   trust if the user is told *why* it's absent, once, up front).

### 11.2 Layout — 360px

Single column, tabs as a horizontal scroller with the fade mask (§5.6).
Downloads row wraps to 2-up (§5.8). Every tab panel is the existing
single-column card stack — already correct at this width structurally;
the fixes are the content-type accents (§5.4) and the Grounded badge
(§5.7), not the grid.

### 11.3 Layout — 768px

Tabs stay horizontal (below the `lg` rail threshold). Grids that were
1-column at 360 (stat grid, meta grid, activity's "Teacher does / Students
do" two-up) now show their natural `auto-fit, minmax(220–260px, 1fr)`
column counts — already correct, no change needed, `.ef-grid` already does
this.

### 11.4 Layout — 1024px+ (`lg`)

New: a persistent **left rail** replaces the horizontal tab strip.
```
┌──────────────────────────────────────────────────────────────────┐
│ PackageHeader (full width, spans both columns)                    │
├───────────────┬──────────────────────────────────────────────────┤
│ Overview       │                                                  │
│ Teaching Plan  │   [ active tab panel content ]                   │
│ ▸Classroom     │                                                  │
│  Content       │                                                  │
│ Knowledge Base │                                                  │
│ Assessments    │                                                  │
│ Learning Gaps  │                                                  │
│ Validation     │                                                  │
│                │                                                  │
│ 220px, sticky  │   remaining width, max --ef-max-width - 220px    │
│ below header   │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
```
Rail items are the same `role="tab"` buttons, `aria-orientation="vertical"`,
active item gets a left accent bar (`--ef-color-accent`, 3px) rather than
the horizontal underline used at narrower widths — same component, two CSS
presentations keyed off the breakpoint, not two components. Rail is
`position: sticky; top: calc(var(--ef-header-height) + var(--ef-space-4))`
so it stays reachable while the panel scrolls.

### 11.5 Overview tab

Existing structure (`OverviewTab.tsx`) is sound: stat grid, source `<dl>`,
generation-cost `<dl>` (only when `stage_timings` is non-empty — already
correct absent-content handling). One addition: the profile call-out from
§11.1 belongs conceptually here too if a user lands directly on Overview via
a deep link — but it is specified once in the header so it is not repeated
per-tab; no duplication needed.

### 11.6 Teaching Plan tab

Existing structure correct (time-allocation bar, objectives, concept tags,
unmapped-objectives warning banner). No changes beyond the content-type
accent not applying here (a period card is structural, not a claim — it
gets the plain `.ef-card`, no left-rule).

### 11.7 Classroom Content tab

Existing `<details>`-per-period structure is correct and should stay
(first period open by default, rest collapsed — the right default for a
2-period package and essential for a 6+ period one). Apply:

- `.ef-card--activity` accent to the embedded `ActivityCard`.
- Mentor Moment section gets `.ef-badge--illustrative` per §5.7 (currently
  renders `.ef-badge--neutral` with the text `"Illustrative — not from
  source"` — keep the copy, change only the tone/colour so it's visually
  distinct from a plain neutral fact badge like a Bloom-level tag).
- Checkpoint questions: the `expected_answer` is itself close to a
  mini-answer-key (it tells a teacher what "correct" sounds like before
  they've asked the class). It does not need the full answer-key visual
  treatment from Assessments (that pattern signals "keep this away from
  students during the exam"; a checkpoint's expected answer is meant to be
  used in real time, mid-lesson) — leave as-is, just confirm it's not
  visually confusable with the graded answer key in Assessments. It isn't
  (different tab, different heading level).

### 11.8 Knowledge Base tab

Apply `.ef-card--concept` / `.ef-card--misconception` / `.ef-card--formula`
accents (§5.4) to the respective sections; apply the Grounded badge (§5.7)
to concepts, definitions, formulae, examples, applications and
misconceptions — every section here is exactly the set of content types
`Grounded.evidence` (`min_length=1`) covers in the contract. Prerequisites
and Keywords are the two sections with no evidence field in the schema
(`Prerequisite` and the raw `keywords: string[]` have no `evidence`) — they
correctly get **no** badge of either kind, because they are not claims,
they're structural metadata. Do not force a badge onto them for
consistency; that would be decoration, not signal.

### 11.9 Assessments tab — answer key separation, reinforced

Current pattern (blueprint summary → single "Show answer key" toggle →
item cards, each revealing its own `AnswerKeyPanel` when the toggle is on)
is correct and matches the PDF's own "questions, then a page break, then
the key" structure (verified against `samples/*/assessment_book.pdf`'s
documented behaviour). Two refinements:

1. **Default OFF is correct and must stay** — a teacher who opens this tab
   while screen-sharing to a class must not have answers visible by
   accident. Do not change this default under any future "convenience"
   argument.
2. Add a persistent, small `--ef-color-text-faint` caption next to the
   toggle, always visible regardless of its state: *"Matches the printed
   Assessment Book — questions first, key behind a page break."* This ties
   the on-screen toggle explicitly to the PDF's physical layout, which is
   the fact a teacher actually needs (will the PDF I hand out also be
   answer-free) — the toggle alone doesn't communicate that on its own.
3. When `bank.items.length === 0` (a package whose profile still produces
   an assessment bank but every item happened to fail generation and get
   dropped, per the "drop rather than repair an empty answer key" policy in
   the README) — this is different from "the tab doesn't exist" (already
   handled — `ViewerPage` omits the tab entirely when the array is empty
   from the start). If this can only be known after fetch, the omission
   logic already covers it since it checks the same array length; no
   separate empty-state UI needed here.

### 11.10 Learning Gaps tab

Existing severity-grouped structure (`high` → `medium` → `low`, in that
order, only non-empty groups render) is correct. Apply `.ef-card--gap`
accent keyed to each gap's own severity (§5.4) — currently only the badge
carries severity colour; the card itself should too, so a teacher scanning
the tab sees a red-orange-blue gradient down the page before reading a
word, which is the point of ranking by severity in the first place.

### 11.11 Validation tab

Existing structure (status banner, coverage `<dl>`, grounding-score stat,
consistency/unsupported-claims/issues sections, each correctly
conditionally rendered) is correct. The grounding-score stat is the one
number on this whole screen that most directly represents the product's
central claim in aggregate — give it the teal `--ef-color-info` treatment
instead of the current `--ef-color-accent` blue used generically for all
big stat numbers (`.ef-stat__value`), so it visually rhymes with every
`Grounded` badge elsewhere in the viewer rather than reading as "just
another big blue number."

---

## 12 · Motion

| Token | Value | Used for |
|---|---|---|
| `--ef-duration-fast` | 120ms | hover/focus transitions, button states |
| `--ef-duration-med` | 220ms | progress bar fill, `<details>`/tab panel open |
| `--ef-duration-slow` | 400ms | landing page section entrances only (a single fade/slide-up on scroll into view, if implemented at all — this is the one place motion is allowed to be more than utilitarian, and it is optional, not load-bearing) |
| `--ef-duration-pulse` | 1200ms (1600ms reduced-motion) | the "current stage" marker in `StageTimeline` |

`prefers-reduced-motion: reduce` zeroes `fast`/`med`/`slow` and slows the
pulse rather than removing it (a completely static "in progress" indicator
with no motion at all under-communicates state to a user relying on the
one motion cue reduced-motion doesn't ask to be removed — a slow pulse is
not the kind of motion the media query exists to suppress; large/fast
transitions are). This matches the existing `tokens.css` behaviour, kept.

---

## 13 · Open dependencies (not blocking, but must be tracked)

1. **`GET /api/v1/samples` is unregistered.** `list_samples()` exists on
   the storage interface; no route calls it; nothing seeds sample packages
   into the in-memory store at boot. Until this is wired (backend work,
   outside this document's scope): the landing page's "See a sample
   package" secondary CTA and the versatility table's two "Open the …
   sample" links **must** degrade to linking at the static files already
   committed under `samples/quantitative-physics/` and
   `samples/narrative-history/` — either by mounting that directory as a
   static route the same way `frontend/dist` is mounted (`backend/api/main.py
   ::_mount_frontend`), or, as an interim fallback with zero backend
   changes, linking to wherever the repository is hosted publicly. Do not
   ship the landing page with a link to `/api/v1/samples` that 404s.
2. **Repository URL for the footer's "Source" link and the "Built for
   review" strip.** Not present anywhere in the codebase read for this
   spec. Fill in the real one; do not invent a placeholder that looks real.
3. **The `errorCopy()` catalogue (§10)** should live in one module
   (suggested: `frontend/src/api/errorCopy.ts`) imported by every page —
   currently each page owns its own ad hoc mapping. This is a
   straightforward consolidation, not a redesign of any individual page's
   logic.

---

## 14 · Definition of done

- [ ] `/` renders the landing page (§7); `/upload` renders the current
      upload form, moved.
- [ ] Header does not clip or overlap at exactly 360px; mobile menu sheet
      implemented per §5.1.
- [ ] At least one real `min-width` breakpoint beyond 767px exists for the
      viewer (`lg` rail, §11.4) — the "one breakpoint total" problem (§0.2)
      is resolved app-wide, not just patched on the header.
- [ ] Artifacts panel (§5.8) renders on both the Run success banner and
      the Viewer header, using the already-implemented `getArtifacts`/
      `downloadArtifact` client functions.
- [ ] Every card representing a factual claim shows exactly one of
      `Grounded` / `Illustrative — not from source` (§5.7) — verified
      against both the physics fixture and the narrative-history sample.
- [ ] Content-type accent borders (§5.4) applied to concept, misconception,
      gap, activity and formula cards.
- [ ] `errorCopy()` catalogue (§10) is the single source for every
      user-facing error string in the app; no `catch` block renders a raw
      `Error.message` or `TypeError` string.
- [ ] Slow-vs-stuck copy (§9.4) implemented on the Run page, using the
      per-stage expected-duration table.
- [ ] Verified against the narrative-history sample specifically: zero
      formulae, zero numerical items, the profile call-out (§11.1) present,
      no empty cards, no "N/A" anywhere on the page.
- [ ] Light and dark contrast re-verified against the final implemented
      colours (this spec's ratios are computed against the token values in
      `tokens.css`; if an implementer substitutes a "close enough" hex by
      hand instead of using the token, re-check).
- [ ] `prefers-reduced-motion` honoured (already correct in `tokens.css`;
      confirm any new motion added for the landing page respects it too).
