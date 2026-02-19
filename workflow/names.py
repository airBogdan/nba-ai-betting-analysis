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
