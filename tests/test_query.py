import pytest

from legalbot.concordance import Concordance
from legalbot.query import QueryAnalyzer
from legalbot.registry import ActRegistry
from legalbot.schema import Status


@pytest.fixture(scope="module")
def analyzer():
    return QueryAnalyzer(ActRegistry.load(), Concordance.load())


def test_old_code_reference_maps_to_new_code(analyzer):
    plan = analyzer.plan("What is IPC 420 under the new law?")
    assert ("ipc", "420") in plan.explicit_sections
    assert ("bns", "318") in plan.explicit_sections
    assert any("BNS §318" in n for n in plan.notes)
    assert set(plan.filters.act_ids) == {"ipc", "bns"}
    assert "BNS section 318" in plan.search_query


def test_section_then_act(analyzer):
    plan = analyzer.plan("Explain section 103 of the Bharatiya Nyaya Sanhita")
    assert plan.explicit_sections == [("bns", "103")]
    assert plan.filters.act_ids == ["bns"]
    assert any("replaced IPC §302" in n for n in plan.notes)


def test_act_then_section_with_subclause(analyzer):
    assert analyzer.plan("BNS section 318(4) punishment").explicit_sections == [("bns", "318")]


def test_number_then_act(analyzer):
    plan = analyzer.plan("302 IPC")
    assert ("ipc", "302") in plan.explicit_sections and ("bns", "103") in plan.explicit_sections


def test_bare_section_with_single_act_in_query(analyzer):
    assert analyzer.plan("BNS: what does section 85 say?").explicit_sections == [("bns", "85")]


def test_bare_section_without_act_is_not_pinned(analyzer):
    plan = analyzer.plan("What does section 103 say?")
    assert plan.explicit_sections == []
    assert plan.filters.statuses == [Status.IN_FORCE]


def test_year_after_act_is_not_a_section(analyzer):
    assert analyzer.plan("Bharatiya Nyaya Sanhita 2023 overview").explicit_sections == []


def test_natural_question_defaults_to_in_force_filter(analyzer):
    plan = analyzer.plan("What is the punishment for dowry death?")
    assert plan.filters.statuses == [Status.IN_FORCE]
    assert plan.explicit_sections == [] and plan.notes == []


def test_alphanumeric_section_numbers(analyzer):
    assert analyzer.plan("IPC 304B").explicit_sections[:2] == [("ipc", "304B"), ("bns", "80")]


def test_concordance_lookup_both_ways():
    c = Concordance.load()
    assert c.forward("ipc", "302")[0].new_section == "103"
    assert c.backward("bns", "318")[0].old_section == "420"
    assert c.forward("ipc", "99999") == []
    # the 19 hand-checked rows are verified; the rows read automatically from the table are not, until someone checks them
    checked = {"34", "120B", "299", "300", "302", "304", "304A", "304B", "307", "323", "354", "376", "379", "406", "420", "498A", "504", "506", "509"}
    assert all(c.forward("ipc", n)[0].verified for n in checked)
    assert any(not m.verified for m in c.rows) and len(c.rows) > 500
    assert c.forward("ipc", "506")[0].new_ref == "351(2), 351(3)"  # the table maps 506 to two sub-sections


def test_unverified_rows_are_flagged_in_the_query_notes(tmp_path, analyzer):
    from legalbot.concordance import Mapping

    c = Concordance([Mapping("ipc", "420", "bns", "318", "318(4)", "Cheating", False)])
    plan = QueryAnalyzer(analyzer.registry, c).plan("IPC 420")
    assert any("unverified mapping" in n for n in plan.notes)
