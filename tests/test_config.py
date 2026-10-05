from sql_copilot.config import Settings


def test_api_key_set_parses_comma_separated_keys():
    s = Settings(api_keys="a, b ,,c")
    assert s.api_key_set == {"a", "b", "c"}


def test_defaults_are_safe():
    s = Settings()
    assert s.max_rows == 100
    assert s.rate_limit == "10/minute"
