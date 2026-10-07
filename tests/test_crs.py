import pytest
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform

from app.core.exceptions import CRSProcessingError
from app.services.crs_service import is_metric_projected, select_measurement_crs, utm_crs
from tests.test_measurements import result_for


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [
        (80, 13, 32644),
        (18, -33, 32734),
        (-180, 0, 32601),
        (180, 0, 32660),
        (0, 0, 32631),
        (6, 60, 32632),
        (15, 78, 32633),
        (30, 78, 32635),
        (40, 78, 32637),
        (10, 85, 32661),
        (10, -85, 32761),
    ],
)
def test_utm_selection(lon, lat, epsg):
    assert utm_crs(lon, lat).to_epsg() == epsg


@pytest.mark.parametrize("lon,lat", [(181, 0), (0, 91), (float("nan"), 0)])
def test_invalid_crs_location(lon, lat):
    with pytest.raises(CRSProcessingError):
        utm_crs(lon, lat)


def test_projected_units_and_web_mercator():
    assert is_metric_projected(CRS.from_epsg(32644))
    assert not is_metric_projected(CRS.from_epsg(4326))
    assert not is_metric_projected(CRS.from_epsg(2263))  # US survey feet
    assert not is_metric_projected(CRS.from_epsg(3857))
    source_line = LineString([(-73.99, 40.75), (-73.989, 40.75)])
    geographic_result = result_for([source_line], 4326)
    for epsg in (2263, 3857):
        projected = transform(
            Transformer.from_crs(4326, epsg, always_xy=True).transform, source_line
        )
        measured = result_for([projected], epsg)
        assert measured.measurement_crs == "EPSG:32618"
        assert measured.features[0].measurement.value == pytest.approx(
            geographic_result.features[0].measurement.value, rel=1e-6
        )


def test_empty_geographic_dataset_has_no_selected_crs():
    assert select_measurement_crs(CRS.from_epsg(4326), []) is None


def test_dateline_points_select_a_nearby_zone():
    crs = select_measurement_crs(CRS.from_epsg(4326), [Point(179.8, 10), Point(-179.8, 10)])
    assert crs.to_epsg() in {32601, 32660}


def test_southern_geographic_length():
    result = result_for([LineString([(18, -33), (18.001, -33)])], 4326)
    assert result.measurement_crs == "EPSG:32734"
    assert 90 < result.features[0].measurement.value < 95
