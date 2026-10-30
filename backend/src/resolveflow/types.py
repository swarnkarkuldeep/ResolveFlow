from typing import Annotated

from pydantic import StringConstraints

# Deliberately simple: one "@", no whitespace, a dot in the domain. Deliverability is not checked
# (and reserved TLDs such as .test are accepted so demo and test data work).
EmailAddr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
