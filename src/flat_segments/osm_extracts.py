"""Cut a national OSM extract into one extract per département (phase 2.4).

The production workflow downloads France once and gives each département job
only its own extract. The cut uses the same area as the département pipeline
(outline grown by ``BORDER_MARGIN_M``, plus a small safety margin) and the
``complete_ways`` strategy of osmium: a way with one node in the area is kept
whole, as ``osm.read_ways`` expects. Running the pipeline on the cut extract
or on a regional one therefore gives the same ways.

osmium keeps node id sets per extract, sized by the largest node id (about
3.7 GB per extract with the OSM ids of 2026, over 14 billion): eight extracts
at once exhaust a 16 GB runner. The national file is therefore first
renumbered (:func:`renumber_nodes`): node ids then run from 1, and a whole
batch of 8 départements takes less than 2 GB. Only node ids change: they are
internal to the network (shared nodes), while the published way ids stay the
OSM ones. The départements are then cut in batches, each batch being one pass
over the national file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Final

import shapely
from shapely.geometry import mapping

from flat_segments.departments import BORDER_MARGIN_M, Department, transform_geometry
from flat_segments.params import WEB_CRS, WORK_CRS

#: Margin of the cut around the outline: the pipeline margin, plus a safety margin.
EXTRACT_MARGIN_M: Final = BORDER_MARGIN_M + 200.0
#: Simplification of the cut polygon, in metres (well within the safety margin).
SIMPLIFY_M: Final = 50.0
#: Départements cut in one pass over the national file.
DEFAULT_BATCH_SIZE: Final = 12


class OsmiumError(RuntimeError):
    """osmium is missing or failed."""


def osmium_available() -> bool:
    """Whether the ``osmium`` command (osmium-tool) is on the PATH."""
    return shutil.which("osmium") is not None


def extract_name(code: str) -> str:
    """File name of the extract of a département."""
    return f"{code}.osm.pbf"


def extract_area(department: Department, margin_m: float = EXTRACT_MARGIN_M) -> Any:
    """Area of the cut in WGS84: the outline grown by ``margin_m``, simplified."""
    area = department.work_area_l93(margin_m).simplify(SIMPLIFY_M)
    return transform_geometry(area, WORK_CRS, WEB_CRS)


def batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Consecutive slices of at most ``size`` items."""
    if size < 1:
        raise ValueError("batch size must be at least 1")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def osmium_config(
    departments: Sequence[Department], out_dir: Path, polygons_dir: Path
) -> dict[str, Any]:
    """Content of the osmium ``extract --config`` file.

    Writes one GeoJSON polygon per département in ``polygons_dir``.
    """
    extracts = []
    for department in departments:
        polygon = polygons_dir / f"{department.code}.geojson"
        feature = {
            "type": "Feature",
            "properties": {"code": department.code},
            "geometry": mapping(shapely.set_precision(extract_area(department), 1e-6)),
        }
        polygon.write_text(json.dumps(feature), encoding="utf-8")
        extracts.append(
            {
                "output": extract_name(department.code),
                "polygon": {"file_name": str(polygon), "file_type": "geojson"},
            }
        )
    return {"directory": str(out_dir), "extracts": extracts}


def renumber_nodes(pbf: Path, out: Path) -> Path:
    """Copy ``pbf`` with its nodes numbered from 1 (ways and relations unchanged).

    The new ids follow the order of the old ones (the file is sorted by id),
    so that the network built from it is the same.

    Raises:
        OsmiumError: If osmium is missing or fails.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    _run_osmium(
        [
            "osmium",
            "renumber",
            "--object-type=node",
            "--overwrite",
            "--no-progress",
            f"--output={out}",
            str(pbf),
        ]
    )
    return out


def cut_extracts(
    pbf: Path,
    departments: Sequence[Department],
    out_dir: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch: Callable[[list[Path]], None] | None = None,
) -> list[Path]:
    """Write ``out_dir/CODE.osm.pbf`` for each département.

    Args:
        pbf: National (or regional) OSM extract.
        departments: Départements to cut.
        out_dir: Folder of the extracts.
        batch_size: Départements cut per pass over ``pbf``.
        on_batch: Called with the files of each batch once written (to upload
            them, then free the disk, for instance).

    Raises:
        OsmiumError: If osmium is missing or fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for batch in batches(departments, batch_size):
        with tempfile.TemporaryDirectory(prefix="flat-segments-osm-") as tmp:
            work = Path(tmp)
            config = work / "config.json"
            config.write_text(json.dumps(osmium_config(batch, out_dir, work)), encoding="utf-8")
            _run_osmium(
                [
                    "osmium",
                    "extract",
                    f"--config={config}",
                    "--strategy=complete_ways",
                    "--overwrite",
                    "--no-progress",
                    str(pbf),
                ]
            )
        files = [out_dir / extract_name(d.code) for d in batch]
        written.extend(files)
        if on_batch is not None:
            on_batch(files)
    return written


def _run_osmium(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise OsmiumError("osmium not found: install osmium-tool") from error
    except subprocess.CalledProcessError as error:
        raise OsmiumError(f"osmium failed: {error.stderr.strip()[-500:]}") from error
