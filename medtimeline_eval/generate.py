"""Synthetic lab-report generator with automatic ground truth.

Renders PDF reports in several layouts from randomly sampled values and writes a
matching ``<report_id>.json`` ground-truth file. All names and labs are fictional.

Usage:
    python -m medtimeline_eval.generate --n 40 --out data/synthetic --seed 7
"""

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .markers import MARKERS, PANELS, to_canonical

LAYOUTS = ("table_classic", "alias_alt_units", "inline_dotted", "scanned")
LABS = ("Sunrise Diagnostics", "Apex Pathlabs", "Metro Health Labs", "CarePoint Diagnostics")
FIRST_NAMES = ("Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vihaan", "Anaya")
LAST_NAMES = ("Sharma", "Iyer", "Khan", "Patel", "Das", "Reddy", "Singh", "Menon")
ABNORMAL_RATE = 0.3
ABNORMAL_SPREAD = 0.4
ALT_UNIT_RATE = 0.6
SCAN_DPI = 150
SCAN_MAX_ROTATION_DEG = 1.5
SCAN_NOISE_PIXELS = 4000
PAGE_W, PAGE_H = A4


@dataclass
class ResultRow:
    """One printed result line plus its ground truth."""

    marker: str
    loinc: str
    label: str
    value: float
    unit: str
    canonical_value: float
    canonical_unit: str
    ref_low: float
    ref_high: float

    @property
    def flag(self) -> str:
        if self.value < self.ref_low:
            return "L"
        return "H" if self.value > self.ref_high else ""


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _sample_row(code: str, layout: str, rng: random.Random) -> ResultRow:
    marker = MARKERS[code]
    low, high = marker.normal_range
    width = high - low
    if rng.random() < ABNORMAL_RATE:
        canonical = rng.uniform(low - width * ABNORMAL_SPREAD, high + width * ABNORMAL_SPREAD)
    else:
        canonical = rng.uniform(low, high)
    canonical = max(canonical, marker.plausible_range[0])

    label = rng.choice(marker.aliases) if layout == "alias_alt_units" else marker.name
    unit, factor, decimals = marker.canonical_unit, 1.0, marker.decimals
    if layout == "alias_alt_units" and marker.alt_units and rng.random() < ALT_UNIT_RATE:
        unit, factor = rng.choice(list(marker.alt_units.items()))
        decimals = 2

    printed = round(canonical * factor, decimals)
    return ResultRow(
        marker=code,
        loinc=marker.loinc,
        label=label,
        value=printed,
        unit=unit,
        canonical_value=round(to_canonical(code, printed, unit), 4),
        canonical_unit=marker.canonical_unit,
        ref_low=round(low * factor, decimals),
        ref_high=round(high * factor, decimals),
    )


def _row_text(row: ResultRow) -> tuple[str, str, str, str]:
    marker = MARKERS[row.marker]
    decimals = marker.decimals if row.unit == marker.canonical_unit else 2
    ref = f"{_fmt(row.ref_low, decimals)} - {_fmt(row.ref_high, decimals)}"
    return row.label, f"{_fmt(row.value, decimals)} {row.flag}".strip(), row.unit, ref


def _header_lines(meta: dict) -> list[str]:
    return [
        f"Patient: {meta['patient_name']}    Age/Sex: {meta['age']}/{meta['sex']}",
        f"Sample collected: {meta['collected_on']}    Report ID: {meta['report_id']}",
    ]


