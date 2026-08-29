import pytest

from news.models import Category, StoryStatus
from news.services.claude import parse_json
from news.services.scoring import apply_scores


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


@pytest.fixture
def scored_batch(source, make_story):
    return [
        make_story(source, "Storm damage across Dallas"),
        make_story(source, "Governor signs new election law"),
        make_story(source, "Cowboys beat Eagles 24-17 in final seconds"),
        make_story(source, "Malformed one"),
    ]


@pytest.mark.django_db
def test_apply_scores_writes_fields_and_hides_bad_categories(scored_batch) -> None:
    weather, politics, live, bad = scored_batch
    results = [
        {
            "id": weather.id,
            "importance": 8,
            "shareability": 7,
            "category": "weather",
            "is_political": False,
            "is_cowboys": False,
            "reason": "Big storm.",
        },
        {
            "id": politics.id,
            "importance": 9,
            "shareability": 4,
            "category": "politics",
            "is_political": True,
            "is_cowboys": False,
            "reason": "Election law.",
        },
        {
            "id": live.id,
            "importance": 5,
            "shareability": 9,
            "category": "sports_live",
            "is_political": False,
            "is_cowboys": True,
            "reason": "Game result.",
        },
        {"id": bad.id, "importance": "lots", "shareability": 3},
        {"id": 999999, "importance": 5, "shareability": 5},
        "not an object",
    ]

    updated = apply_scores(scored_batch, results)

    for s in scored_batch:
        s.refresh_from_db()
    assert updated == 3
    assert weather.status == StoryStatus.SCORED
    assert (weather.importance, weather.shareability, weather.category) == (8, 7, Category.WEATHER)
    assert weather.score_reason == "Big storm."
    assert weather.scored_at is not None
    assert politics.status == StoryStatus.HIDDEN and politics.is_political is True
    assert live.status == StoryStatus.HIDDEN and live.is_cowboys is True
    assert bad.status == StoryStatus.NEW and bad.importance is None


@pytest.mark.django_db
def test_apply_scores_clamps_and_defaults(source, make_story) -> None:
    story = make_story(source, "Something")
    apply_scores([story], [{"id": story.id, "importance": 42, "shareability": -3, "category": "nonsense"}])
    story.refresh_from_db()
    assert (story.importance, story.shareability) == (10, 1)
    assert story.category == Category.OTHER
    assert story.status == StoryStatus.SCORED
