"""Output languages the form may offer, bounded by what stage 10 can typeset.

The list is short on purpose, and the constraint that decides its length is not
the model's — it is the renderer's. Stage 10 embeds two font families: NotoSans
(Latin, Cyrillic, Greek) and NotoSansDevanagari. A language whose script neither
covers still passes through the model perfectly well and then renders as tofu
boxes in the lesson plan PDF, which is a worse outcome than not offering it: the
teacher gets a file that looks like a corrupted download and no explanation.

So a language earns a place here by having a script the shipped fonts draw. That
excludes Tamil, Bengali, Telugu, Kannada, Malayalam, Gujarati, Odia, Punjabi,
Urdu and Arabic — a real limitation, listed in the docstring rather than left for
someone to discover from a broken PDF. Adding any of them is one Noto font file
in ``stages/s10_publishing/render/fonts/`` plus an entry below; it is deliberately
not a code change, because the blocker is a licence-cleared font, not logic.

``en`` stays first because it is the default and the common answer, not because
the list is ranked by anything.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["OUTPUT_LANGUAGES", "OutputLanguage", "is_supported"]


@dataclass(frozen=True, slots=True)
class OutputLanguage:
    """One offerable language, and the script the renderer must cover for it."""

    code: str
    """BCP-47 tag, sent as ``output_language`` on the job."""

    label: str
    """What the teacher reads in the dropdown — endonym plus English name."""

    script: str
    """The Unicode script the shipped fonts have to draw."""


#: Offered in the UI. Every entry's script is covered by an embedded font.
OUTPUT_LANGUAGES: tuple[OutputLanguage, ...] = (
    OutputLanguage("en", "English", "Latin"),
    OutputLanguage("hi", "हिन्दी — Hindi", "Devanagari"),
    OutputLanguage("mr", "मराठी — Marathi", "Devanagari"),
    OutputLanguage("ne", "नेपाली — Nepali", "Devanagari"),
    OutputLanguage("sa", "संस्कृतम् — Sanskrit", "Devanagari"),
    OutputLanguage("fr", "Français — French", "Latin"),
    OutputLanguage("es", "Español — Spanish", "Latin"),
    OutputLanguage("de", "Deutsch — German", "Latin"),
    OutputLanguage("pt", "Português — Portuguese", "Latin"),
    OutputLanguage("id", "Bahasa Indonesia — Indonesian", "Latin"),
)


def is_supported(code: str | None) -> bool:
    """Whether ``code`` is one the renderer is known to typeset.

    Not a validator. The job contract still accepts any BCP-47 tag, because
    refusing an unlisted language would turn a rendering limitation into a hard
    block on a package whose JSON and Markdown would have been fine. This only
    answers whether the form should offer it.
    """
    if not code:
        return False
    return code.strip().lower() in {language.code for language in OUTPUT_LANGUAGES}
