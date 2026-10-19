import random
from datetime import date
from types import SimpleNamespace

import pytest

from medtimeline_eval.generate import generate_report
from medtimeline_extract import pipeline
from medtimeline_extract.llm import ExtractedResult, Extraction
from medtimeline_extract.pipeline import Status, process_report, validate
from medtimeline_extract.text import extract_text, redact_identifiers


def _row(marker: str, value: float, unit: str) -> ExtractedResult:
    return ExtractedResult(marker=marker, printed_name=marker, value=value, unit=unit)


@pytest.mark.parametrize("layout,method", [("table_classic", "text_layer"), ("scanned", "ocr")])
def test_extract_text_reads_results_from_both_pdf_kinds(tmp_path, layout, method):
    truth = generate_report("r1", layout, random.Random(5), tmp_path)
    text, used = extract_text(tmp_path / "r1.pdf")
    assert used == method
    assert truth["results"][0]["label"].split()[0].lower() in text.lower()


def test_non_pdf_is_rejected(tmp_path):
    fake = tmp_path / "x.pdf"
    fake.write_bytes(b"MZ not a pdf")
    with pytest.raises(ValueError):
        extract_text(fake)


def test_redaction_removes_identifiers_but_keeps_date_and_results():
    text = "Patient: Rohan Patel    Age/Sex: 68/M\nSample collected: 2025-12-24    Report ID: rpt_001\nHGB 14.8 g/dL"
    redacted = redact_identifiers(text)
    assert "Rohan" not in redacted and "rpt_001" not in redacted and "68/M" not in redacted
    assert "2025-12-24" in redacted and "HGB 14.8 g/dL" in redacted


def test_validate_converts_alt_units():
    assert validate(_row("chol", 5.17, "mmol/l")).canonical_value == pytest.approx(200, rel=0.01)


@pytest.mark.parametrize(
    "row,issue",
    [
        (_row("hb", 132.0, "g/dL"), "implausible_value"),
        (_row("hb", 13.2, "mmol/L"), "unit_mismatch"),
        (_row("unknown", 1.0, "x"), "unrecognised_marker"),
    ],
)
def test_validate_flags_suspicious_rows(row, issue):
    assert validate(row).issues == [issue]


def _fake_extract(results):
    return lambda text, client: Extraction(collected_on=date(2025, 1, 2), results=results)


def test_clean_report_is_extracted(tmp_path, monkeypatch):
    generate_report("r1", "table_classic", random.Random(1), tmp_path)
    monkeypatch.setattr(pipeline, "extract_results", _fake_extract([_row("hb", 13.0, "g/dL")]))
    assert process_report(tmp_path / "r1.pdf", client=None)["status"] == Status.EXTRACTED


def test_suspicious_or_empty_report_needs_review(tmp_path, monkeypatch):
    generate_report("r1", "table_classic", random.Random(1), tmp_path)
    monkeypatch.setattr(
        pipeline, "extract_results", _fake_extract([_row("hb", 13.0, "g/dL"), _row("hb", 13.0, "g/dL")])
    )
    assert process_report(tmp_path / "r1.pdf", client=None)["status"] == Status.NEEDS_REVIEW
    monkeypatch.setattr(pipeline, "extract_results", _fake_extract([]))
    assert process_report(tmp_path / "r1.pdf", client=None)["status"] == Status.NEEDS_REVIEW


def test_llm_failure_marks_report_failed_without_raising(tmp_path, monkeypatch):
    generate_report("r1", "table_classic", random.Random(1), tmp_path)

    def boom(text, client):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline, "extract_results", boom)
    out = process_report(tmp_path / "r1.pdf", client=None)
    assert out["status"] == Status.FAILED and out["results"] == []


def test_baseline_reads_table_dotted_and_alias_rows():
    from medtimeline_extract.baseline import extract_baseline

    text = (
        "Sample collected: 24/12/2025\n"
        "HGB                 14.8        g/dL        12.0 - 17.0\n"
        "Red Blood Cell Count 3.82 L     10^6/uL     4.20 - 5.90\n"
        "HDL Cholesterol ............... 1.10 mmol/L  (1.03 - 1.55)\n"
        "Investigation  Observed Value  Units\n"
    )
    out = extract_baseline(text)
    assert out.collected_on == date(2025, 12, 24)
    assert [(r.marker.value, r.value, r.unit) for r in out.results] == [
        ("hb", 14.8, "g/dL"),
        ("rbc", 3.82, "10^6/uL"),
        ("hdl", 1.10, "mmol/L"),
    ]


def test_baseline_reads_column_layout_rows():
    # pdftotext output of a hospital column layout: specimen in brackets, method glued to the
    # value, unit before or after the value, Indian digit grouping, and wrapped rows.
    from medtimeline_extract.baseline import extract_baseline

    text = (
        " Labelled on : 04-Mar-2026 09:10 AM      Sample Collected on: 05-Mar-2026 09:32 AM\n"
        "HAEMOGLOBIN (Whole Blood EDTA)          13.6 Automated -SLS -Hb          g/dLFemale : 12-15\n"
        "TOTAL RBC COUNT      (Whole Blood     Hydrodynamic Focusing      Million / 4.62Female : 3.8 - 4.8\n"
        "EDTA  )                                                                 cu.mm\n"
        "MCV (Whole Blood EDTA)          88 *Electrical Impedance          83 - 101          fL\n"
        "Total Leucocyte Count (Whole Blood      Hydrodynamic Focusing      /cu.mm7,250 4000 - 10000\n"
        "EDTA  )\n"
        "PLATELET COUNT      (Whole Blood      Hydrodynamic Focusing      /cu.mm2,85,0001,50,000 - 4,10,000\n"
    )
    out = extract_baseline(text)

    assert out.collected_on == date(2026, 3, 5)
    assert [(r.marker.value, validate(r).canonical_value, validate(r).issues) for r in out.results] == [
        ("hb", 13.6, []),
        ("rbc", 4.62, []),
        ("wbc", 7.25, []),
        ("plt", 285.0, []),
    ]


