import secrets


def new_token() -> str:
    """A URL-safe secret bearer token for a per-agent identity."""
    return secrets.token_urlsafe(24)
