"""Marker catalogue: LOINC codes, canonical units, unit conversions and plausible ranges.

Single source of truth shared by the synthetic generator, the evaluator and
(later) the extraction pipeline's validation step.
"""

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

MARKERS: dict[str, Marker] = {
    m.code: m
    for m in (
        Marker("hb", "718-7", "Hemoglobin", "g/dL", (12.0, 17.0), (3.0, 25.0),
               ("Haemoglobin", "Hb", "HGB")),
        Marker("wbc", "6690-2", "Total Leucocyte Count", "10^3/uL", (4.0, 11.0), (0.5, 100.0),
               ("TLC", "WBC Count", "Total WBC Count")),
        Marker("rbc", "789-8", "RBC Count", "10^6/uL", (4.2, 5.9), (1.0, 9.0),
               ("Red Blood Cell Count", "Total RBC Count"), decimals=2),
        Marker("plt", "777-3", "Platelet Count", "10^3/uL", (150.0, 450.0), (10.0, 1500.0),
               ("Platelets", "PLT"), {"lakhs/cumm": THOUSAND_PER_UL_TO_LAKH}, decimals=0),
        Marker("chol", "2093-3", "Total Cholesterol", "mg/dL", (125.0, 200.0), (50.0, 600.0),
               ("Cholesterol, Total", "S. Cholesterol"), {"mmol/L": MG_DL_TO_MMOL_CHOL}, decimals=0),
        Marker("hdl", "2085-9", "HDL Cholesterol", "mg/dL", (40.0, 60.0), (5.0, 150.0),
               ("HDL", "HDL-C"), {"mmol/L": MG_DL_TO_MMOL_CHOL}, decimals=0),
        Marker("ldl", "13457-7", "LDL Cholesterol", "mg/dL", (50.0, 130.0), (5.0, 400.0),
               ("LDL (Calculated)", "LDL-C"), {"mmol/L": MG_DL_TO_MMOL_CHOL}, decimals=0),
        Marker("tg", "2571-8", "Triglycerides", "mg/dL", (50.0, 150.0), (10.0, 3000.0),
               ("TG", "S. Triglycerides"), {"mmol/L": MG_DL_TO_MMOL_TG}, decimals=0),
        Marker("crp", "1988-5", "C-Reactive Protein", "mg/L", (0.0, 5.0), (0.0, 500.0),
               ("CRP", "CRP (Quantitative)")),
    )
}

PANELS: dict[str, tuple[str, ...]] = {
    "CBC": ("hb", "wbc", "rbc", "plt"),
    "Lipid Profile": ("chol", "hdl", "ldl", "tg"),
    "Inflammation": ("crp",),
}

_UNIT_SYNONYMS = {"10^3/ul": "10^3/uL", "thou/mm3": "10^3/uL", "10^6/ul": "10^6/uL",
                  "mill/mm3": "10^6/uL", "g/dl": "g/dL", "mg/dl": "mg/dL",
                  "mmol/l": "mmol/L", "mg/l": "mg/L", "lakhs/cumm": "lakhs/cumm"}


def normalise_unit(unit: str) -> str:
    """Return a unit string in canonical spelling (case/whitespace-insensitive)."""
    key = unit.strip().replace(" ", "").lower()
    return _UNIT_SYNONYMS.get(key, unit.strip())


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
