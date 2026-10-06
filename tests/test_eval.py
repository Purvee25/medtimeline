import json

import pytest

from medtimeline_eval.evaluate import evaluate, score_report
from medtimeline_eval.generate import LAYOUTS, generate_dataset
from medtimeline_eval.markers import MARKERS, is_plausible, normalise_unit, to_canonical


def _perfect_prediction(truth: dict) -> dict:
    return {"results": [{"marker": r["marker"], "value": r["value"], "unit": r["unit"]} for r in truth["results"]]}


def test_mmol_converts_back_to_mg_dl():
    assert to_canonical("chol", 5.17, "mmol/L") == pytest.approx(200, rel=0.01)


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        to_canonical("hb", 13.0, "mmol/L")


def test_lost_decimal_point_is_implausible():
    assert not is_plausible("hb", 132.0)


def test_all_loinc_codes_present():
    assert all(m.loinc for m in MARKERS.values())


def test_generator_covers_every_layout_and_is_deterministic(tmp_path):
    first = generate_dataset(8, tmp_path / "a", seed=1)
    second = generate_dataset(8, tmp_path / "b", seed=1)
    assert {t["layout"] for t in first} == set(LAYOUTS)
    assert first == [{**t} for t in second]
    assert len(list((tmp_path / "a").glob("*.pdf"))) == 8


def test_perfect_predictions_score_one(tmp_path):
    truths = generate_dataset(8, tmp_path / "truth", seed=3)
    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    for t in truths:
        (pred_dir / f"{t['report_id']}.json").write_text(json.dumps(_perfect_prediction(t)))
    assert evaluate(tmp_path / "truth", pred_dir)["ALL"].f1 == 1.0


def test_missing_prediction_counts_as_missed():
    truth = {"layout": "x", "results": [{"marker": "hb", "canonical_value": 13.0}]}
    score = score_report(truth, None)
    assert (score.correct, score.expected, score.recall) == (0, 1, 0.0)


def test_wrong_value_and_duplicates_are_penalised():
    truth = {"layout": "x", "results": [{"marker": "hb", "canonical_value": 13.0}]}
    pred = {
        "results": [
            {"marker": "hb", "value": 13.0, "unit": "g/dL"},
            {"marker": "hb", "value": 13.0, "unit": "g/dL"},
            {"marker": "wbc", "value": 7, "unit": "10^3/uL"},
        ]
    }
    score = score_report(truth, pred)
    assert (score.correct, score.predicted) == (1, 3)
    assert score_report(truth, {"results": [{"marker": "hb", "value": 1.3, "unit": "g/dL"}]}).correct == 0


def test_empty_truth_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluate(tmp_path, tmp_path)


@pytest.mark.parametrize(
    "ocr,expected",
    [
        ("1043/uL", "10^3/uL"),
        ("1046/uL", "10^6/uL"),
        ("103/ul", "10^3/uL"),
        ("10*3/µL", "10^3/uL"),
        ("10^6/pL", "10^6/uL"),
        ("10°6/uL", "10^6/uL"),
        ("10\u20196/uL", "10^6/uL"),  # curly-quote caret
        ("10%6/uL", "10^6/uL"),
    ],
)
def test_normalise_unit_repairs_ocr_caret(ocr, expected):
    assert normalise_unit(ocr) == expected


@pytest.mark.parametrize("unit", ["1043/mL", "10435/uL", "403/uL", "mo/L", "g/dL", "mg/L"])
def test_normalise_unit_leaves_other_units_alone(unit):
    assert normalise_unit(unit) == unit
