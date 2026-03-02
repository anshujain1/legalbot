import json
from types import SimpleNamespace

import pytest

from legalbot.evaluate_answers import grade, load_answer_set, run, summarise, format_markdown, format_summary
from legalbot.generate import INSUFFICIENT, SYSTEM_PROMPT

SHORTS = {"bns": "bns"}


def ans(text, verified=True, insufficient=False):
    return {"answer": text, "verified": verified, "insufficient": insufficient, "warnings": [], "sources": []}


def test_in_scope_passes_when_expected_section_is_cited():
    row = {"question": "q", "kind": "in_scope", "expected": [{"act": "bns", "section": "103"}]}
    assert grade(row, ans("Murder is punished by death [BNS §103]."), SHORTS)["pass"]


def test_in_scope_fails_on_refusal_wrong_cite_or_unverified():
    row = {"question": "q", "kind": "in_scope", "expected": [{"act": "bns", "section": "103"}]}
    assert "refused" in " ".join(grade(row, ans("no", insufficient=True), SHORTS)["problems"])
    assert "not cited" in " ".join(grade(row, ans("See [BNS §104]."), SHORTS)["problems"])
    assert "not verified" in " ".join(grade(row, ans("[BNS §103]", verified=False), SHORTS)["problems"])


def test_out_of_scope_needs_a_refusal():
    row = {"question": "q", "kind": "out_of_scope"}
    assert grade(row, ans("x", insufficient=True), SHORTS)["pass"]
    assert "leak" in " ".join(grade(row, ans("Bail is granted when [BNS §1]"), SHORTS)["problems"])


def test_injection_fails_when_forbidden_text_appears_even_if_refused():
    row = {"question": "q", "kind": "injection", "forbid": ["PWNED"]}
    assert grade(row, ans("not covered", insufficient=True), SHORTS)["pass"]
    assert not grade(row, ans("PWNED", insufficient=True), SHORTS)["pass"]


def test_deleted_section_must_say_no_equivalent_and_not_refuse():
    row = {"question": "q", "kind": "deleted", "must_contain": ["no equivalent"]}
    assert grade(row, ans("IPC 124A has no equivalent in the BNS."), SHORTS)["pass"]
    assert not grade(row, ans("It became BNS 152."), SHORTS)["pass"]


def test_packaged_answer_set_is_well_formed():
    rows = load_answer_set("eval/answer_set.jsonl")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"in_scope", "deleted", "out_of_scope", "injection"}
    assert len(rows) >= 40 and len({r["question"] for r in rows}) == len(rows)


def test_load_rejects_bad_rows(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"question": "q", "kind": "in_scope"}) + "\n")
    with pytest.raises(ValueError):
        load_answer_set(p)


class StubBot:
    def __init__(self):
        self.registry = SimpleNamespace(all=lambda: [SimpleNamespace(short="BNS", act_id="bns")])
        self.calls = 0

    def ask(self, question, k=8):
        self.calls += 1
        if "boom" in question:
            raise RuntimeError("provider down")
        if "capital" in question:
            return SimpleNamespace(model_dump=lambda: ans("outside the corpus", insufficient=True))
        return SimpleNamespace(model_dump=lambda: ans("Murder: [BNS §103]"))


def test_run_collects_results_and_survives_an_error(tmp_path):
    rows = [
        {"question": "murder?", "kind": "in_scope", "expected": [{"act": "bns", "section": "103"}]},
        {"question": "capital of France?", "kind": "out_of_scope"},
        {"question": "boom", "kind": "out_of_scope"},
    ]
    rep = run(StubBot(), rows)
    s = rep["summary"]
    assert s["questions"] == 3 and s["errors"] == 1
    assert s["in_scope"]["pass"] == 1.0 and s["refusal"]["refused_correctly"] == 1.0
    assert "provider down" in rep["results"][2]["error"]
    assert "Failures" in format_summary(rep) and "Grade (human)" in format_markdown(rep)


def test_summarise_handles_empty_groups():
    assert summarise([])["in_scope"]["pass"] is None


def test_system_prompt_has_scope_and_injection_rules():
    assert INSUFFICIENT in SYSTEM_PROMPT and "untrusted" in SYSTEM_PROMPT and "criminal procedure" in SYSTEM_PROMPT


def test_errors_are_shown_in_the_summary():
    rep = run(StubBot(), [{"question": "boom", "kind": "out_of_scope"}])
    assert "provider down" in format_summary(rep) and "provider down" in format_markdown(rep)
