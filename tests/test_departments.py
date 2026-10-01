import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box, mapping

from flat_segments import departments as dep
from flat_segments.detect import detect_all
from flat_segments.download import DownloadError
from tests.helpers import piecewise, raw_profile, straight_stroke
from tests.test_download import FakeWeb

# A 0.1° square around Labège standing for a département.
SQUARE = box(1.48, 43.48, 1.58, 43.58)


def collection(*features: tuple[str, str, object]) -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"code_insee": code, "nom_officiel": name},
                    "geometry": geometry,
                }
                for code, name, geometry in features
            ],
        }
    ).encode()


def test_download_and_load_a_department(tmp_path: Path) -> None:
    web = FakeWeb({dep.DEPARTMENTS_WFS_URL: collection(("31", "Haute-Garonne", mapping(SQUARE)))})
    path = dep.download_departments(tmp_path / "departements.geojson", web)
    assert "TYPENAMES=ADMINEXPRESS-COG-CARTO.LATEST%3Adepartement" in web.requests[0]
    department = dep.load_department(path, "31")
    assert (department.code, department.name) == ("31", "Haute-Garonne")
    area = department.outline_l93().area
    assert area == pytest.approx(8.07e3 * 11.1e3, rel=0.02)  # 0.1° x 0.1° at 43.5° N
    perimeter = department.outline_l93().length
    grown = area + perimeter * 2000 + np.pi * 2000**2  # margin of 2 km all around
    assert department.work_area_l93(2000).area == pytest.approx(grown, rel=0.01)
    with pytest.raises(KeyError, match="12"):
        dep.load_department(path, "12")


@pytest.mark.parametrize(
    "answer",
    [
        b"<ServiceExceptionReport/>",
        collection(),
        collection(("31", "x", None)),
        collection(("31", "x", mapping(box(576000, 6265000, 604000, 6278000)))),  # metres
    ],
)
def test_unexpected_wfs_answers_are_rejected(tmp_path: Path, answer: bytes) -> None:
    web = FakeWeb({dep.DEPARTMENTS_WFS_URL: answer})
    with pytest.raises(DownloadError):
        dep.download_departments(tmp_path / "departements.geojson", web)
    assert not (tmp_path / "departements.geojson").exists()


def test_a_segment_belongs_to_the_department_holding_its_midpoint() -> None:
    stroke = straight_stroke(1000)  # (0, 0) -> (1000, 0)
    [segment] = detect_all([stroke], {stroke.id: raw_profile(stroke, piecewise((1000, 0.2)))})
    shifted = replace(segment, id="flat-shifted", coords=segment.coords + np.array([700.0, 0.0]))
    outline = box(-100, -100, 1100, 100)  # holds the first midpoint (500, 0), not (1200, 0)
    assert dep.owned_segments([segment, shifted], outline) == [segment]
    assert dep.owned_segments([], outline) == []
