import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shell_detector as sd


def test_empty_history_finds_nothing():
    assert sd.find_repeated_chains([]) == []


def test_no_repeats_finds_nothing():
    commands = ["git status", "ls", "cd foo", "cat bar.txt"]
    assert sd.find_repeated_chains(commands, min_repeats=3) == []


def test_finds_a_simple_repeated_pair():
    commands = (
        ["git add .", "git commit -m wip"] * 3
        + ["ls"]
    )
    candidates = sd.find_repeated_chains(commands, chain_lengths=(2,), min_repeats=3)
    assert len(candidates) == 1
    assert candidates[0]["chain"] == ("git add .", "git commit -m wip")
    assert candidates[0]["repeats"] == 3
    assert candidates[0]["chain_length"] == 2


def test_below_min_repeats_not_flagged():
    commands = ["git add .", "git commit -m wip"] * 2  # only twice
    candidates = sd.find_repeated_chains(commands, chain_lengths=(2,), min_repeats=3)
    assert candidates == []


def test_longer_chain_suppresses_redundant_shorter_subchain():
    # [build, test, deploy] repeats 3x, so [build, test] and [test, deploy]
    # — both real, both technically >= min_repeats — should NOT also be
    # reported separately; they're fully contained in the longer chain.
    commands = ["make build", "make test", "make deploy"] * 3
    candidates = sd.find_repeated_chains(commands, chain_lengths=(2, 3), min_repeats=3)
    assert len(candidates) == 1
    assert candidates[0]["chain"] == ("make build", "make test", "make deploy")
    assert candidates[0]["chain_length"] == 3


def test_unrelated_chain_alongside_a_longer_one_is_kept():
    long_chain = ["make build", "make test", "make deploy"] * 3
    unrelated_pair = ["docker ps", "docker logs web"] * 3
    commands = long_chain + unrelated_pair
    candidates = sd.find_repeated_chains(commands, chain_lengths=(2, 3), min_repeats=3)
    chains = {c["chain"] for c in candidates}
    assert ("make build", "make test", "make deploy") in chains
    assert ("docker ps", "docker logs web") in chains
    assert len(candidates) == 2


def test_results_sorted_longest_and_most_repeated_first():
    # Exactly 3 reps of each, with fully distinct tokens between the two
    # segments — enough repeats to hit min_repeats on the intended chain,
    # not enough for any accidental rotation of it to also qualify (see
    # test_longer_chain_suppresses_redundant_shorter_subchain for what
    # happens when a chain's own rotations DO qualify — that's a separate,
    # deliberately covered case, not what this test is about).
    commands = (
        ["make build", "make test", "make deploy"] * 3   # triple, 3 repeats
        + ["docker ps", "docker logs web"] * 3            # pair, 3 repeats
    )
    candidates = sd.find_repeated_chains(commands, chain_lengths=(2, 3), min_repeats=3)
    assert candidates[0]["chain_length"] == 3  # longer chain sorts first
    assert candidates[0]["chain"] == ("make build", "make test", "make deploy")
    assert candidates[1]["chain"] == ("docker ps", "docker logs web")


def test_chain_key_is_stable_and_distinguishes_chains():
    a = sd.chain_key(("git add .", "git commit -m wip"))
    b = sd.chain_key(("git add .", "git commit -m wip"))
    c = sd.chain_key(("git status",))
    assert a == b
    assert a != c
    assert isinstance(a, str) and len(a) == 16


def test_format_chain_message_includes_repeats_and_commands():
    candidate = {"chain": ("git add .", "git commit -m wip"), "chain_length": 2, "repeats": 4}
    message = sd.format_chain_message(candidate)
    assert "4 times" in message
    assert "git add ." in message
    assert "git commit -m wip" in message


def test_format_chain_message_truncates_very_long_previews():
    long_cmd = "x" * 200
    candidate = {"chain": (long_cmd, "ls"), "chain_length": 2, "repeats": 3}
    message = sd.format_chain_message(candidate)
    assert len(message) < 200
    assert message.endswith("?")
