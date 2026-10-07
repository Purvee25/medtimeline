"""Marker catalogue: LOINC codes, canonical units, unit conversions and plausible ranges.

Single source of truth shared by the synthetic generator, the evaluator and
(later) the extraction pipeline's validation step.
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Marker:
    """A lab marker with its standard code and unit rules.

    Attributes:
        code: Internal stable key.
        loinc: LOINC code for the observation.
        name: Canonical display name.
        canonical_unit: Unit all values are normalised to.
        normal_range: Generic adult reference range in canonical units (approximate).
        plausible_range: Physiologically possible bounds; values outside are likely OCR errors.
        aliases: Names labs print for this marker.
        alt_units: Other printed units mapped to factor, where alt_value = canonical_value * factor.
        decimals: Decimal places labs typically print in canonical units.
    """

    code: str
    loinc: str
    name: str
    canonical_unit: str
    normal_range: tuple[float, float]
    plausible_range: tuple[float, float]
    aliases: tuple[str, ...] = ()
    alt_units: dict[str, float] = field(default_factory=dict)
    decimals: int = 1


MG_DL_TO_MMOL_CHOL = 0.02586
MG_DL_TO_MMOL_TG = 0.01129
THOUSAND_PER_UL_TO_LAKH = 0.01
MMOL_L_TO_MG_DL_GLUCOSE = 18.016
UMOL_L_TO_MG_DL_CREAT = 0.01131
UMOL_L_TO_MG_DL_URIC = 0.01681

MARKERS: dict[str, Marker] = {
    m.code: m
    for m in (
        Marker("hb", "718-7", "Hemoglobin", "g/dL", (12.0, 17.0), (3.0, 25.0), ("Haemoglobin", "Hb", "HGB")),
        Marker(
            "wbc",
            "6690-2",
            "Total Leucocyte Count",
            "10^3/uL",
            (4.0, 11.0),
            (0.5, 100.0),
            ("TLC", "WBC Count", "Total WBC Count"),
        ),
        Marker(
            "rbc",
            "789-8",
            "RBC Count",
            "10^6/uL",
            (4.2, 5.9),
            (1.0, 9.0),
            ("Red Blood Cell Count", "Total RBC Count"),
            decimals=2,
        ),
        Marker(
            "plt",
            "777-3",
            "Platelet Count",
            "10^3/uL",
            (150.0, 450.0),
            (10.0, 1500.0),
            ("Platelets", "PLT"),
            {"lakhs/cumm": THOUSAND_PER_UL_TO_LAKH},
            decimals=0,
        ),
        Marker(
            "chol",
            "2093-3",
            "Total Cholesterol",
            "mg/dL",
            (125.0, 200.0),
            (50.0, 600.0),
            ("Cholesterol, Total", "S. Cholesterol"),
            {"mmol/L": MG_DL_TO_MMOL_CHOL},
            decimals=0,
        ),
        Marker(
            "hdl",
            "2085-9",
            "HDL Cholesterol",
            "mg/dL",
            (40.0, 60.0),
            (5.0, 150.0),
            ("HDL", "HDL-C"),
            {"mmol/L": MG_DL_TO_MMOL_CHOL},
            decimals=0,
        ),
        Marker(
            "ldl",
            "13457-7",
            "LDL Cholesterol",
            "mg/dL",
            (50.0, 130.0),
            (5.0, 400.0),
            ("LDL (Calculated)", "LDL-C"),
            {"mmol/L": MG_DL_TO_MMOL_CHOL},
            decimals=0,
        ),
        Marker(
            "tg",
            "2571-8",
            "Triglycerides",
            "mg/dL",
            (50.0, 150.0),
            (10.0, 3000.0),
            ("TG", "S. Triglycerides"),
            {"mmol/L": MG_DL_TO_MMOL_TG},
            decimals=0,
        ),
        Marker("crp", "1988-5", "C-Reactive Protein", "mg/L", (0.0, 5.0), (0.0, 500.0), ("CRP", "CRP (Quantitative)")),
        # Thyroid
        Marker(
            "tsh",
            "3016-3",
            "TSH",
            "mIU/L",
            (0.4, 4.0),
            (0.001, 200.0),
            ("Thyroid Stimulating Hormone", "S. TSH", "TSH (Ultrasensitive)"),
            decimals=2,
        ),
        Marker(
            "t4",
            "3026-2",
            "Free T4",
            "ng/dL",
            (0.8, 1.8),
            (0.1, 10.0),
            ("FT4", "Free Thyroxine", "T4 Free"),
            decimals=2,
        ),
        # Liver function
        Marker(
            "alt",
            "1742-6",
            "ALT (SGPT)",
            "U/L",
            (7.0, 56.0),
            (1.0, 3000.0),
            ("SGPT", "Alanine Aminotransferase", "ALT/SGPT"),
            decimals=0,
        ),
        Marker(
            "ast",
            "1920-8",
            "AST (SGOT)",
            "U/L",
            (10.0, 40.0),
            (1.0, 5000.0),
            ("SGOT", "Aspartate Aminotransferase", "AST/SGOT"),
            decimals=0,
        ),
        Marker(
            "alp",
            "6768-6",
            "Alkaline Phosphatase",
            "U/L",
            (44.0, 147.0),
            (10.0, 3000.0),
            ("ALP", "Alk. Phosphatase"),
            decimals=0,
        ),
        Marker(
            "tbili",
            "1975-2",
            "Total Bilirubin",
            "mg/dL",
            (0.2, 1.2),
            (0.0, 50.0),
            ("T. Bilirubin", "Serum Bilirubin Total", "Bilirubin Total"),
            decimals=1,
        ),
        # Kidney function
        Marker(
            "creat",
            "2160-0",
            "Creatinine",
            "mg/dL",
            (0.6, 1.2),
            (0.1, 30.0),
            ("S. Creatinine", "Serum Creatinine", "Creatinine (Serum)"),
            {"umol/L": UMOL_L_TO_MG_DL_CREAT, "µmol/L": UMOL_L_TO_MG_DL_CREAT},
            decimals=2,
        ),
        Marker(
            "bun",
            "3094-0",
            "Blood Urea Nitrogen",
            "mg/dL",
            (7.0, 20.0),
            (1.0, 200.0),
            ("BUN", "Urea Nitrogen", "Blood Urea"),
            decimals=0,
        ),
        Marker(
            "uric",
            "3084-1",
            "Uric Acid",
            "mg/dL",
            (2.5, 7.0),
            (0.5, 30.0),
            ("S. Uric Acid", "Serum Uric Acid", "Uric Acid (Serum)"),
            {"umol/L": UMOL_L_TO_MG_DL_URIC, "µmol/L": UMOL_L_TO_MG_DL_URIC},
            decimals=1,
        ),
        # Glucose / diabetes
        Marker(
            "glu",
            "2345-7",
            "Fasting Blood Glucose",
            "mg/dL",
            (70.0, 100.0),
            (20.0, 800.0),
            ("FBS", "Fasting Blood Sugar", "Fasting Glucose", "Glucose (F)"),
            {"mmol/L": 1 / MMOL_L_TO_MG_DL_GLUCOSE},
            decimals=0,
        ),
        Marker(
            "pp_glu",
            "2339-0",
            "Post-Prandial Glucose",
            "mg/dL",
            (70.0, 140.0),
            (20.0, 800.0),
            ("PPBS", "Post Prandial Blood Sugar", "PP Glucose", "Glucose (PP)"),
            {"mmol/L": 1 / MMOL_L_TO_MG_DL_GLUCOSE},
            decimals=0,
        ),
        Marker(
            "hba1c",
            "4548-4",
            "HbA1c",
            "%",
            (4.0, 5.6),
            (2.0, 20.0),
            ("Glycated Haemoglobin", "Glycosylated Hb", "HbA1C", "A1C"),
            decimals=1,
        ),
        # Iron studies
        Marker(
            "ferritin",
            "2276-4",
            "Ferritin",
            "ng/mL",
            (12.0, 300.0),
            (1.0, 10000.0),
            ("S. Ferritin", "Serum Ferritin"),
            decimals=0,
        ),
        Marker(
            "vitd",
            "14635-7",
            "Vitamin D (25-OH)",
            "ng/mL",
            (30.0, 100.0),
            (1.0, 200.0),
            ("25-OH Vitamin D", "Vit D", "Vitamin D Total", "25(OH)D"),
            decimals=1,
        ),
        Marker(
            "vitb12",
            "2132-9",
            "Vitamin B12",
            "pg/mL",
            (200.0, 900.0),
            (50.0, 5000.0),
            ("Cobalamin", "Vit B12", "Cyanocobalamin"),
            decimals=0,
        ),
    )
}

PANELS: dict[str, tuple[str, ...]] = {
    "CBC": ("hb", "wbc", "rbc", "plt"),
    "Lipid Profile": ("chol", "hdl", "ldl", "tg"),
    "Liver Function": ("alt", "ast", "alp", "tbili"),
    "Kidney Function": ("creat", "bun", "uric"),
    "Thyroid": ("tsh", "t4"),
    "Diabetes": ("glu", "pp_glu", "hba1c"),
    "Vitamins & Iron": ("ferritin", "vitd", "vitb12"),
    "Inflammation": ("crp",),
}

_UNIT_SYNONYMS = {
    "10^3/ul": "10^3/uL",
    "thou/mm3": "10^3/uL",
    "10^6/ul": "10^6/uL",
    "mill/mm3": "10^6/uL",
    "g/dl": "g/dL",
    "mg/dl": "mg/dL",
    "mmol/l": "mmol/L",
    "mg/l": "mg/L",
    "lakhs/cumm": "lakhs/cumm",
    "u/l": "U/L",
    "iu/l": "U/L",
    "miu/l": "mIU/L",
    "uiu/ml": "mIU/L",
    "ng/dl": "ng/dL",
    "ng/ml": "ng/mL",
    "pg/ml": "pg/mL",
    "umol/l": "umol/L",
    "µmol/l": "µmol/L",
}


# OCR misreads the caret in "10^3/uL" as "4" ("1043/uL"), as a punctuation glyph ("10°6/uL",
# "10%6/uL", a curly quote), or drops it ("103/uL"); "µ" comes back as "u" or "p". Anchored to the
# whole string so it only rewrites what is plainly a count unit. Lost leading digits ("403/uL")
# are deliberately not guessed at: those rows go to review.
_OCR_POWER_UNIT = re.compile(r"^10(?:4|[^\w\s/])?(?P<exp>[36])/[uµp]l$")


def normalise_unit(unit: str) -> str:
    """Return a unit string in canonical spelling (case/whitespace-insensitive, OCR-tolerant)."""
    key = unit.strip().replace(" ", "").lower()
    if key in _UNIT_SYNONYMS:
        return _UNIT_SYNONYMS[key]
    if match := _OCR_POWER_UNIT.match(key):
        return f"10^{match['exp']}/uL"
    return unit.strip()


def to_canonical(code: str, value: float, unit: str) -> float:
    """Convert a value in `unit` to the marker's canonical unit.

    Raises:
        KeyError: Unknown marker code.
        ValueError: Unit is not recognised for this marker.
    """
    marker = MARKERS[code]
    unit = normalise_unit(unit)
    if unit == marker.canonical_unit:
        return value
    if unit in marker.alt_units:
        return value / marker.alt_units[unit]
    raise ValueError(f"Unit {unit!r} not valid for marker {code!r}")


def is_plausible(code: str, canonical_value: float) -> bool:
    """True if a canonical value lies within the marker's physiologically possible range."""
    low, high = MARKERS[code].plausible_range
    return low <= canonical_value <= high
