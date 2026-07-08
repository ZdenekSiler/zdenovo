"""Unit tests for the shared data.categories module (tag-overlap categorization heuristic)."""


def test_load_categories_returns_four_fixed_categories():
    from data.categories import load_categories
    categories = load_categories()
    assert len(categories) == 4
    ids = {c["id"] for c in categories}
    assert ids == {"ai-agents-llm", "python-backend", "solo-consulting-startup", "deploy-devops-war-stories"}


def test_categorize_matches_by_tag_overlap():
    from data.categories import categorize
    assert categorize(["python", "fastapi"]) == "python-backend"
    assert categorize(["ai", "agents"]) == "ai-agents-llm"


def test_categorize_returns_none_when_no_overlap():
    from data.categories import categorize
    assert categorize(["woodworking", "gardening"]) is None


def test_categorize_returns_first_match_on_multi_category_overlap():
    from data.categories import categorize
    # "web" appears only in deploy-devops-war-stories' tag list
    assert categorize(["web"]) == "deploy-devops-war-stories"


def test_categorize_accepts_preloaded_categories_list():
    from data.categories import categorize, load_categories
    categories = load_categories()
    assert categorize(["python"], categories) == "python-backend"
