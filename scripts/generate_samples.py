"""Generate a real Shapefile ZIP without committing binary sample data."""

import argparse
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon


def generate_zip(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    polygon = Polygon([(500000, 1500000), (500100, 1500000), (500100, 1500100), (500000, 1500100)])
    with tempfile.TemporaryDirectory(prefix="sample-shapefile-") as directory:
        path = Path(directory)
        frame = gpd.GeoDataFrame({"name": ["Parcel A"]}, geometry=[polygon], crs="EPSG:32644")
        frame.to_file(path / "survey.shp", engine="pyogrio", driver="ESRI Shapefile")
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for component in sorted(path.iterdir()):
                archive.write(component, component.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/sample-shapefile.zip"))
    arguments = parser.parse_args()
    generate_zip(arguments.output)
    print(f"Created {arguments.output}")
