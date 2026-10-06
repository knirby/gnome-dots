"""Just enough GVariant text format to write and read settings values."""

import ast


def quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def dump(value) -> str:
    """Python value -> GVariant text, for the types settings use here."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "@as []"
        return "[" + ", ".join(dump(v) for v in value) + "]"
    if isinstance(value, dict):
        # a{sv}-like list entries such as ArcMenu's [{'id': <...>}] are written as a{ss}
        return "{" + ", ".join(f"{quote(k)}: {dump(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"cannot write {type(value).__name__} as GVariant")


def load_strv(text: str | None) -> list[str]:
    """Parse a GVariant string array such as "['a', 'b']" or "@as []"."""
    if not text:
        return []
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def load_str(text: str | None) -> str | None:
    if not text:
        return None
    try:
        value = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None
