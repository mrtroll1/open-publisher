"""Shared helpers for command preparers."""


def parse_flags(text: str) -> tuple[bool, bool, str]:
    """Parse -v (verbose) and -e (expert) flags. Returns (verbose, expert, rest)."""
    verbose = False
    expert = False
    while text:
        if text.startswith(("-v ", "verbose ")):
            verbose = True
            parts = text.split(None, 1)
            text = parts[1] if len(parts) > 1 else ""
        elif text.startswith(("-e ", "expert ")):
            expert = True
            parts = text.split(None, 1)
            text = parts[1] if len(parts) > 1 else ""
        else:
            break
    return verbose, expert, text
