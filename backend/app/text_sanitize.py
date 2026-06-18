def sanitize_pg_text(value: str | None) -> str | None:
    """PostgreSQL TEXT/VARCHAR fields reject NUL (0x00) bytes."""
    if value is None:
        return None
    if "\x00" not in value:
        return value
    return value.replace("\x00", "")
