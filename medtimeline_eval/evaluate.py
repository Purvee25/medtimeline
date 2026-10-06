"""Field-level evaluation of extraction output against synthetic ground truth.

A predicted result is correct only if marker, value and unit all match. Values are
compared after converting both sides to the canonical unit, so a correct mmol/L
reading matches its mg/dL ground truth.

Prediction format (one JSON per report, same filename as the ground truth):
    {"results": [{"marker": "hb", "value": 13.2, "unit": "g/dL"}, ...]}

Usage:
    python -m medtimeline_eval.evaluate --truth data/synthetic --pred data/predictions
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .markers import MARKERS, to_canonical

RELATIVE_TOLERANCE = 0.01


@dataclass
class Score:
    """Counts for precision/recall over (marker, value, unit) fields."""

    correct: int = 0
    predicted: int = 0
    expected: int = 0

    def add(self, other: "Score") -> None:
        self.correct += other.correct
        self.predicted += other.predicted
        self.expected += other.expected

    @property
    def precision(self) -> float:
        return self.correct / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.expected if self.expected else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def _canonical(pred: dict) -> float | None:
    """Canonical value of a predicted result, or None if marker/unit/value is invalid."""
    try:
        return to_canonical(pred["marker"], float(pred["value"]), str(pred["unit"]))
    except (KeyError, ValueError, TypeError):
        return None


def _matches(expected: float, actual: float | None) -> bool:
    if actual is None:
        return False
    return abs(actual - expected) <= RELATIVE_TOLERANCE * max(abs(expected), 1e-9)


def score_report(truth: dict, prediction: dict | None) -> Score:
    """Score one report. A missing prediction counts every expected field as missed."""
    expected = {r["marker"]: r["canonical_value"] for r in truth["results"]}
    preds = (prediction or {}).get("results", [])
    seen: set[str] = set()
    correct = 0
    for pred in preds:
        marker = pred.get("marker")
        if marker in expected and marker not in seen and _matches(expected[marker], _canonical(pred)):
            correct += 1
        if marker in MARKERS:
            seen.add(marker)
    return Score(correct=correct, predicted=len(preds), expected=len(expected))


def evaluate(truth_dir: Path, pred_dir: Path) -> dict[str, Score]:
    """Score every ground-truth report in `truth_dir`, grouped by layout plus an 'ALL' total."""
    truth_files = sorted(truth_dir.glob("*.json"))
    if not truth_files:
        raise FileNotFoundError(f"No ground-truth JSON files in {truth_dir}")

    scores: dict[str, Score] = defaultdict(Score)
    for truth_path in truth_files:
        truth = json.loads(truth_path.read_text())
        pred_path = pred_dir / truth_path.name
        prediction = json.loads(pred_path.read_text()) if pred_path.exists() else None
        report_score = score_report(truth, prediction)
        scores[truth["layout"]].add(report_score)
        scores["ALL"].add(report_score)
    return dict(scores)


def format_table(scores: dict[str, Score]) -> str:
    """Render scores as a Markdown table, layouts sorted with ALL last."""
    lines = ["| Layout | Precision | Recall | F1 | Correct / Expected |", "|---|---|---|---|---|"]
    for layout in sorted(scores, key=lambda k: (k == "ALL", k)):
        s = scores[layout]
        lines.append(f"| {layout} | {s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} | {s.correct} / {s.expected} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--truth", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--pred", type=Path, required=True)
    args = parser.parse_args()
    print(format_table(evaluate(args.truth, args.pred)))


if __name__ == "__main__":
    main()
