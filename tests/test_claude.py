import pytest

from news.services.claude import parse_json


@pytest.mark.parametrize(
    "raw",
    [
        '[{"id": 1}]',
        '```json\n[{"id": 1}]\n```',
        '```\n[{"id": 1}]\n```',
        'Here are the scores:\n[{"id": 1}]\nLet me know if you need more.',
        '  \n[{"id": 1}]  ',
    ],
)
def test_parse_json_handles_fences_and_prose(raw: str) -> None:
    assert parse_json(raw) == [{"id": 1}]


def test_parse_json_object() -> None:
    assert parse_json('Sure!\n```json\n{"post_title": "Hi"}\n```') == {"post_title": "Hi"}


def test_parse_json_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        parse_json("I cannot help with that.")
