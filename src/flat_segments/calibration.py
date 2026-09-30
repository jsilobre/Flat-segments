"""Calibration tools: reports, parameter sweeps, profile plots, field sheets.

These help tune the thresholds of docs/algorithm.md on real data (phase 1):

* :func:`summarize` describes a set of segments (Markdown);
* :func:`sweep` reruns detection for several values of one parameter;
* :func:`plot_segment` draws the elevation and grade profile around a segment;
* :func:`validation_sheet` produces the field validation table (in French,
  like the rest of the user documentation).
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np

from flat_segments.config import apply_overrides
from flat_segments.detect import Segment, SegmentKind, detect_all
from flat_segments.geometry import FloatArray
from flat_segments.network import EventKind, Stroke
from flat_segments.params import PipelineParams
from flat_segments.profile import Profile

DEFAULT_SITE_URL: Final = "https://jsilobre.github.io/Flat-segments/"


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def _km(segments: Sequence[Segment]) -> str:
    return f"{sum(s.length_m for s in segments) / 1000:.1f}"


def _median(values: Iterable[float]) -> str:
    items = list(values)
    return f"{statistics.median(items):.0f}" if items else "-"


def summarize(segments: Sequence[Segment]) -> str:
    """Markdown summary: counts, lengths, targets, crossings, surfaces, flags."""
    by_kind = {kind: [s for s in segments if s.kind is kind] for kind in SegmentKind}
    lines = ["# Segments report", ""]
    lines += _table(
        ("kind", "count", "total km", "median length m", "median score"),
        (
            (
                kind.value,
                len(items),
                _km(items),
                _median(s.length_m for s in items),
                _median(s.score for s in items),
            )
            for kind, items in by_kind.items()
        ),
    )
    for kind, items in by_kind.items():
        if not items:
            continue
        lines += ["", f"## {kind.value}", ""]
        fits = Counter(t for s in items for t in s.fits_targets_m)
        lines += _table(("target length m", "segments"), sorted(fits.items()))
        crossings = Counter(min(s.n_crossings, 2) for s in items)
        lines += [
            "",
            *_table(
                ("crossings", "segments"),
                (("0", crossings[0]), ("1", crossings[1]), ("2+", crossings[2])),
            ),
        ]
        surfaces = Counter(s.surface for s in items)
        lines += ["", *_table(("surface", "segments"), surfaces.most_common())]
        flags = Counter(f for s in items for f in s.quality_flags)
        if flags:
            lines += ["", *_table(("quality flag", "segments"), flags.most_common())]
    return "\n".join(lines) + "\n"


# --- sweeps -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SweepRow:
    """Detection results for one value of the swept parameter."""

    value: str
    n_flat: int
    flat_km: float
    n_climb: int
    climb_km: float


def sweep(
    strokes: Sequence[Stroke],
    z_raw: Mapping[str, FloatArray],
    params: PipelineParams,
    key: str,
    values: Sequence[str],
    elevation_source: str = "rge_alti_1m",
) -> list[SweepRow]:
    """Rerun detection with ``key`` set to each of ``values`` (override syntax).

    Raises:
        ConfigError: If ``key`` or a value is invalid.
    """
    rows = []
    for value in values:
        run_params = apply_overrides(params, [f"{key}={value}"])
        segments = detect_all(strokes, z_raw, run_params, elevation_source)
        flats = [s for s in segments if s.kind is SegmentKind.FLAT]
        climbs = [s for s in segments if s.kind is SegmentKind.CLIMB]
        rows.append(
            SweepRow(
                value=value,
                n_flat=len(flats),
                flat_km=sum(s.length_m for s in flats) / 1000,
                n_climb=len(climbs),
                climb_km=sum(s.length_m for s in climbs) / 1000,
            )
        )
    return rows


def format_sweep(key: str, rows: Sequence[SweepRow]) -> str:
    """Markdown table of a sweep."""
    lines = _table(
        (key, "flat segments", "flat km", "climbs", "climb km"),
        ((r.value, r.n_flat, f"{r.flat_km:.1f}", r.n_climb, f"{r.climb_km:.1f}") for r in rows),
    )
    return "\n".join(lines) + "\n"


# --- profile plot -----------------------------------------------------------

COLORS: Final[Mapping[SegmentKind, str]] = {
    SegmentKind.FLAT: "#1f6fb2",
    SegmentKind.CLIMB: "#d4570f",
}


def plot_segment(
    segment: Segment,
    stroke: Stroke,
    profile: Profile,
    params: PipelineParams,
    path: Path,
    context_m: float = 150.0,
) -> Path:
    """Save a PNG of the raw / smoothed elevation and local grade around a segment.

    The x axis is the distance along the stroke; bridges and tunnels are
    hatched, crossings (red) and junctions (grey) are vertical lines.
    """
    from matplotlib.figure import Figure

    start, end = segment.stroke_start_m, segment.stroke_end_m
    lo, hi = max(0.0, start - context_m), min(profile.length, end + context_m)
    d = profile.distances
    window = (d >= lo) & (d <= hi)
    color = COLORS[segment.kind]

    figure = Figure(figsize=(10, 6), dpi=110, layout="constrained")
    ax_z, ax_g = figure.subplots(2, 1, sharex=True, height_ratios=(3, 2))
    ax_z.plot(d[window], profile.z_raw[window], color="0.7", lw=1, label="MNT brut")
    ax_z.plot(d[window], profile.z[window], color="black", lw=1.5, label="profil lissé")
    ax_z.set_ylabel("altitude (m)")
    ax_g.plot(d[window], profile.grade_pct[window], color="black", lw=1.2)
    ax_g.set_ylabel("pente locale (%)")
    ax_g.set_xlabel(f"distance le long du stroke {stroke.id} (m)")
    for ax in (ax_z, ax_g):
        ax.axvspan(start, end, color=color, alpha=0.15)
        for s_start, s_end, _kind in stroke.structures():
            ax.axvspan(s_start, s_end, fill=False, hatch="//", edgecolor="0.5", lw=0)
        for event in stroke.events:
            if lo <= event.offset_m <= hi:
                crossing = event.kind is EventKind.CROSSING
                ax.axvline(event.offset_m, color="red" if crossing else "0.6", ls="--", lw=1)
        ax.grid(alpha=0.3)
    if segment.kind is SegmentKind.FLAT:
        limit = params.detection.flat.max_local_grade_pct
        for level in (-limit, limit):
            ax_g.axhline(level, color=color, ls=":", lw=1)
    else:
        # Climbs go uphill; along the stroke the grade is negative if it descends.
        climb = params.detection.climb
        z_start, z_end = np.interp([start, end], d, profile.z)
        sign = 1.0 if z_end >= z_start else -1.0
        for level in (climb.min_local_grade_pct, climb.min_mean_grade_pct):
            ax_g.axhline(sign * level, color=color, ls=":", lw=1)
    ax_z.legend(loc="best", fontsize=8)
    title = segment.name or segment.id
    ax_z.set_title(
        f"{title} — {segment.kind.value}, {segment.length_m:.0f} m, "
        f"pente moy. {segment.grade_mean_pct:.1f} %, max {segment.grade_max_pct:.1f} %, "
        f"score {segment.score:.0f}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path)
    return path


# --- field validation sheet -------------------------------------------------

VERDICTS: Final = (
    ("OK", "Conforme à la description"),
    ("PENTE", "La pente ne correspond pas (pas plat, côte trop ou pas assez raide)"),
    ("TRAVERSEE", "Traversée ou intersection non signalée, ou signalée à tort"),
    ("ACCES", "Inaccessible : privé, fermé ou dangereux"),
    ("SURFACE", "Revêtement ou éclairage faux"),
    ("GEOMETRIE", "Tracé faux, ou segment coupé au mauvais endroit"),
    ("DOUBLON", "Doublon d'un autre segment"),
    ("AUTRE", "Autre problème (préciser en remarque)"),
)
SURFACE_FR: Final[Mapping[str, str]] = {
    "paved": "revêtu",
    "compacted": "stabilisé",
    "gravel": "gravier",
    "cobbles": "pavés",
    "unpaved": "terre",
    "unknown": "inconnu",
}


def _fr(value: float, digits: int = 1) -> str:
    """Number with a French decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")


