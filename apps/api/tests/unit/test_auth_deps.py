"""``Authorization: Bearer`` parsing."""

import pytest
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth.deps import bearer_token


def test_bearer_token_is_extracted() -> None:
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer   ", "Basic abc", "bearer abc"])
def test_bad_headers_are_401(header: str | None) -> None:
    with pytest.raises(UnauthorizedError):
        bearer_token(header)
