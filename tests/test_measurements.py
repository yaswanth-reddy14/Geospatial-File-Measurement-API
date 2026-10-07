from uuid import uuid4

import pytest
from pyproj import CRS, Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from app.models.file import Dataset, SourceFeature
from app.services.measurement_service import measure_dataset
from tests.helpers import metric_polygon, to_wgs84


def result_for(geometries, crs=32644):
    return measure_dataset(
        Dataset(
            CRS.from_user_input(crs),
            [
                SourceFeature(geometry, {"index": index})
                for index, geometry in enumerate(geometries)
            ],
        ),
        uuid4(),
    )


@pytest.mark.parametrize(
    "geometry,kind,value,unit",
    [
        (metric_polygon(), "area", 10000, "square_meters"),
        (LineString([(500000, 1500000), (500003, 1500004)]), "length", 5, "meters"),
        (
            MultiPolygon(
                [
                    metric_polygon(),
                    Polygon(
                        [(501000, 1500000), (501010, 1500000), (501010, 1500010), (501000, 1500010)]
                    ),
                ]
            ),
            "area",
            10100,
            "square_meters",
        ),
        (
            MultiLineString(
                [[(500000, 1500000), (500003, 1500004)], [(500000, 1500100), (500000, 1500107)]]
            ),
            "length",
            12,
            "meters",
        ),
    ],
)
def test_projected_measurements(geometry, kind, value, unit):
    result = result_for([geometry])
    measurement = result.features[0].measurement
    assert measurement.type == kind
    assert measurement.value == pytest.approx(value, abs=1e-8)
    assert measurement.unit == unit
    assert result.measurement_crs == "EPSG:32644"


def test_polygon_holes_are_subtracted():
    shell = metric_polygon().exterior.coords
    hole = [(500010, 1500010), (500020, 1500010), (500020, 1500020), (500010, 1500020)]
    assert result_for([Polygon(shell, [hole])]).features[0].measurement.value == 9900


@pytest.mark.parametrize("geometry", [Point(500000, 1500000), MultiPoint([(500000, 1500000)])])
def test_points_have_no_measurement(geometry):
    feature = result_for([geometry]).features[0]
    assert feature.measurement is None
    assert feature.measurement_error is None
    assert feature.geometry is not None


@pytest.mark.parametrize("geometry", [None, Point(), LineString(), Polygon(), GeometryCollection()])
def test_null_and_empty_geometries_are_json_safe(geometry):
    result = result_for([geometry])
    assert result.features[0].geometry is None
    assert result.features[0].measurement is None
    assert result.features[0].measurement_error == "Geometry is null or empty."
    assert "NaN" not in result.model_dump_json()


def test_unsupported_and_invalid_do_not_break_other_features():
    collection = GeometryCollection([Point(500000, 1500000), metric_polygon()])
    bowtie = Polygon(
        [
            (500000, 1500000),
            (500100, 1500100),
            (500100, 1500000),
            (500000, 1500100),
            (500000, 1500000),
        ]
    )
    result = result_for([collection, bowtie, metric_polygon()])
    assert "GeometryCollection" in result.features[0].measurement_error
    assert result.features[0].geometry["type"] == "GeometryCollection"
    assert "Invalid geometry" in result.features[1].measurement_error
    assert result.features[1].geometry is not None
    assert result.features[2].measurement.value == 10000


def test_geographic_area_and_length_match_known_projected_values():
    line = LineString([(500000, 1500000), (500100, 1500000)])
    result = result_for([to_wgs84(metric_polygon()), to_wgs84(line)], 4326)
    assert result.measurement_crs == "EPSG:32644"
    assert result.features[0].measurement.value == pytest.approx(10000, abs=0.001)
    assert result.features[1].measurement.value == pytest.approx(100, abs=0.001)
    assert result.features[0].geometry["coordinates"][0][0][0] == pytest.approx(81)


def test_geographic_measurements_also_agree_with_independent_geodesic_reference():
    polygon = Polygon([(80, 13), (80.001, 13), (80.001, 13.001), (80, 13.001)])
    line = LineString([(80, 13), (80.001, 13)])
    result = result_for([polygon, line], 4326)
    geod = Geod(ellps="WGS84")
    area, _ = geod.geometry_area_perimeter(polygon)
    assert result.features[0].measurement.value == pytest.approx(abs(area), rel=0.002)
    assert result.features[1].measurement.value == pytest.approx(
        geod.geometry_length(line), rel=0.002
    )


def test_dateline_and_wide_datasets_get_explicit_errors():
    crossing = LineString([(179.9, 10), (-179.9, 10)])
    result = result_for([crossing], 4326)
    assert result.features[0].measurement is None
    assert "Dateline" in result.features[0].measurement_error
    result = result_for([LineString([(0, 0), (20, 0)])], 4326)
    assert result.measurement_crs is None
    assert "extent exceeds" in result.features[0].measurement_error


def test_altitude_is_preserved_but_length_is_planar():
    line = LineString([(500000, 1500000, 0), (500003, 1500004, 100)])
    feature = result_for([line]).features[0]
    assert feature.measurement.value == 5
    assert feature.geometry["coordinates"][1][2] == 100
