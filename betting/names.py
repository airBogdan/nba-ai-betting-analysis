"""Shared player name matching utilities."""

import re
import unicodedata


_SUFFIXES = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", re.IGNORECASE)


def normalize_name(name: str) -> str:
    """Normalize a player name for comparison.

    Handles Unicode diacritics (e.g. Dončić -> doncic), suffixes, periods.
    """
    # Strip diacritics: NFKD decomposition + drop combining marks
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.strip().lower()
    name = _SUFFIXES.sub("", name)
    name = name.replace(".", "")
    return name


def _teams_match(name1: str, name2: str) -> bool:
    """Check if two team names match (case-insensitive, word-based matching)."""
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    # Word-subset matching: "Lakers" matches "Los Angeles Lakers"
    # but "Nets" does NOT match "Hornets"
    w1 = set(n1.split())
    w2 = set(n2.split())
    if w1 <= w2 or w2 <= w1:
        return True
    # Handle LA/Los Angeles variations
    n1_norm = n1.replace("los angeles", "la").replace("l.a.", "la")
    n2_norm = n2.replace("los angeles", "la").replace("l.a.", "la")
    if n1_norm == n2_norm:
        return True
    w1n = set(n1_norm.split())
    w2n = set(n2_norm.split())
    return w1n <= w2n or w2n <= w1n


def names_match(name_a: str, name_b: str) -> bool:
    """Check if two player names refer to the same person.

    Handles: exact match, suffix stripping, Unicode normalization,
    initial matching (e.g. "C. Coward" -> "Cedric Coward").
    """
    a = normalize_name(name_a)
    b = normalize_name(name_b)
    if a == b:
        return True

    # Initial matching: "k knueppel" matches "kyle knueppel"
    parts_a = a.split()
    parts_b = b.split()
    if len(parts_a) >= 2 and len(parts_b) >= 2 and parts_a[-1] == parts_b[-1]:
        # Last names match — check if first name is an initial
        if len(parts_a[0]) == 1 and parts_b[0].startswith(parts_a[0]):
            return True
        if len(parts_b[0]) == 1 and parts_a[0].startswith(parts_b[0]):
            return True
    return False