def _draw_pdf(path: Path, meta: dict, panels: dict[str, list[ResultRow]], layout: str) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    font = "Times-Roman" if layout == "inline_dotted" else "Helvetica"
    y = PAGE_H - 60
    pdf.setFont(f"{font}-Bold" if font == "Helvetica" else "Times-Bold", 16)
    pdf.drawString(50, y, meta["lab"])
    pdf.setFont(font, 10)
    for line in _header_lines(meta):
        y -= 18
        pdf.drawString(50, y, line)
    y -= 30

    columns = (50, 230, 330, 420) if layout == "table_classic" else (50, 250, 340, 440)
    headings = ("Test", "Result", "Unit", "Reference Range")
    if layout == "alias_alt_units":
        headings = ("Investigation", "Observed Value", "Units", "Bio. Ref. Interval")

    for panel, rows in panels.items():
        pdf.setFont(font, 12)
        pdf.drawString(50, y, panel.upper())
        y -= 18
        pdf.setFont(font, 10)
        if layout == "inline_dotted":
            for row in rows:
                label, value, unit, ref = _row_text(row)
                pdf.drawString(50, y, f"{label} {'.' * max(4, 40 - len(label))} {value} {unit}  ({ref})")
                y -= 16
        else:
            for x, heading in zip(columns, headings, strict=True):
                pdf.drawString(x, y, heading)
            y -= 4
            pdf.line(50, y, PAGE_W - 50, y)
            y -= 14
            for row in rows:
                for x, text in zip(columns, _row_text(row), strict=True):
                    pdf.drawString(x, y, text)
                y -= 16
        y -= 20

    pdf.setFont(font, 8)
    pdf.drawString(50, 40, "SYNTHETIC REPORT - generated for testing, not a real patient.")
    pdf.save()


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in ("/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _draw_scanned(path: Path, meta: dict, panels: dict[str, list[ResultRow]], rng: random.Random) -> None:
    scale = SCAN_DPI / 72
    img = Image.new("L", (int(PAGE_W * scale), int(PAGE_H * scale)), 255)
    draw = ImageDraw.Draw(img)
    big, small = _load_font(int(16 * scale)), _load_font(int(10 * scale))

    def text(x: float, y: float, s: str, font: ImageFont.ImageFont = small) -> None:
        draw.text((x * scale, y * scale), s, fill=0, font=font)

    y = 50.0
    text(50, y, meta["lab"], big)
    for line in _header_lines(meta):
        y += 22
        text(50, y, line)
    y += 34
    for panel, rows in panels.items():
        text(50, y, panel.upper())
        y += 18
        for x, heading in zip((50, 230, 330, 420), ("Test", "Result", "Unit", "Reference Range"), strict=True):
            text(x, y, heading)
        y += 18
        for row in rows:
            for x, s in zip((50, 230, 330, 420), _row_text(row), strict=True):
                text(x, y, s)
            y += 18
        y += 20

    for _ in range(SCAN_NOISE_PIXELS):
        img.putpixel((rng.randrange(img.width), rng.randrange(img.height)), rng.randint(0, 120))
    img = img.rotate(rng.uniform(-SCAN_MAX_ROTATION_DEG, SCAN_MAX_ROTATION_DEG), fillcolor=255, expand=False)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img.save(path, "PDF", resolution=SCAN_DPI)


def generate_report(report_id: str, layout: str, rng: random.Random, out_dir: Path) -> dict:
    """Render one report PDF and write its ground-truth JSON.

    Returns:
        The ground-truth dict that was written.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"Unknown layout {layout!r}; expected one of {LAYOUTS}")

    chosen = rng.sample(list(PANELS), k=rng.randint(1, 2))
    panels = {p: [_sample_row(code, layout, rng) for code in PANELS[p]] for p in chosen}
    meta = {
        "report_id": report_id,
        "layout": layout,
        "lab": rng.choice(LABS),
        "patient_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        "age": rng.randint(18, 80),
        "sex": rng.choice("MF"),
        "collected_on": (date(2025, 1, 1) + timedelta(days=rng.randrange(500))).isoformat(),
    }

    pdf_path = out_dir / f"{report_id}.pdf"
    if layout == "scanned":
        _draw_scanned(pdf_path, meta, panels, rng)
    else:
        _draw_pdf(pdf_path, meta, panels, layout)

    truth = {**meta, "results": [asdict(r) for rows in panels.values() for r in rows]}
    (out_dir / f"{report_id}.json").write_text(json.dumps(truth, indent=2))
    return truth


def generate_dataset(n: int, out_dir: Path, seed: int) -> list[dict]:
    """Generate `n` reports, cycling through layouts so each is evenly represented."""
    if n < 1:
        raise ValueError("n must be >= 1")
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    return [generate_report(f"rpt_{i:03d}", LAYOUTS[i % len(LAYOUTS)], rng, out_dir) for i in range(n)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    reports = generate_dataset(args.n, args.out, args.seed)
    print(f"Wrote {len(reports)} reports to {args.out}")


if __name__ == "__main__":
    main()
