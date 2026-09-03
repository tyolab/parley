from parley.core.identity import compose_agent_id, next_handle, slugify_name


def test_compose_honors_exact_box():
    assert compose_agent_id("work3", "work3") == "work3"

def test_compose_honors_box_prefixed_handle():
    assert compose_agent_id("work3", "work3-agent#2") == "work3-agent#2"

def test_compose_rejects_prefix_collision():
    # 'work300-evil' must NOT be honored for box 'work3' (needs the '-' separator)
    assert compose_agent_id("work3", "work300-evil") == "work3"

def test_compose_rejects_foreign_handle():
    assert compose_agent_id("work3", "elitebook2-agent#1") == "work3"

def test_compose_none_box_is_none():
    assert compose_agent_id(None, "anything") is None

def test_compose_no_handle_falls_back_to_box():
    assert compose_agent_id("work3", None) == "work3"

def test_slugify_sanitizes_and_caps():
    assert slugify_name("Reach Deploy!") == "Reach-Deploy"
    assert slugify_name("") == ""
    assert slugify_name(None) == ""
    assert slugify_name("!!!") == ""
    assert len(slugify_name("x" * 100)) == 32

def test_next_handle_numbers_monotonically_per_name():
    counters = {}
    def bump(box, slug):
        counters[(box, slug)] = counters.get((box, slug), 0) + 1
        return counters[(box, slug)]
    assert next_handle("work3", None, bump) == "work3-agent#1"
    assert next_handle("work3", None, bump) == "work3-agent#2"
    assert next_handle("work3", "reach", bump) == "work3-agent-reach#1"
    assert next_handle("work3", "reach", bump) == "work3-agent-reach#2"
