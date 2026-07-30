"""Equation detection and LaTeX normalisation.

Why this exists: a physics or maths chapter that loses its equations during
parsing cannot produce a usable lesson plan, and "the characters are all still
there somewhere in a paragraph" is not structure preservation (FR-02, docs/00
H-14).

Two honest limits, stated rather than hidden:

* Detection is heuristic. PDFs encode equations as positioned glyphs with no
  markup, so there is no ground truth to read.
* Normalisation is best-effort. ``Block.text`` always retains the raw extraction,
  so a failed conversion degrades to plain text rather than losing content.

The bias is toward under-detection. Mislabelling prose as an equation corrupts a
paragraph; missing an equation leaves it as readable text.
"""

from __future__ import annotations

import re

__all__ = ["is_probable_equation", "to_latex"]

#: Characters that essentially only appear in mathematical content.
_MATH_SYMBOLS = set("=≠≈≤≥±×÷∑∏∫√∞∂∇→←↔⇒⇔αβγδθλμπσωΔΩ^_")

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

_GREEK_TO_LATEX = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "θ": r"\theta", "λ": r"\lambda", "μ": r"\mu", "π": r"\pi",
    "σ": r"\sigma", "ω": r"\omega", "Δ": r"\Delta", "Ω": r"\Omega",
}

_OPERATOR_TO_LATEX = {
    "×": r"\times", "÷": r"\div", "±": r"\pm", "≠": r"\neq",
    "≈": r"\approx", "≤": r"\leq", "≥": r"\geq", "√": r"\sqrt",
    "∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∞": r"\infty",
    "∂": r"\partial", "∇": r"\nabla", "→": r"\to", "⇒": r"\Rightarrow",
}

_WORDY = re.compile(r"\b(the|is|are|and|of|to|in|that|this|which|when)\b", re.IGNORECASE)


def is_probable_equation(text: str) -> bool:
    """True when a line reads as mathematics rather than prose."""
    stripped = text.strip()
    if not stripped or len(stripped) > 220:
        return False

    # Existing LaTeX is unambiguous.
    if stripped.startswith("$") or "\\frac" in stripped or "\\vec" in stripped:
        return True

    symbols = sum(1 for ch in stripped if ch in _MATH_SYMBOLS)
    if symbols == 0:
        return False

    letters = sum(1 for ch in stripped if ch.isalpha())
    words = stripped.split()

    # Prose containing an equals sign is still prose. Function words are the
    # cheapest reliable discriminator.
    prose_words = len(_WORDY.findall(stripped))
    if prose_words >= 2:
        return False

    # Dense in symbols relative to letters, or short and equation-shaped.
    density = symbols / max(letters, 1)
    return density > 0.12 or (len(words) <= 8 and "=" in stripped)


def to_latex(text: str) -> str | None:
    """Best-effort LaTeX for an equation line, or None when not convertible.

    Deliberately shallow: symbol substitution and simple sub/superscripts. It does
    not attempt to reconstruct fractions or matrices from flattened PDF text,
    because a wrong reconstruction is worse than none — the raw text is kept
    either way.
    """
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith("$") and stripped.endswith("$"):
        return stripped.strip("$").strip()
    if "\\" in stripped:
        return stripped  # already LaTeX-ish; pass through untouched

    if not is_probable_equation(stripped):
        return None

    out = stripped
    for symbol, latex in {**_GREEK_TO_LATEX, **_OPERATOR_TO_LATEX}.items():
        out = out.replace(symbol, f" {latex} ")

    out = re.sub(
        r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
        lambda m: "^{" + m.group(1).translate(_SUPERSCRIPT) + "}",
        out,
    )
    out = re.sub(
        r"([₀₁₂₃₄₅₆₇₈₉]+)",
        lambda m: "_{" + m.group(1).translate(_SUBSCRIPT) + "}",
        out,
    )

    out = re.sub(r"\s{2,}", " ", out).strip()
    return out or None
