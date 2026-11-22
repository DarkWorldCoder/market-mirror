"""Concept and statement answers: valid scores only, quotes checked against the statement."""

import pytest

from app.services import idea_tests


def test_prompts_show_one_item_and_ask_for_honest_numbers():
    p = {"name": "Asha", "age": 34, "country": "Nepal", "persona": "Teacher"}
    concept = idea_tests.concept_prompt(p, "Oat bar, 2 USD, recyclable wrapper", "Oatly")
    assert "Oat bar, 2 USD" in concept and "p_buy" in concept and "not the same as paying" in concept
    statement = idea_tests.statement_prompt(p, "Prices rise 10% on 1 May.", "Acme", "customers")
    assert "Prices rise 10%" in statement and "customers" in statement and "trust_after" in statement


@pytest.mark.parametrize("bad", [None, "0.5", True, -0.1, 1.2, float("nan")])
def test_invalid_scores_raise_instead_of_counting_as_zero(bad):
    with pytest.raises(RuntimeError):
        idea_tests.read_concept({"p_buy": bad})
    with pytest.raises(RuntimeError):
        idea_tests.read_statement({"trust_after": bad}, "text")


def test_statement_quote_must_be_in_the_statement_and_actions_are_fixed():
    s = "We are raising prices to keep quality high. Nothing else changes."
    ok = idea_tests.read_statement({"trust_after": 0.4, "riskiest_phrase": "“Nothing else changes”",
                                    "would_do": "Complain", "missing": ""}, s)
    assert ok["riskiest_phrase"] == "Nothing else changes" and ok["would_do"] == "complain"
    assert ok["objection"] == '"Nothing else changes"'
    made_up = idea_tests.read_statement({"trust_after": 0.4, "riskiest_phrase": "greedy", "would_do": "riot"}, s)
    assert made_up["riskiest_phrase"] == "" and made_up["would_do"] == ""
    concept = idea_tests.read_concept({"p_buy": 0, "unclear": "the size", "objection": ""})
    assert concept["score"] == 0.0 and concept["objection"] == "the size"
