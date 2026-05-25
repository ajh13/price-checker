"""
classifier.py — eBay listing condition classifier.

Classifies a listing title into one of five condition tiers using a top-down
priority ruleset.  Rules are applied in order; the first match wins.
"""

import re

CONDITION_ORDER = ["Sealed + Graded", "Sealed", "CIB", "Box + Disc", "Loose"]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GRADING_COMPANY_RE = re.compile(r'\b(vga|wata|psa|cgc|beckett)\b')

def _normalise(title: str) -> str:
    """Lowercase, replace hyphens with spaces, strip parentheses."""
    t = title.lower()
    t = t.replace('-', ' ')
    t = t.replace('(', '').replace(')', '')
    return t


def _any_kw(title_lower: str, keywords) -> bool:
    return any(kw in title_lower for kw in keywords)


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

_SEALED_KEYWORDS = [
    'factory sealed',
    'shrinkwrap',
    'shrink wrap',
    'shrink',
    'never opened',
    'unopened',
    'sealed',
    'nib',
]

_SEALED_ANTI = [
    'loose',
    'cartridge only',
    'cart only',
    'disc only',
    'disk only',
    'no box',
]

_CIB_KEYWORDS = [
    'complete in box',
    'complete in case',
    'with manual',
    'with booklet',
    'box and manual',
    'box manual',
    'includes manual',
    'includes box',
    'cib',
    'complete',  # most common shorthand
]

_CIB_ANTI = [
    'no manual',
    'no booklet',
    'missing manual',
    'missing insert',
    'no insert',
]

_BOX_DISC_BOX_KEYWORDS = [
    'with box',
    'game and box',
    'disc and box',
    'cart and box',
]

_BOX_DISC_NO_MANUAL_KEYWORDS = [
    'no manual',
    'without manual',
    'missing manual',
    'box only no manual',
    'no booklet',
]

_LOOSE_EXPLICIT = [
    'loose',
    'cartridge only',
    'cart only',
    'disc only',
    'disk only',
    'game only',
    'no box',
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_condition(title: str) -> str:
    """Return the condition tier for an eBay listing *title*.

    Tiers (evaluated top-down, first match wins):
      1. "Sealed + Graded"
      2. "Sealed"
      3. "CIB"
      4. "Box + Disc"
      5. "Loose"   (default fallback)
    """
    t = _normalise(title)

    # ------------------------------------------------------------------
    # 1. Sealed + Graded
    #    A grading company name must be present (VGA, WATA, PSA, CGC,
    #    Beckett).  Bare numeric grades like "9.8" are not sufficient.
    # ------------------------------------------------------------------
    if _GRADING_COMPANY_RE.search(t):
        return "Sealed + Graded"

    # ------------------------------------------------------------------
    # 2. Sealed
    #    Must contain a sealed keyword AND must NOT contain any anti-
    #    keywords that indicate only a bare cartridge/disc is present.
    #    NOTE: "new" alone is intentionally excluded (too ambiguous).
    # ------------------------------------------------------------------
    if _any_kw(t, _SEALED_KEYWORDS) and not _any_kw(t, _SEALED_ANTI):
        return "Sealed"

    # ------------------------------------------------------------------
    # 3. CIB
    #    Must contain a CIB keyword AND must NOT contain anti-keywords
    #    that indicate a manual or insert is missing.
    #    Special case: "box only" means an empty box → falls through to
    #    Loose, so we exclude it here via the anti list path.
    # ------------------------------------------------------------------
    if _any_kw(t, _CIB_KEYWORDS) and not _any_kw(t, _CIB_ANTI):
        # "box only" → empty box, not a complete copy; treat as Loose
        if 'box only' in t:
            pass  # fall through
        else:
            return "CIB"

    # ------------------------------------------------------------------
    # 4. Box + Disc
    #    Has a box keyword AND an explicit "no manual" / missing-manual
    #    indicator.  Also fires on standalone "no manual".
    # ------------------------------------------------------------------
    has_box_kw = _any_kw(t, _BOX_DISC_BOX_KEYWORDS)
    has_no_manual = _any_kw(t, _BOX_DISC_NO_MANUAL_KEYWORDS)

    if has_box_kw and has_no_manual:
        return "Box + Disc"

    # Standalone "no manual" (with box implicitly present via "with box"
    # already handled above; catch remaining cases such as bare "no manual")
    if has_no_manual and not _any_kw(t, _LOOSE_EXPLICIT):
        return "Box + Disc"

    # ------------------------------------------------------------------
    # 5. Loose  (default / explicit)
    # ------------------------------------------------------------------
    return "Loose"
