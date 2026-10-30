import re

_BREAKS = re.compile(r"[\x00-\x1f\x7f  \s]+")


def clean_line(value: str) -> str:
    """One line of plain text: control characters and line breaks become single spaces.

    Used for anything that ends up in an email header (subjects, names) so a crafted value can
    neither inject headers nor make delivery fail.
    """
    return _BREAKS.sub(" ", value).strip()
