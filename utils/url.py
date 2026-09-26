from urllib.parse import urlsplit, urlunsplit


def canonicalize_detail_url(url: str) -> str:
    """
    Normalize Mahkamah Agung detail URLs so query strings/fragments
    do not create duplicate Putusan identities.

    Example:
        https://example.com/foo.html?celery_test=1
        -> https://example.com/foo.html
    """
    url = url.strip()

    parts = urlsplit(url)

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            "",
            "",
        )
    )