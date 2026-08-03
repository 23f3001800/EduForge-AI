"""Instance a static Bold cut from each committed variable font.

Run once when the variable fonts change; the output is committed beside them:

    python scripts/build_bold_fonts.py

Why this exists rather than a ``variations={"wght": 700}`` argument at render
time: fpdf2 accepts that, and it costs ~2.5 s per family per document because
fontTools re-flattens every glyph outline on each call. Three artifacts per job
would pay it six times over. Instancing once at build time moves that cost off
the request path entirely, and the result is an ordinary static TTF that fpdf2
loads as fast as the regular cut.

Why bold is worth having at all: without it every heading in the rendered PDFs
differed from body copy by size alone, which reads as one undifferentiated
column of text — the reason a teacher opening the guide saw "text in a file"
rather than a document. Weight is what makes a heading scan as a heading.

Both fonts are OFL, which permits modification and redistribution provided the
licence travels with them; the OFL-*.txt files already sit in the same
directory and cover these derivatives. Neither Noto family declares a Reserved
Font Name, so the instances keep their family names and simply gain a Bold
style — which is what lets fpdf2 pair them as one family.
"""

from __future__ import annotations

from pathlib import Path

from fontTools import ttLib
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "backend/stages/s10_publishing/render/fonts"

#: Regular (variable) source -> static Bold output. wght 700 is the conventional
#: bold; wdth is pinned to 100 so the instance keeps the normal width rather
#: than inheriting whatever the default named instance carried.
BUILDS = {
    "NotoSans[wdth,wght].ttf": "NotoSans-Bold.ttf",
    "NotoSansDevanagari[wdth,wght].ttf": "NotoSansDevanagari-Bold.ttf",
}

AXES = {"wght": 700, "wdth": 100}


def main() -> int:
    for source_name, target_name in BUILDS.items():
        source = FONT_DIR / source_name
        if not source.is_file():
            print(f"missing source font: {source}")
            return 1

        font = ttLib.TTFont(source)
        static = instancer.instantiateVariableFont(font, AXES, inplace=False, updateFontNames=False)
        target = FONT_DIR / target_name
        static.save(target)
        print(f"  {target_name}  ({target.stat().st_size / 1024:.0f} KB)")

    print("bold cuts written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
