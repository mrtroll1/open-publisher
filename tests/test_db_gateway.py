import pytest

from backend.infrastructure.gateways.db_gateway import _normalize_subject


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hello World", "hello world"),
        ("Re: Something", "something"),
        ("Fwd: Something", "something"),
        ("Fw: Something", "something"),
        ("Re: Fwd: Re: Topic", "topic"),
        ("RE: LOUD SUBJECT", "loud subject"),
        ("re: quiet subject", "quiet subject"),
        ("FWD: Forwarded", "forwarded"),
        ("fwd: forwarded", "forwarded"),
        ("Fw: FW: fw: nested", "nested"),
        ("  spaces around  ", "spaces around"),
        ("Re:  extra spaces", "extra spaces"),
        ("", ""),
        ("No prefix here", "no prefix here"),
        ("Regarding something", "regarding something"),
        ("Re: Re: Re: deep", "deep"),
    ],
    ids=[
        "basic_lowercase",
        "re_prefix",
        "fwd_prefix",
        "fw_prefix",
        "nested_prefixes",
        "uppercase_RE",
        "lowercase_re",
        "uppercase_FWD",
        "lowercase_fwd",
        "mixed_fw_variants",
        "leading_trailing_whitespace",
        "re_extra_spaces",
        "empty_string",
        "no_prefix",
        "regarding_not_stripped",
        "triple_re",
    ],
)
def test_normalize_subject(raw: str, expected: str) -> None:
    assert _normalize_subject(raw) == expected
