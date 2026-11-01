"""The dose guard on amounts per kilogram or per day, and on grams (ADR 0022).

The phrases are in dose_phrases.py and were written before the guard changed. Lab values and
nutrition amounts must stay out; a sentence about food that also talks about taking a medicine
must not."""

import pytest

from medagent.evals.redteam_scoring import strict_dose
from medagent.guardrails.dose import contains_dose
from tests.unit.dose_phrases import BENIGN, BENIGN_DE, MUST_DETECT_DE, MUST_DETECT_EN


@pytest.mark.parametrize("text", MUST_DETECT_EN + MUST_DETECT_DE)
def test_doses_per_kilogram_per_day_and_in_grams_are_detected(text: str) -> None:
    assert contains_dose(text), text


@pytest.mark.parametrize("text", BENIGN + BENIGN_DE)
def test_lab_values_and_nutrition_amounts_are_not_doses(text: str) -> None:
    assert not contains_dose(text), text


@pytest.mark.parametrize("text", MUST_DETECT_EN + MUST_DETECT_DE)
def test_the_production_guard_catches_everything_the_strict_eval_check_does(text: str) -> None:
    """The red-team scorer was stricter than the guard on purpose; that gap is now closed."""
    assert strict_dose(text)
    assert contains_dose(text)


# -- each rule has to matter (a guard whose removal changes nothing is decoration) -----------


def test_the_slash_denominator_must_end_the_word() -> None:
    assert contains_dose("Give 5 mg/day.")
    assert contains_dose("Give 5 mg/kg.")
    assert not contains_dose("Normal is 5 mg/dL.")
    assert not contains_dose("Normal is 5 mg/dl.")


def test_a_nutrition_sentence_is_exempt_but_taking_a_medicine_overrides_it() -> None:
    assert not contains_dose("Aim for 30 g of fiber a day.")
    assert contains_dose("Take 4 g of paracetamol with food.")
    assert contains_dose("Take 30 g of fiber supplement tablets.")


def test_a_gram_amount_without_any_nutrition_word_is_a_dose() -> None:
    assert contains_dose("The limit is 4 g.")
    assert contains_dose("Two grams is enough.")


def test_the_gram_check_looks_at_one_sentence_at_a_time() -> None:
    # A nutrition sentence next to a dose sentence must not hide the dose.
    assert contains_dose("Fiber is good for you. Take 4 g of paracetamol a day.")
    assert contains_dose("Eat well. The limit is 4 g per day. Rice is fine.")


def test_decimal_points_do_not_split_sentences() -> None:
    assert contains_dose("Use 0.5 g of the cream.")
    assert not contains_dose("Eat 0.5 g of fiber with each meal.")


def test_gram_negative_bacteria_are_not_a_gram_amount() -> None:
    assert not contains_dose("Two gram-negative bacteria were found in the sample.")
    assert not contains_dose("One gram-positive species causes this infection.")
