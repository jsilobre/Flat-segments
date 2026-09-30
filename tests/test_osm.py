from pathlib import Path

import numpy as np
import pytest

from flat_segments import osm
from flat_segments.network import RoadClass


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "cycleway"}, RoadClass.PATH),
        ({"highway": "track", "tracktype": "grade2"}, RoadClass.PATH),
        ({"highway": "residential"}, RoadClass.MINOR),
        ({"highway": "tertiary"}, RoadClass.MAJOR),
        ({"highway": "primary", "access": "private"}, RoadClass.MAJOR),
        ({"highway": "steps"}, None),
        ({"building": "yes"}, None),
        ({"highway": "service", "service": "driveway"}, None),
        ({"highway": "service", "service": "alley"}, RoadClass.MINOR),
        ({"highway": "footway", "access": "private"}, None),
        ({"highway": "footway", "access": "private", "foot": "permissive"}, RoadClass.PATH),
        ({"highway": "cycleway", "foot": "no"}, None),
        ({"highway": "pedestrian", "area": "yes"}, None),
        ({"highway": "footway", "oneway:foot": "yes"}, None),
    ],
)
def test_classify_way(tags: dict[str, str], expected: RoadClass | None) -> None:
    assert osm.classify_way(tags) is expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"bridge": "yes"}, "bridge"),
        ({"bridge": "viaduct"}, "bridge"),
        ({"bridge": "no"}, None),
        ({"tunnel": "building_passage"}, "tunnel"),
        ({"covered": "yes"}, "tunnel"),
        ({}, None),
    ],
)
def test_structure_of(tags: dict[str, str], expected: str | None) -> None:
    assert osm.structure_of(tags) == expected


@pytest.mark.parametrize(
    ("surface", "tracktype", "road_class", "expected"),
    [
        ("asphalt", None, None, "paved"),
        ("fine_gravel", None, None, "compacted"),
        ("sett", None, None, "cobbles"),
        ("ground", "grade1", None, "unpaved"),
        ("weird", None, None, "unknown"),
        (None, "grade1", None, "compacted"),
        (None, "grade4", None, "unpaved"),
        (None, None, RoadClass.MINOR, "paved"),
        (None, None, RoadClass.PATH, "unknown"),
    ],
)
def test_surface_category(
    surface: str | None, tracktype: str | None, road_class: RoadClass | None, expected: str
) -> None:
    assert osm.surface_category(surface, tracktype, road_class) == expected


@pytest.mark.parametrize(
    ("lit", "expected"),
    [("yes", "yes"), ("automatic", "yes"), ("no", "no"), ("disused", "no"), (None, "unknown")],
)
def test_lit_category(lit: str | None, expected: str) -> None:
    assert osm.lit_category(lit) == expected


OSM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="43.5300" lon="1.5300" version="1"/>
  <node id="2" lat="43.5300" lon="1.5350" version="1"/>
  <node id="3" lat="43.5300" lon="1.5400" version="1"/>
  <node id="4" lat="43.5250" lon="1.5350" version="1"/>
  <node id="5" lat="43.6500" lon="1.9000" version="1"/>
  <node id="6" lat="43.6500" lon="1.9100" version="1"/>
  <way id="10" version="1">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="cycleway"/><tag k="surface" v="asphalt"/>
    <tag k="lit" v="yes"/><tag k="name" v="Voie verte"/>
  </way>
  <way id="11" version="1">
    <nd ref="4"/><nd ref="2"/>
    <tag k="highway" v="tertiary"/>
  </way>
  <way id="12" version="1">
    <nd ref="2"/><nd ref="4"/>
    <tag k="highway" v="steps"/>
  </way>
  <way id="13" version="1">
    <nd ref="5"/><nd ref="6"/>
    <tag k="highway" v="footway"/>
  </way>
  <way id="14" version="1">
    <nd ref="1"/><nd ref="4"/>
    <tag k="building" v="yes"/>
  </way>
</osm>
"""


def test_read_ways_from_osm_xml(tmp_path: Path) -> None:
    path = tmp_path / "sample.osm"
    path.write_text(OSM_XML)
    ways = osm.read_ways(path, bbox=(1.5, 43.5, 1.6, 43.6))
    assert [w.id for w in ways] == [10, 11]
    greenway, road = ways
    assert greenway.road_class is RoadClass.PATH
    assert road.road_class is RoadClass.MAJOR
    assert greenway.node_ids == (1, 2, 3)
    assert (greenway.surface, greenway.lit, greenway.name) == ("asphalt", "yes", "Voie verte")
    # Lambert-93 coordinates, ~800 m between nodes 1 and 3 at this latitude.
    assert greenway.coords[0, 0] == pytest.approx(581_140, abs=200)
    assert greenway.coords[0, 1] == pytest.approx(6_271_090, abs=200)
    length = float(np.hypot(*(greenway.coords[-1] - greenway.coords[0])))
    assert length == pytest.approx(806, rel=0.01)


def test_read_ways_without_bbox_keeps_everything_relevant(tmp_path: Path) -> None:
    path = tmp_path / "sample.osm"
    path.write_text(OSM_XML)
    assert [w.id for w in osm.read_ways(path)] == [10, 11, 13]