def test_baseline_prefers_longest_label():
    from medtimeline_extract.baseline import extract_baseline

    (row,) = extract_baseline("LDL Cholesterol 120 mg/dL").results
    assert row.marker.value == "ldl"


@pytest.mark.parametrize(
    "line",
    [
        "Name - Rohan Patel",
        "Pt Name Rohan Patel",
        "DOB: 01/02/1980",
        "D.O.B 01/02/1980",
        "UHID - AB1234",
        "MRN 55512",
        "PATIENT ID 778899",
        "Address - 12 MG Road, Pune",
        "Ref. by Dr. Mehta",
        "Mr. Rohan Patel 45Y/M",
        "Rohan Patel 45 Yrs / M",
        "Age: 45 Sex: M",
        "Age/Sex: 45 Y / M",
        "Gender : Female",
        "Contact 9876543210",
    ],
)
def test_redaction_drops_identifying_lines(line):
    assert redact_identifiers(line).strip() == ""


@pytest.mark.parametrize(
    "line,secret",
    [
        ("Call +91 98765 43210 for queries", "98765"),
        ("Report emailed to rohan.p@example.com", "rohan.p@example.com"),
        ("1234 5678 9012", "1234 5678 9012"),
    ],
)
def test_redaction_scrubs_unlabelled_identifier_values(line, secret):
    assert secret not in redact_identifiers(line)


@pytest.mark.parametrize(
    "line",
    [
        "Hemoglobin 13.2 g/dL 12.0 - 17.0",
        "Platelet Count 264 10^3/uL 150 - 450",
        "Total Leucocyte Count ........ 6.6 10^3/uL (4.0 - 11.0)",
        "LDL Cholesterol 118 mg/dL 50 - 130",
        "Triglycerides 1.59 mmol/L",
        "C-Reactive Protein 4.4 mg/L 0.0 - 5.0",
        # Value and reference range in separate columns: 11 digits in total, but not one number.
        "ABSOLUTE NEUTROPHIL COUNT     Calculated     /cu.mm4,870     2000 - 7000",
    ],
)
def test_redaction_keeps_result_rows(line):
    assert redact_identifiers(line) == line


def test_redaction_salvages_collection_date_from_identifier_line():
    out = redact_identifiers("Patient: Rohan Patel   Sample collected: 2025-12-24   Report ID: rpt_001")
    assert out == "Sample collected: 2025-12-24"


def test_redaction_salvages_month_name_collection_date():
    out = redact_identifiers("Patient: Rohan Patel   Sample collected: 05-Mar-2026 09:32 AM")
    assert out == "Sample collected: 05-Mar-2026"


def test_pdf_page_limit(tmp_path, monkeypatch):
    from medtimeline_extract import text as text_module

    generate_report("r1", "table_classic", random.Random(1), tmp_path)
    monkeypatch.setattr(text_module, "MAX_PDF_PAGES", 0)
    with pytest.raises(ValueError, match="pages"):
        extract_text(tmp_path / "r1.pdf")


class _FakeGeminiModels:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text, usage_metadata=None)


def test_gemini_extractor_parses_structured_response():
    pytest.importorskip("google.genai")
    from medtimeline_extract.gemini import MODEL, extract_results_gemini

    models = _FakeGeminiModels(
        '{"collected_on": "2026-03-01", "results": '
        '[{"marker": "hb", "printed_name": "Haemoglobin", "value": 13.2, "unit": "g/dL"}]}'
    )
    out = extract_results_gemini("Haemoglobin 13.2 g/dL", SimpleNamespace(models=models))

    assert out.collected_on == date(2026, 3, 1)
    assert [(r.marker.value, r.value, r.unit) for r in out.results] == [("hb", 13.2, "g/dL")]
    assert models.calls[0]["model"] == MODEL
    assert "<report>" in models.calls[0]["contents"]


def test_gemini_extractor_rejects_off_schema_response():
    pytest.importorskip("google.genai")
    from pydantic import ValidationError

    from medtimeline_extract.gemini import extract_results_gemini

    models = _FakeGeminiModels('{"results": [{"marker": "not-a-marker"}]}')
    with pytest.raises(ValidationError):
        extract_results_gemini("text", SimpleNamespace(models=models))


def test_extractor_label_is_recorded_in_prediction(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "extract_text", lambda pdf: ("Haemoglobin 13.0 g/dL", "text_layer"))
    fake = lambda text: Extraction(collected_on=date(2026, 3, 1), results=[_row("hb", 13.0, "g/dL")])  # noqa: E731

    prediction = process_report(tmp_path / "r1.pdf", None, fake, prompt_version="v2+gemini-test")

    assert prediction["prompt_version"] == "v2+gemini-test"
