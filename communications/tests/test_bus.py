def test_publish_and_peek(cc):
    result = cc.op_publish("memory.events", "fact_added", {"fact_id": 1}, "memory")
    assert result["id"] == 1

    events = cc.op_peek("memory.events")
    assert len(events) == 1
    assert events[0]["event_type"] == "fact_added"
    assert events[0]["payload"] == {"fact_id": 1}


def test_publish_requires_topic_and_publisher(cc):
    try:
        cc.op_publish("", "x", {}, "someone")
        assert False
    except cc.CommError:
        pass
    try:
        cc.op_publish("topic", "x", {}, "")
        assert False
    except cc.CommError:
        pass


def test_peek_does_not_advance_any_cursor(cc):
    cc.op_publish("t", "e", {}, "p")
    cc.op_peek("t")
    cc.op_peek("t")
    # a fresh consumer should still see the event — peek never touched cursors
    result = cc.op_consume("fresh_consumer", ["t"])
    assert result["count"] == 1


def test_consume_advances_cursor_so_second_call_returns_nothing_new(cc):
    cc.op_publish("t", "e", {}, "p")
    first = cc.op_consume("alice", ["t"])
    assert first["count"] == 1

    second = cc.op_consume("alice", ["t"])
    assert second["count"] == 0


def test_multiple_consumers_each_see_full_history_independently(cc):
    """Broadcast semantics — this is the whole point of the bus."""
    cc.op_publish("t", "e1", {}, "p")
    cc.op_publish("t", "e2", {}, "p")

    alice = cc.op_consume("alice", ["t"])
    assert alice["count"] == 2

    # bob hasn't consumed yet — still sees both, alice's read didn't remove anything
    bob = cc.op_consume("bob", ["t"])
    assert bob["count"] == 2

    # a NEW event only shows up for consumers who haven't already passed it
    cc.op_publish("t", "e3", {}, "p")
    alice_again = cc.op_consume("alice", ["t"])
    assert alice_again["count"] == 1
    assert alice_again["events"][0]["event_type"] == "e3"


def test_consume_across_multiple_topics_in_one_call(cc):
    cc.op_publish("topic_a", "e", {}, "p")
    cc.op_publish("topic_b", "e", {}, "p")
    cc.op_publish("topic_c", "e", {}, "p")  # not requested, shouldn't appear

    result = cc.op_consume("carl", ["topic_a", "topic_b"])
    assert result["count"] == 2
    topics_seen = {e["topic"] for e in result["events"]}
    assert topics_seen == {"topic_a", "topic_b"}


def test_consume_events_ordered_by_id_across_topics(cc):
    cc.op_publish("a", "1", {}, "p")
    cc.op_publish("b", "2", {}, "p")
    cc.op_publish("a", "3", {}, "p")

    result = cc.op_consume("dan", ["a", "b"])
    ids = [e["id"] for e in result["events"]]
    assert ids == sorted(ids)


def test_consume_requires_at_least_one_topic(cc):
    try:
        cc.op_consume("x", [])
        assert False
    except cc.CommError:
        pass


def test_reset_consumer_allows_replay(cc):
    cc.op_publish("t", "e", {}, "p")
    cc.op_consume("erin", ["t"])
    assert cc.op_consume("erin", ["t"])["count"] == 0

    cc.op_reset_consumer("erin", "t", to_id=0)
    replayed = cc.op_consume("erin", ["t"])
    assert replayed["count"] == 1


def test_list_topics_reflects_activity(cc):
    cc.op_publish("t1", "e", {}, "p")
    cc.op_publish("t1", "e", {}, "p")
    cc.op_publish("t2", "e", {}, "p")

    topics = cc.op_list_topics()
    by_name = {t["topic"]: t for t in topics}
    assert by_name["t1"]["event_count"] == 2
    assert by_name["t2"]["event_count"] == 1


def test_list_consumers_shows_cursors(cc):
    cc.op_publish("t", "e", {}, "p")
    cc.op_consume("frank", ["t"])

    consumers = cc.op_list_consumers()
    assert len(consumers) == 1
    assert consumers[0]["consumer"] == "frank"
    assert consumers[0]["last_event_id"] == 1


def test_has_more_flag_when_page_is_full(cc):
    for i in range(5):
        cc.op_publish("t", f"e{i}", {}, "p")

    result = cc.op_consume("gina", ["t"], limit=3)
    assert result["count"] == 3
    assert result["has_more"] is True

    remainder = cc.op_consume("gina", ["t"], limit=3)
    assert remainder["count"] == 2
    assert remainder["has_more"] is False

def test_peek_rejects_non_positive_limit(cc):
    cc.op_publish("t", "e", {}, "p")
    for bad in (0, -1, -50):
        try:
            cc.op_peek("t", limit=bad)
            assert False, f"limit={bad} should have been rejected"
        except cc.CommError:
            pass


def test_consume_rejects_non_positive_limit(cc):
    cc.op_publish("t", "e", {}, "p")
    for bad in (0, -1, -50):
        try:
            cc.op_consume("someone", ["t"], limit=bad)
            assert False, f"limit={bad} should have been rejected"
        except cc.CommError:
            pass
