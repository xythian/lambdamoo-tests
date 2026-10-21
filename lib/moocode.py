"""Helpers for building MOO code from Python."""


def moo_string(text: str) -> str:
    """Quote text as a MOO string literal."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def moo_list(lines) -> str:
    """Quote a sequence of strings as a MOO list of string literals."""
    return "{" + ", ".join(moo_string(line) for line in lines) + "}"