def select_for_validation(segments: Sequence[Segment], count: int) -> list[Segment]:
    """Pick a deterministic, representative sample for field validation.

    Climbs get a share proportional to their number (at least 3 when there
    are some). Within a kind, one flagged segment and one with crossings are
    included when available, then segments evenly spread over the score range.
    """
    if count >= len(segments):
        return sorted(segments, key=lambda s: (s.kind.value, -s.score))
    flats = sorted((s for s in segments if s.kind is SegmentKind.FLAT), key=lambda s: -s.score)
    climbs = sorted((s for s in segments if s.kind is SegmentKind.CLIMB), key=lambda s: -s.score)
    n_climbs = min(
        len(climbs), max(min(3, len(climbs)), round(count * len(climbs) / len(segments)))
    )
    n_flats = min(len(flats), count - n_climbs)
    picked: list[Segment] = []
    for items, quota in ((flats, n_flats), (climbs, count - n_flats)):
        chosen: list[Segment] = []
        for predicate in (lambda s: bool(s.quality_flags), lambda s: s.n_crossings > 0):
            extra = next((s for s in items if predicate(s) and s not in chosen), None)
            if extra is not None and len(chosen) < quota:
                chosen.append(extra)
        rest = [s for s in items if s not in chosen]
        needed = min(quota - len(chosen), len(rest))
        if needed > 0:
            indices = np.unique(np.linspace(0, len(rest) - 1, needed).round().astype(int))
            chosen.extend(rest[i] for i in indices)
        picked.extend(sorted(chosen, key=lambda s: -s.score))
    return picked


def validation_sheet(
    segments: Sequence[Segment],
    *,
    site_url: str = DEFAULT_SITE_URL,
    source: str = "data/processed/segments.parquet",
    today: date | None = None,
) -> str:
    """Markdown field validation table (French), with links to the map page."""
    today = today or date.today()
    lines = [
        "# Validation terrain — zone pilote",
        "",
        f"Générée le {today.isoformat()} à partir de `{source}` ({len(segments)} segments).",
        "",
        "Pour chaque segment : ouvrir le lien **Carte**, aller sur place, puis remplir",
        "**Verdict** avec un code ci-dessous. Ajouter une remarque si besoin (pente",
        "ressentie, traversée manquée, meilleur point de départ…).",
        "",
    ]
    lines += _table(("Code", "Signification"), ((f"`{c}`", m) for c, m in VERDICTS))
    lines += [""]
    rows = []
    for index, s in enumerate(segments, start=1):
        grade = (
            f"max {_fr(s.grade_max_pct)} %"
            if s.kind is SegmentKind.FLAT
            else f"moy. {_fr(s.grade_mean_pct)} %"
        )
        rows.append(
            (
                index,
                f"`{s.id}`",
                "Plat" if s.kind is SegmentKind.FLAT else "Côte",
                (s.name or "—").replace("|", "/"),
                f"{s.length_m:.0f} m",
                grade,
                s.n_crossings,
                SURFACE_FR.get(s.surface, s.surface),
                f"[voir]({site_url}?id={s.id})",
                "",
                "",
            )
        )
    lines += _table(
        (
            "#",
            "Id",
            "Type",
            "Nom",
            "Longueur",
            "Pente",
            "Traversées",
            "Revêtement",
            "Carte",
            "Verdict",
            "Remarques",
        ),
        rows,
    )
    return "\n".join(lines) + "\n"
