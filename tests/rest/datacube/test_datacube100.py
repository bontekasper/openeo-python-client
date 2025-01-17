"""

Unit tests specifically for 1.0.0-style DataCube

"""
import pathlib
import re
import sys
import textwrap

import pytest
import requests
import shapely.geometry

import openeo.metadata
from openeo import UDF
from openeo.api.process import Parameter
from openeo.internal.graph_building import PGNode
from openeo.internal.process_graph_visitor import ProcessGraphVisitException
from openeo.rest import OpenEoClientException
from openeo.rest.connection import Connection
from openeo.rest.datacube import THIS, DataCube, ProcessBuilder
from .conftest import API_URL
from ... import load_json_resource

basic_geometry_types = [
    (
        shapely.geometry.box(0, 0, 1, 1),
        {"type": "Polygon", "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)},
    ),
    (
        {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
        {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
    ),
    (
        shapely.geometry.MultiPolygon([shapely.geometry.box(0, 0, 1, 1)]),
        {"type": "MultiPolygon", "coordinates": [(((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)]},
    ),
    (
        shapely.geometry.GeometryCollection([shapely.geometry.box(0, 0, 1, 1)]),
        {"type": "GeometryCollection", "geometries": [
            {"type": "Polygon", "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)}
        ]},
    ),
    (
        {
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
        },
        {
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
        },
    ),
]


def _get_leaf_node(cube: DataCube) -> dict:
    """Get leaf node (node with result=True), supporting old and new style of graph building."""
    flat_graph = cube.flat_graph()
    node, = [n for n in flat_graph.values() if n.get("result")]
    return node


def test_datacube_graph(con100):
    s2cube = con100.load_collection("S2")
    with pytest.warns(DeprecationWarning, match=re.escape("Use `DataCube.flat_graph()` instead.")):
        actual = s2cube.graph
    assert actual == {'loadcollection1': {
        'process_id': 'load_collection',
        'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        'result': True
    }}


def test_datacube_flat_graph(con100):
    s2cube = con100.load_collection("S2")
    assert s2cube.flat_graph() == {'loadcollection1': {
        'process_id': 'load_collection',
        'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        'result': True
    }}


def test_datacube_legacy_flatten(con100):
    s2cube = con100.load_collection("S2")
    with pytest.warns(DeprecationWarning, match="Call to deprecated method `flatten`, use `flat_graph` instead."):
        assert s2cube.flatten() == {'loadcollection1': {
            'process_id': 'load_collection',
            'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
            'result': True
        }}


@pytest.mark.parametrize(["kwargs", "expected"], [
    ({"west": 3, "south": 51, "east": 4, "north": 52}, {"west": 3, "south": 51, "east": 4, "north": 52}),
    (
            {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326},
            {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}
    ),
    ({"bbox": [3, 51, 4, 52]}, {"west": 3, "south": 51, "east": 4, "north": 52}),
    ({"bbox": (3, 51, 4, 52)}, {"west": 3, "south": 51, "east": 4, "north": 52}),
    ({"bbox": shapely.geometry.box(3, 51, 4, 52)}, {"west": 3, "south": 51, "east": 4, "north": 52}),
    ({"bbox": {"west": 3, "south": 51, "east": 4, "north": 52}}, {"west": 3, "south": 51, "east": 4, "north": 52}),
    (
            {"bbox": {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}},
            {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}
    ),

])
def test_filter_bbox_kwargs(con100: Connection, kwargs, expected):
    cube = con100.load_collection("S2").filter_bbox(**kwargs)
    node = _get_leaf_node(cube)
    assert node["process_id"] == "filter_bbox"
    assert node["arguments"]["extent"] == expected


def test_filter_bbox_parameter(con100: Connection):
    expected = {
        "process_id": "filter_bbox",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "extent": {"from_parameter": "my_bbox"}
        },
        "result": True
    }
    bbox_param = Parameter(name="my_bbox", schema={"type": "object"})

    cube = con100.load_collection("S2").filter_bbox(bbox_param)
    assert _get_leaf_node(cube) == expected

    cube = con100.load_collection("S2").filter_bbox(bbox=bbox_param)
    assert _get_leaf_node(cube) == expected


@pytest.mark.parametrize(["args", "expected"], [
    ((3, 4, 52, 51,), {"west": 3, "south": 51, "east": 4, "north": 52}),
    ((3, 4, 52, 51, 4326,), {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}),
    (([3, 51, 4, 52],), {"west": 3, "south": 51, "east": 4, "north": 52}),
    (((3, 51, 4, 52),), {"west": 3, "south": 51, "east": 4, "north": 52}),
    (({"west": 3, "south": 51, "east": 4, "north": 52},), {"west": 3, "south": 51, "east": 4, "north": 52}),
    (
            ({"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326},),
            {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}
    ),
    ((shapely.geometry.box(3, 51, 4, 52),), {"west": 3, "south": 51, "east": 4, "north": 52}),

])
def test_filter_bbox_positional_args(con100: Connection, args, expected):
    cube = con100.load_collection("S2").filter_bbox(*args)
    node = _get_leaf_node(cube)
    assert node["process_id"] == "filter_bbox"
    assert node["arguments"]["extent"] == expected


def test_filter_bbox_legacy_positional_args(con100: Connection):
    with pytest.warns(UserWarning, match="Deprecated argument order"):
        cube = con100.load_collection("S2").filter_bbox(3, 4, 52, 51)
    node = _get_leaf_node(cube)
    assert node["process_id"] == "filter_bbox"
    assert node["arguments"]["extent"] == {"west": 3, "south": 51, "east": 4, "north": 52}


@pytest.mark.parametrize(["args", "kwargs", "expected"], [
    ((3, 4, 52, 51,), {"crs": 4326}, {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}),
    (([3, 51, 4, 52],), {"crs": 4326}, {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}),
    (((3, 51, 4, 52),), {"crs": 4326}, {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}),
    (
            ({"west": 3, "south": 51, "east": 4, "north": 52},),
            {"crs": 4326},
            {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}
    ),
    (
            (shapely.geometry.box(3, 51, 4, 52),),
            {"crs": 4326},
            {"west": 3, "south": 51, "east": 4, "north": 52, "crs": 4326}
    ),
])
def test_filter_bbox_args_and_kwargs(con100: Connection, args, kwargs, expected):
    cube = con100.load_collection("S2").filter_bbox(*args, **kwargs)
    node = _get_leaf_node(cube)
    assert node["process_id"] == "filter_bbox"
    assert node["arguments"]["extent"] == expected


@pytest.mark.parametrize(["args", "kwargs", "expected"], [
    ((3, 4, 52, 51,), {"west": 2}, "Don't mix positional arguments with keyword arguments"),
    (([3, 51, 4, 52],), {"west": 2}, "Don't mix positional arguments with keyword arguments"),
    ((), {"west": 2, "bbox": [3, 51, 4, 52]}, "Don't mix `bbox` with `west`/`south`/`east`/`north` keyword arguments"),
])
def test_filter_bbox_args_and_kwargs_conflict(con100: Connection, args, kwargs, expected):
    with pytest.raises(ValueError, match=expected):
        con100.load_collection("S2").filter_bbox(*args, **kwargs)


def test_filter_spatial(con100: Connection, recwarn):
    img = con100.load_collection("S2")
    polygon = shapely.geometry.box(0, 0, 1, 1)
    masked = img.filter_spatial(geometries=polygon)
    assert sorted(masked.flat_graph().keys()) == ["filterspatial1", "loadcollection1"]
    assert masked.flat_graph()["filterspatial1"] == {
        "process_id": "filter_spatial",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "geometries": {
                "type": "Polygon",
                "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),),
            }
        },
        "result": True
    }

def test_aggregate_spatial_basic(con100: Connection):
    img = con100.load_collection("S2")
    polygon = shapely.geometry.box(0, 0, 1, 1)
    masked = img.aggregate_spatial(geometries=polygon, reducer="mean")
    assert sorted(masked.flat_graph().keys()) == ["aggregatespatial1", "loadcollection1"]
    assert masked.flat_graph()["aggregatespatial1"] == {
        "process_id": "aggregate_spatial",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "geometries": {
                "type": "Polygon",
                "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),),
            },
            "reducer": {"process_graph": {
                "mean1": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": True}
            }}
        },
        "result": True
    }


@pytest.mark.parametrize(["polygon", "expected_geometries"], [
    (
            shapely.geometry.box(0, 0, 1, 1),
            {"type": "Polygon", "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)},
    ),
    (
            {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
            {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
    ),
    (
            shapely.geometry.MultiPolygon([shapely.geometry.box(0, 0, 1, 1)]),
            {"type": "MultiPolygon", "coordinates": [(((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)]},
    ),
    (
            shapely.geometry.GeometryCollection([shapely.geometry.box(0, 0, 1, 1)]),
            {"type": "GeometryCollection", "geometries": [
                {"type": "Polygon", "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)}
            ]},
    ),
    (
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature", "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
                    },

                ]
            },
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature", "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": (((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)),)},
                    },

                ]
            },
    ),
])
def test_aggregate_spatial_types(con100: Connection, polygon, expected_geometries):
    img = con100.load_collection("S2")
    masked = img.aggregate_spatial(geometries=polygon, reducer="mean")
    assert sorted(masked.flat_graph().keys()) == ["aggregatespatial1", "loadcollection1"]
    assert masked.flat_graph()["aggregatespatial1"] == {
        "process_id": "aggregate_spatial",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "geometries": expected_geometries,
            "reducer": {"process_graph": {
                "mean1": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": True}
            }}
        },
        "result": True
    }


def test_aggregate_spatial_with_crs(con100: Connection, recwarn):
    img = con100.load_collection("S2")
    polygon = shapely.geometry.box(0, 0, 1, 1)
    masked = img.aggregate_spatial(geometries=polygon, reducer="mean", crs="EPSG:32631")
    warnings = [str(w.message) for w in recwarn]
    assert "Geometry with non-Lon-Lat CRS 'EPSG:32631' is only supported by specific back-ends." in warnings
    assert sorted(masked.flat_graph().keys()) == ["aggregatespatial1", "loadcollection1"]
    assert masked.flat_graph()["aggregatespatial1"] == {
        "process_id": "aggregate_spatial",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "geometries": {
                "type": "Polygon",
                "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),),
                "crs": {"properties": {"name": "EPSG:32631"}, "type": "name"},
            },
            "reducer": {"process_graph": {
                "mean1": {"process_id": "mean", "arguments": {"data": {"from_parameter": "data"}}, "result": True}
            }}
        },
        "result": True
    }


def test_aggregate_temporal(con100: Connection):
    img = con100.load_collection("S2").aggregate_temporal_period(period="dekad",reducer=lambda d:d.median(),context={"bla":"bla"})

    graph = img.flat_graph()
    assert graph == {'aggregatetemporalperiod1': {'arguments': {'data': {'from_node': 'loadcollection1'},
                                                                'period': 'dekad',
                                                                'context': {'bla': 'bla'},
                                                                'reducer': {'process_graph': {'median1': {'arguments': {'data': {'from_parameter': 'data'}},
                                                                                                          'process_id': 'median',
                                                                                                          'result': True}}}},
                                                  'process_id': 'aggregate_temporal_period',
                                                  'result': True},
                     'loadcollection1': {'arguments': {'id': 'S2',
                                                       'spatial_extent': None,
                                                       'temporal_extent': None},
                                         'process_id': 'load_collection'}}

def test_mask_polygon_basic(con100: Connection):
    img = con100.load_collection("S2")
    polygon = shapely.geometry.box(0, 0, 1, 1)
    masked = img.mask_polygon(mask=polygon)
    assert sorted(masked.flat_graph().keys()) == ["loadcollection1", "maskpolygon1"]
    assert masked.flat_graph()["maskpolygon1"] == {
        "process_id": "mask_polygon",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "mask": {
                "type": "Polygon",
                "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),),
            }
        },
        "result": True
    }


@pytest.mark.parametrize(["polygon", "expected_mask"], basic_geometry_types)
def test_mask_polygon_types(con100: Connection, polygon, expected_mask):
    img = con100.load_collection("S2")
    masked = img.mask_polygon(mask=polygon)
    assert sorted(masked.flat_graph().keys()) == ["loadcollection1", "maskpolygon1"]
    assert masked.flat_graph()["maskpolygon1"] == {
        "process_id": "mask_polygon",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "mask": expected_mask
        },
        "result": True
    }


def test_mask_polygon_with_crs(con100: Connection, recwarn):
    img = con100.load_collection("S2")
    polygon = shapely.geometry.box(0, 0, 1, 1)
    masked = img.mask_polygon(mask=polygon, srs="EPSG:32631")
    warnings = [str(w.message) for w in recwarn]
    assert "Geometry with non-Lon-Lat CRS 'EPSG:32631' is only supported by specific back-ends." in warnings
    assert sorted(masked.flat_graph().keys()) == ["loadcollection1", "maskpolygon1"]
    assert masked.flat_graph()["maskpolygon1"] == {
        "process_id": "mask_polygon",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "mask": {
                "type": "Polygon", "coordinates": (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),),
                "crs": {"type": "name", "properties": {"name": "EPSG:32631"}},
            },
        },
        "result": True
    }


def test_mask_polygon_parameter(con100: Connection):
    img = con100.load_collection("S2")
    polygon = Parameter(name="shape", schema="object")
    masked = img.mask_polygon(mask=polygon)
    assert sorted(masked.flat_graph().keys()) == ["loadcollection1", "maskpolygon1"]
    assert masked.flat_graph()["maskpolygon1"] == {
        "process_id": "mask_polygon",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "mask": {"from_parameter": "shape"},
        },
        "result": True
    }


def test_mask_polygon_path(con100: Connection):
    img = con100.load_collection("S2")
    masked = img.mask_polygon(mask="path/to/polygon.json")
    assert sorted(masked.flat_graph().keys()) == ["loadcollection1", "maskpolygon1", "readvector1"]
    assert masked.flat_graph()["maskpolygon1"] == {
        "process_id": "mask_polygon",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "mask": {"from_node": "readvector1"},
        },
        "result": True
    }
    assert masked.flat_graph()["readvector1"] == {
        "process_id": "read_vector",
        "arguments": {"filename": "path/to/polygon.json"},
    }


def test_mask_raster(con100: Connection):
    img = con100.load_collection("S2")
    mask = con100.load_collection("MASK")
    masked = img.mask(mask=mask, replacement=102)
    assert masked.flat_graph()["mask1"] == {
        "process_id": "mask",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "mask": {"from_node": "loadcollection2"},
            "replacement": 102
        },
        "result": True
    }


def test_merge_cubes(con100: Connection):
    a = con100.load_collection("S2")
    b = con100.load_collection("MASK")
    c = a.merge(b)
    assert c.flat_graph()["mergecubes1"] == {
        "process_id": "merge_cubes",
        "arguments": {
            "cube1": {"from_node": "loadcollection1"},
            "cube2": {"from_node": "loadcollection2"},
        },
        "result": True
    }


def test_resample_spatial(con100: Connection):
    data = con100.load_collection("S2")
    target = con100.load_collection("MASK")
    im = data.resample_cube_spatial(target,method='spline')
    print(im.flat_graph())
    assert im.flat_graph()["resamplecubespatial1"] == {
        'arguments': {
           'data': {'from_node': 'loadcollection1'},
           'method': 'spline',
           'target': {'from_node': 'loadcollection2'}
        },
        'process_id': 'resample_cube_spatial',
        'result': True}


def test_ndvi_simple(con100: Connection):
    ndvi = con100.load_collection("S2").ndvi()
    assert sorted(ndvi.flat_graph().keys()) == ["loadcollection1", "ndvi1"]
    assert ndvi.flat_graph()["ndvi1"] == {
        "process_id": "ndvi",
        "arguments": {"data": {"from_node": "loadcollection1"}},
        "result": True,
    }
    assert not ndvi.metadata.has_band_dimension()


def test_ndvi_args(con100: Connection):
    ndvi = con100.load_collection("S2").ndvi(nir="nirr", red="rred", target_band="ndvii")
    assert sorted(ndvi.flat_graph().keys()) == ["loadcollection1", "ndvi1"]
    assert ndvi.flat_graph()["ndvi1"] == {
        "process_id": "ndvi",
        "arguments": {"data": {"from_node": "loadcollection1"}, "nir": "nirr", "red": "rred", "target_band": "ndvii"},
        "result": True,
    }
    assert ndvi.metadata.has_band_dimension()
    assert ndvi.metadata.band_dimension.band_names == ["B02", "B03", "B04", "B08", "ndvii"]


def test_rename_dimension(con100):
    s2 = con100.load_collection("S2")
    x = s2.rename_dimension(source="bands", target="ThisIsNotTheBandsDimension")
    assert x.flat_graph() == {
        'loadcollection1': {
            'arguments': {
                'id': 'S2',
                'spatial_extent': None,
                'temporal_extent': None
            },
            'process_id': 'load_collection'
        },
        'renamedimension1': {
            'arguments': {
                'data': {'from_node': 'loadcollection1'},
                'source': 'bands',
                'target': 'ThisIsNotTheBandsDimension'
            },
            'process_id': 'rename_dimension',
            'result': True
        }
    }


def test_reduce_dimension(con100):
    s2 = con100.load_collection("S2")
    x = s2.reduce_dimension(dimension="bands", reducer="mean")
    assert x.flat_graph() == {
        'loadcollection1': {
            'process_id': 'load_collection',
            'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        },
        'reducedimension1': {
            'process_id': 'reduce_dimension',
            'arguments': {
                'data': {'from_node': 'loadcollection1'},
                'dimension': 'bands',
                'reducer': {'process_graph': {
                    'mean1': {
                        'process_id': 'mean',
                        'arguments': {'data': {'from_parameter': 'data'}},
                        'result': True
                    }
                }}
            },
            'result': True
        }}


def test_reduce_dimension_binary(con100):
    s2 = con100.load_collection("S2")
    reducer = PGNode(
        process_id="add",
        arguments={"x": {"from_parameter": "x"}, "y": {"from_parameter": "y"}},
    )
    x = s2.reduce_dimension(dimension="bands", reducer=reducer, process_id="reduce_dimension_binary")
    assert x.flat_graph() == {
        'loadcollection1': {
            'process_id': 'load_collection',
            'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        },
        'reducedimensionbinary1': {
            'process_id': 'reduce_dimension_binary',
            'arguments': {
                'data': {'from_node': 'loadcollection1'},
                'dimension': 'bands',
                'reducer': {'process_graph': {
                    'add1': {
                        'process_id': 'add',
                        'arguments': {'x': {'from_parameter': 'x'}, 'y': {'from_parameter': 'y'}},
                        'result': True
                    }
                }}
            },
            'result': True
        }}


def test_reduce_dimension_name(con100, requests_mock):
    requests_mock.get(API_URL + "/collections/S22", json={
        "cube:dimensions": {
            "color": {"type": "bands", "values": ["cyan", "magenta", "yellow", "black"]},
            "alpha": {"type": "spatial"},
            "date": {"type": "temporal"}
        }
    })
    s22 = con100.load_collection("S22")

    for dim in ["color", "alpha", "date"]:
        cube = s22.reduce_dimension(dimension=dim, reducer="sum")
        assert cube.flat_graph()["reducedimension1"] == {
            "process_id": "reduce_dimension",
            "arguments": {
                'data': {'from_node': 'loadcollection1'},
                'dimension': dim,
                'reducer': {'process_graph': {
                    'sum1': {
                        'process_id': 'sum',
                        'arguments': {'data': {'from_parameter': 'data'}},
                        'result': True
                    }
                }}
            },
            'result': True
        }

    with pytest.raises(ValueError, match="Invalid dimension 'wut'"):
        s22.reduce_dimension(dimension="wut", reducer="sum")


def test_chunk_polygon_basic(con100: Connection):
    img = con100.load_collection("S2")
    polygon: shapely.geometry.Polygon = shapely.geometry.box(0, 0, 1, 1)
    process = lambda data: data.run_udf(udf="myfancycode", runtime="Python")
    result = img.chunk_polygon(chunks=polygon, process=process)
    assert sorted(result.flat_graph().keys()) == ['chunkpolygon1', 'loadcollection1']
    assert result.flat_graph()["chunkpolygon1"] == {
        'process_id': 'chunk_polygon',
        'arguments': {
            'chunks': {
                'type': 'Polygon',
                'coordinates': (((1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)),)
            },
            'data': {'from_node': 'loadcollection1'},
            'process': {
                'process_graph': {
                    'runudf1': {
                        'process_id': 'run_udf',
                        'arguments': {'data': {'from_parameter': 'data'}, 'runtime': 'Python', 'udf': 'myfancycode'},
                        'result': True
                    }
                }
            }
        },
        'result': True}


@pytest.mark.parametrize(["polygon", "expected_chunks"], basic_geometry_types)
def test_chunk_polygon_types(con100: Connection, polygon, expected_chunks):
    img = con100.load_collection("S2")
    process = lambda data: data.run_udf(udf="myfancycode", runtime="Python")
    result = img.chunk_polygon(chunks=polygon, process=process)
    assert sorted(result.flat_graph().keys()) == ['chunkpolygon1', 'loadcollection1']
    assert result.flat_graph()["chunkpolygon1"] == {
        'process_id': 'chunk_polygon',
        'arguments': {
            'chunks': expected_chunks,
            'data': {'from_node': 'loadcollection1'},
            'process': {
                'process_graph': {
                    'runudf1': {
                        'process_id': 'run_udf',
                        'arguments': {'data': {'from_parameter': 'data'}, 'runtime': 'Python', 'udf': 'myfancycode'},
                        'result': True
                    }
                }
            }
        },
        'result': True}


def test_chunk_polygon_parameter(con100: Connection):
    img = con100.load_collection("S2")
    polygon = Parameter(name="shape", schema="object")
    process = lambda data: data.run_udf(udf="myfancycode", runtime="Python")
    result = img.chunk_polygon(chunks=polygon, process=process)
    assert sorted(result.flat_graph().keys()) == ['chunkpolygon1', 'loadcollection1']
    assert result.flat_graph()["chunkpolygon1"] == {
        'process_id': 'chunk_polygon',
        'arguments': {
            'chunks': {"from_parameter": "shape"},
            'data': {'from_node': 'loadcollection1'},
            'process': {
                'process_graph': {
                    'runudf1': {
                        'process_id': 'run_udf',
                        'arguments': {'data': {'from_parameter': 'data'}, 'runtime': 'Python', 'udf': 'myfancycode'},
                        'result': True
                    }
                }
            }
        },
        'result': True}


def test_chunk_polygon_path(con100: Connection):
    img = con100.load_collection("S2")
    process = lambda data: data.run_udf(udf="myfancycode", runtime="Python")
    result = img.chunk_polygon(chunks="path/to/polygon.json", process=process)
    assert sorted(result.flat_graph().keys()) == ['chunkpolygon1', 'loadcollection1', 'readvector1']
    assert result.flat_graph()["chunkpolygon1"]['arguments']['chunks'] == {"from_node": "readvector1"}
    assert result.flat_graph()["readvector1"] == {
        "process_id": "read_vector",
        "arguments": {"filename": "path/to/polygon.json"},
    }


def test_metadata_load_collection_100(con100, requests_mock):
    requests_mock.get(API_URL + "/collections/SENTINEL2", json={
        "cube:dimensions": {
            "bands": {"type": "bands", "values": ["B2", "B3"]}
        },
        "summaries": {
            "eo:bands": [
                {"name": "B2", "common_name": "blue"},
                {"name": "B3", "common_name": "green"},
            ]
        }
    })
    im = con100.load_collection('SENTINEL2')
    assert im.metadata.bands == [
        openeo.metadata.Band("B2", "blue", None),
        openeo.metadata.Band("B3", "green", None)
    ]


def test_apply_absolute_pgnode(con100):
    im = con100.load_collection("S2")
    result = im.apply(PGNode(process_id="absolute", arguments={"x": {"from_parameter": "x"}}))
    expected_graph = load_json_resource('data/1.0.0/apply_absolute.json')
    assert result.flat_graph() == expected_graph


def test_load_collection_properties(con100):
    # TODO: put this somewhere and expose it to the user?
    def eq(value, case_sensitive=True) -> PGNode:
        return PGNode(
            process_id="eq",
            arguments={"x": {"from_parameter": "value"}, "y": value, "case_sensitive": case_sensitive}
        )

    def between(min, max) -> PGNode:
        return PGNode(process_id="between", arguments={"x": {"from_parameter": "value"}, "min": min, "max": max})

    im = con100.load_collection(
        "S2",
        spatial_extent={"west": 16.1, "east": 16.6, "north": 48.6, "south": 47.2},
        temporal_extent=["2018-01-01", "2019-01-01"],
        properties={
            "eo:cloud_cover": between(min=0, max=50),
            "platform": eq("Sentinel-2B", case_sensitive=False)
        }
    )

    expected = load_json_resource('data/1.0.0/load_collection_properties.json')
    assert im.flat_graph() == expected


def test_load_collection_properties_process_builder_function(con100):
    from openeo.processes import between, eq
    im = con100.load_collection(
        "S2",
        spatial_extent={"west": 16.1, "east": 16.6, "north": 48.6, "south": 47.2},
        temporal_extent=["2018-01-01", "2019-01-01"],
        properties={
            "eo:cloud_cover": lambda x: between(x=x, min=0, max=50),
            "platform": lambda x: eq(x=x, y="Sentinel-2B", case_sensitive=False)
        }
    )

    expected = load_json_resource('data/1.0.0/load_collection_properties.json')
    assert im.flat_graph() == expected


def test_load_collection_temporalextent_process_builder_function(con100):
    from openeo.processes import date_shift

    im = con100.load_collection(
        "S2",
        temporal_extent=[date_shift(Parameter("start_date"), -2, unit="days").pgnode, "2019-01-01"],

    )

    expected = {'dateshift1': {'arguments': {'date': {'from_parameter': 'start_date'},
                                                     'unit': 'days',
                                                     'value': -2},
                                       'process_id': 'date_shift'},
                        'loadcollection1': {'arguments': {'id': 'S2',
                                                          'spatial_extent': None,
                                                          'temporal_extent': [{'from_node': 'dateshift1'},
                                                                              '2019-01-01']},
                                            'process_id': 'load_collection',
                                            'result': True}}
    assert im.flat_graph() == expected

    assert con100.load_collection(
        "S2",
        temporal_extent=[date_shift(Parameter("start_date"), -2, unit="days"), "2019-01-01"],

    ).flat_graph() == expected



def test_apply_dimension_temporal_cumsum_with_target(con100):
    cumsum = con100.load_collection("S2").apply_dimension('cumsum', dimension="t", target_dimension="MyNewTime")
    actual_graph = cumsum.flat_graph()
    expected_graph = load_json_resource('data/1.0.0/apply_dimension_temporal_cumsum.json')
    expected_graph['applydimension1']['arguments']['target_dimension'] = 'MyNewTime'
    expected_graph['applydimension1']['result'] = True
    del expected_graph['saveresult1']
    assert actual_graph == expected_graph

def test_apply_dimension_modify_bands(con100):
    def update_bands(x:ProcessBuilder):
        b01 =  x.array_element(0)
        b02 = x.array_element(1)
        diff = b01-b02
        return x.array_modify(values=diff, index=0)
    cumsum = con100.load_collection("S2").apply_dimension(process=update_bands, dimension="bands")
    actual_graph = cumsum.flat_graph()

    assert actual_graph ==  {'applydimension1': {'arguments': {'data': {'from_node': 'loadcollection1'},
                                                               'dimension': 'bands',
                                                               'process': {'process_graph': {'arrayelement1': {'arguments': {'data': {'from_parameter': 'data'},
                                                                                                                             'index': 0},
                                                                                                               'process_id': 'array_element'},
                                                                                             'arrayelement2': {'arguments': {'data': {'from_parameter': 'data'},
                                                                                                                             'index': 1},
                                                                                                               'process_id': 'array_element'},
                                                                                             'arraymodify1': {'arguments': {'data': {'from_parameter': 'data'},
                                                                                                                            'index': 0,
                                                                                                                            'values': {'from_node': 'subtract1'}},
                                                                                                              'process_id': 'array_modify',
                                                                                                              'result': True},
                                                                                             'subtract1': {'arguments': {'x': {'from_node': 'arrayelement1'},
                                                                                                                         'y': {'from_node': 'arrayelement2'}},
                                                                                                           'process_id': 'subtract'}}}},
                                                 'process_id': 'apply_dimension',
                                                 'result': True},
                             'loadcollection1': {'arguments': {'id': 'S2',
                                                               'spatial_extent': None,
                                                               'temporal_extent': None},
                                                 'process_id': 'load_collection'}}


def test_apply_neighborhood_udf(con100):
    collection = con100.load_collection("S2")
    neighbors = collection.apply_neighborhood(size=[
        {'dimension': 'x', 'value': 128, 'unit': 'px'},
        {'dimension': 'y', 'value': 128, 'unit': 'px'}
    ], overlap=[
        {'dimension': 't', 'value': 'P10d'},
    ],process= lambda data:data.run_udf(udf="myfancycode", runtime="Python"))
    actual_graph = neighbors.flat_graph()['applyneighborhood1']
    assert actual_graph == {'arguments': {'data': {'from_node': 'loadcollection1'},
                                          'overlap': [{'dimension': 't', 'value': 'P10d'}],
                                          'process': {'process_graph': {'runudf1': {'arguments': {'udf': 'myfancycode',
                                                                                                  'data': {'from_parameter': 'data'},
                                                                                                  'runtime': 'Python'},
                                                                                    'process_id': 'run_udf',
                                                                                    'result': True}}},
                                          'size': [{'dimension': 'x', 'unit': 'px', 'value': 128},
                                                   {'dimension': 'y', 'unit': 'px', 'value': 128}]},
                            'process_id': 'apply_neighborhood',
                            'result': True}


def test_filter_spatial_callback(con100):
    """
    Experiment test showing how to introduce a callback for preprocessing process arguments
    https://github.com/Open-EO/openeo-processes/issues/156
    @param con100:
    @return:
    """
    collection = con100.load_collection("S2")

    feature_collection = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [125.6, 10.1]
                }
            }]
        }
    udf_process = UDF("def transform_point_into_bbox(data:UdfData): blabla","Python",data=feature_collection)


    filtered_collection = collection.process("filter_spatial", {
        "data": THIS,
        "geometries": udf_process
    })

    assert filtered_collection.flat_graph() == {
        'filterspatial1': {
            'arguments': {
                'data': {'from_node': 'loadcollection1'},
                'geometries': {'from_node': 'runudf1'}
            },
            'process_id': 'filter_spatial',
            'result': True
        },
        'loadcollection1': {
            'arguments': {
                'id': 'S2',
                'spatial_extent': None,
                'temporal_extent': None
            },
            'process_id': 'load_collection'
        },
        'runudf1': {
            'arguments': {
                'data': {
                    'features': [{'geometry': {'coordinates': [125.6, 10.1], 'type': 'Point'}, 'type': 'Feature'}],
                    'type': 'FeatureCollection'
                },
                'runtime': 'Python',
                'udf': 'def transform_point_into_bbox(data:UdfData): blabla'
            },
            'process_id': 'run_udf'}
    }


def test_custom_process_kwargs_datacube(con100: Connection):
    img = con100.load_collection("S2")
    res = img.process(process_id="foo", data=img, bar=123)
    expected = load_json_resource('data/1.0.0/process_foo.json')
    assert res.flat_graph() == expected


def test_custom_process_kwargs_datacube_pg(con100: Connection):
    img = con100.load_collection("S2")
    res = img.process(process_id="foo", data=img._pg, bar=123)
    expected = load_json_resource('data/1.0.0/process_foo.json')
    assert res.flat_graph() == expected


def test_custom_process_kwargs_this(con100: Connection):
    res = con100.load_collection("S2").process(process_id="foo", data=THIS, bar=123)
    expected = load_json_resource('data/1.0.0/process_foo.json')
    assert res.flat_graph() == expected


def test_custom_process_kwargs_namespaced(con100: Connection):
    res = con100.load_collection("S2").process(process_id="foo", data=THIS, bar=123, namespace="bar")
    expected = load_json_resource('data/1.0.0/process_foo_namespaced.json')
    assert res.flat_graph() == expected


def test_custom_process_arguments_datacube(con100: Connection):
    img = con100.load_collection("S2")
    res = img.process(process_id="foo", arguments={"data": img, "bar": 123})
    expected = load_json_resource('data/1.0.0/process_foo.json')
    assert res.flat_graph() == expected


def test_custom_process_arguments_datacube_pg(con100: Connection):
    img = con100.load_collection("S2")
    res = img.process(process_id="foo", arguments={"data": img._pg, "bar": 123})
    expected = load_json_resource('data/1.0.0/process_foo.json')
    assert res.flat_graph() == expected


def test_custom_process_arguments_this(con100: Connection):
    res = con100.load_collection("S2").process(process_id="foo", arguments={"data": THIS, "bar": 123})
    expected = load_json_resource('data/1.0.0/process_foo.json')
    assert res.flat_graph() == expected


def test_custom_process_arguments_namespacd(con100: Connection):
    res = con100.load_collection("S2").process(process_id="foo", arguments={"data": THIS, "bar": 123}, namespace="bar")
    expected = load_json_resource('data/1.0.0/process_foo_namespaced.json')
    assert res.flat_graph() == expected


def test_save_user_defined_process(con100, requests_mock):
    requests_mock.get(API_URL + "/processes", json={"processes": [{"id": "add"}]})

    expected_body = load_json_resource("data/1.0.0/save_user_defined_process.json")

    def check_body(request):
        body = request.json()
        assert body['process_graph'] == expected_body['process_graph']
        assert not body.get('public', False)
        return True

    adapter = requests_mock.put(API_URL + "/process_graphs/my_udp", additional_matcher=check_body)

    collection = con100.load_collection("S2") \
        .filter_bbox(west=16.1, east=16.6, north=48.6, south=47.2) \
        .filter_temporal(start_date="2018-01-01", end_date="2019-01-01")

    collection.save_user_defined_process(user_defined_process_id='my_udp')

    assert adapter.called


def test_save_user_defined_process_public(con100, requests_mock):
    requests_mock.get(API_URL + "/processes", json={"processes": [{"id": "add"}]})

    expected_body = load_json_resource("data/1.0.0/save_user_defined_process.json")

    def check_body(request):
        body = request.json()
        assert body['process_graph'] == expected_body['process_graph']
        assert body['public']
        return True

    adapter = requests_mock.put(API_URL + "/process_graphs/my_udp", additional_matcher=check_body)

    collection = con100.load_collection("S2") \
        .filter_bbox(west=16.1, east=16.6, north=48.6, south=47.2) \
        .filter_temporal(start_date="2018-01-01", end_date="2019-01-01")

    collection.save_user_defined_process(user_defined_process_id='my_udp', public=True)

    assert adapter.called


def test_save_result_format(con100, requests_mock):
    requests_mock.get(API_URL + "/file_formats", json={
        "output": {
            "GTiff": {"gis_data_types": ["raster"]},
            "PNG": {"gis_data_types": ["raster"]},
        }
    })

    cube = con100.load_collection("S2")
    with pytest.raises(ValueError):
        cube.save_result(format="hdmi")
    cube.save_result(format="GTiff")
    cube.save_result(format="gtIFF")
    cube.save_result(format="pNg")


@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires 'insertion ordered' dicts from python3.6 or higher")
def test_to_json(con100):
    ndvi = con100.load_collection("S2").ndvi()
    expected = textwrap.dedent('''\
      {
        "process_graph": {
          "loadcollection1": {
            "process_id": "load_collection",
            "arguments": {
              "id": "S2",
              "spatial_extent": null,
              "temporal_extent": null
            }
          },
          "ndvi1": {
            "process_id": "ndvi",
            "arguments": {
              "data": {
                "from_node": "loadcollection1"
              }
            },
            "result": true
          }
        }
      }''')
    assert ndvi.to_json() == expected


@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires 'insertion ordered' dicts from python3.6 or higher")
def test_to_json_compact(con100):
    ndvi = con100.load_collection("S2").ndvi()
    expected = '{"process_graph": {"loadcollection1": {"process_id": "load_collection", "arguments": {"id": "S2", "spatial_extent": null, "temporal_extent": null}}, "ndvi1": {"process_id": "ndvi", "arguments": {"data": {"from_node": "loadcollection1"}}, "result": true}}}'
    assert ndvi.to_json(indent=None) == expected
    expected = '{"process_graph":{"loadcollection1":{"process_id":"load_collection","arguments":{"id":"S2","spatial_extent":null,"temporal_extent":null}},"ndvi1":{"process_id":"ndvi","arguments":{"data":{"from_node":"loadcollection1"}},"result":true}}}'
    assert ndvi.to_json(indent=None, separators=(',', ':')) == expected


def test_sar_backscatter_defaults(con100):
    cube = con100.load_collection("S2").sar_backscatter()
    assert _get_leaf_node(cube) == {
        "process_id": "sar_backscatter",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "coefficient": "gamma0-terrain", "elevation_model": None,
            "mask": False, "contributing_area": False, "local_incidence_angle": False,
            "ellipsoid_incidence_angle": False, "noise_removal": True
        },
        "result": True
    }


def test_sar_backscatter_custom(con100):
    cube = con100.load_collection("S2")
    cube = cube.sar_backscatter(coefficient="sigma0-ellipsoid", elevation_model="mapzen", options={"speed": "warp42"})
    assert _get_leaf_node(cube) == {
        "process_id": "sar_backscatter",
        "arguments": {
            "data": {"from_node": "loadcollection1"},
            "coefficient": "sigma0-ellipsoid", "elevation_model": "mapzen",
            "mask": False, "contributing_area": False, "local_incidence_angle": False,
            "ellipsoid_incidence_angle": False, "noise_removal": True, "options": {"speed": "warp42"}
        },
        "result": True
    }


def test_sar_backscatter_coefficient_none(con100):
    cube = con100.load_collection("S2")
    cube = cube.sar_backscatter(coefficient=None)
    assert _get_leaf_node(cube)["arguments"]["coefficient"] is None


def test_sar_backscatter_coefficient_invalid(con100):
    cube = con100.load_collection("S2")
    with pytest.raises(OpenEoClientException, match="Invalid.*coef.*unicorn.*Should.*sigma0-ellipsoid.*gamma0-terrain"):
        cube.sar_backscatter(coefficient="unicorn")


def test_datacube_from_process(con100):
    cube = con100.datacube_from_process("colorize", color="red", size=4)
    assert cube.flat_graph() == {
        "colorize1": {"process_id": "colorize", "arguments": {"color": "red", "size": 4}, "result": True}
    }


def test_datacube_from_process_namespace(con100):
    cube = con100.datacube_from_process("colorize", namespace="foo", color="red")
    assert cube.flat_graph() == {
        "colorize1": {"process_id": "colorize", "namespace": "foo", "arguments": {"color": "red"}, "result": True}
    }


class TestDataCubeFromFlatGraph:

    def test_datacube_from_flat_graph_minimal(self, con100):
        flat_graph = {"1+2": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}
        cube = con100.datacube_from_flat_graph(flat_graph)
        assert cube.flat_graph() == {"add1": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}

    def test_datacube_from_json_minimal_string(self, con100):
        udp_json = '''{"1+2": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": true}}'''
        cube = con100.datacube_from_json(udp_json)
        assert cube.flat_graph() == {"add1": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}

    @pytest.mark.parametrize("path_factory", [str, pathlib.Path])
    def test_datacube_from_json_minimal_file(self, con100, tmp_path, path_factory):
        path = tmp_path / "pg.json"
        with path.open("w") as f:
            f.write('''{"1+2": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": true}}''')
        cube = con100.datacube_from_json(path_factory(path))
        assert cube.flat_graph() == {"add1": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}

    def test_datacube_from_json_minimal_http(self, con100, requests_mock):
        url = "https://jzon.test/data/add.json"
        requests_mock.get(url, json={"1+2": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}})
        cube = con100.datacube_from_json(url)
        assert cube.flat_graph() == {"add1": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}

    def test_process_dict_wrapper(self, con100):
        flat_graph = {
            "id": "one-plus-two",
            "summary": "One plus two as a service",
            "process_graph": {"1+2": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}
        }
        cube = con100.datacube_from_flat_graph(flat_graph)
        assert cube.flat_graph() == {"add1": {"process_id": "add", "arguments": {"x": 1, "y": 2}, "result": True}}

    def test_parameter_substitution_minimal(self, con100):
        flat_graph = {
            "sub1": {"process_id": "subtract", "arguments": {"x": {"from_parameter": "f"}, "y": 32}, "result": True},
        }
        cube = con100.datacube_from_flat_graph(flat_graph, parameters={"f": 86})
        assert cube.flat_graph() == {
            "subtract1": {"process_id": "subtract", "arguments": {"x": 86, "y": 32}, "result": True},
        }

    def test_parameter_substitution_cube(self, con100):
        flat_graph = {
            "kernel": {"process_id": "constant", "arguments": {"x": [[1, 2, 1], [2, 5, 2], [1, 2, 1]]}},
            "blur": {
                "process_id": "apply_kernel",
                "arguments": {"data": {"from_parameter": "cube"}, "kernel": {"from_node": "kernel"}},
                "result": True
            },
        }
        input_cube = con100.load_collection("S2")
        cube = con100.datacube_from_flat_graph(flat_graph, parameters={"cube": input_cube})
        assert cube.flat_graph() == {
            "loadcollection1": {
                "process_id": "load_collection",
                "arguments": {"id": "S2", "spatial_extent": None, "temporal_extent": None}
            },
            "constant1": {"process_id": "constant", "arguments": {"x": [[1, 2, 1], [2, 5, 2], [1, 2, 1]]}},
            "applykernel1": {
                "process_id": "apply_kernel",
                "arguments": {"data": {"from_node": "loadcollection1"}, "kernel": {"from_node": "constant1"}},
                "result": True
            },
        }

    def test_parameter_substitution_udp(self, con100):
        flat_graph = {
            "id": "fahrenheit_to_celsius",
            "parameters": [{"description": "Degrees Fahrenheit.", "name": "f", "schema": {"type": "number"}}],
            "process_graph": {
                "sub1": {"process_id": "subtract", "arguments": {"x": {"from_parameter": "f"}, "y": 32}},
                "div1": {"process_id": "divide", "arguments": {"x": {"from_node": "sub1"}, "y": 1.8}, "result": True},
            },
        }
        cube = con100.datacube_from_flat_graph(flat_graph, parameters={"f": 86})
        assert cube.flat_graph() == {
            "subtract1": {"process_id": "subtract", "arguments": {"x": 86, "y": 32}},
            "divide1": {
                "process_id": "divide", "arguments": {"x": {"from_node": "subtract1"}, "y": 1.8}, "result": True
            },
        }

    def test_parameter_substitution_parameter_again(self, con100):
        flat_graph = {
            "sub1": {"process_id": "subtract", "arguments": {"x": {"from_parameter": "f"}, "y": 32}, "result": True},
        }
        cube = con100.datacube_from_flat_graph(flat_graph, parameters={"f": Parameter("warmth")})
        assert cube.flat_graph() == {
            "subtract1": {"process_id": "subtract", "arguments": {
                "x": {"from_parameter": "warmth"}, "y": 32
            }, "result": True},
        }

    def test_parameter_substitution_no_params(self, con100):
        flat_graph = {
            "sub1": {"process_id": "subtract", "arguments": {"x": {"from_parameter": "f"}, "y": 32}, "result": True},
        }
        with pytest.raises(ProcessGraphVisitException, match="No substitution value for parameter 'f'"):
            _ = con100.datacube_from_flat_graph(flat_graph)

    def test_parameter_substitution_missing_params(self, con100):
        flat_graph = {
            "sub1": {"process_id": "subtract", "arguments": {"x": {"from_parameter": "f"}, "y": 32}, "result": True},
        }
        with pytest.raises(ProcessGraphVisitException, match="No substitution value for parameter 'f'"):
            _ = con100.datacube_from_flat_graph(flat_graph, parameters={"something else": 42})

    @pytest.mark.parametrize(["kwargs", "expected"], [
        ({}, 100),
        ({"parameters": {}}, 100),
        ({"parameters": {"f": 86}}, 86),
    ])
    def test_parameter_substitution_default(self, con100, kwargs, expected):
        flat_graph = {
            "id": "fahrenheit_to_celsius",
            "parameters": [{"name": "f", "schema": {"type": "number"}, "default": 100}],
            "process_graph": {
                "sub1": {"process_id": "subtract", "arguments": {"x": {"from_parameter": "f"}, "y": 32}},
                "div1": {"process_id": "divide", "arguments": {"x": {"from_node": "sub1"}, "y": 1.8}, "result": True},
            },
        }
        cube = con100.datacube_from_flat_graph(flat_graph, **kwargs)
        assert cube.flat_graph() == {
            "subtract1": {"process_id": "subtract", "arguments": {"x": expected, "y": 32}},
            "divide1": {
                "process_id": "divide", "arguments": {"x": {"from_node": "subtract1"}, "y": 1.8}, "result": True
            },
        }


def test_send_nan_json(con100, requests_mock):
    """https://github.com/Open-EO/openeo-python-client/issues/185"""
    cube = con100.load_collection("S2")
    cube = cube.mask(cube > 100, replacement=float("nan"))
    with pytest.raises(requests.exceptions.InvalidJSONError, match="not JSON compliant"):
        cube.execute()


def test_dimension_labels(con100):
    cube = con100.load_collection("S2").dimension_labels("bands")
    assert cube.flat_graph() == {
        'loadcollection1': {
            'process_id': 'load_collection',
            'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        },
        'dimensionlabels1': {
            'process_id': 'dimension_labels',
            'arguments': {'data': {'from_node': 'loadcollection1'}, 'dimension': 'bands'},
            'result': True
        },
    }


def test_dimension_labels_invalid(con100):
    # Validate dimension name by default
    with pytest.raises(ValueError, match="Invalid dimension name 'unv6lidd'"):
        con100.load_collection("S2").dimension_labels("unv6lidd")

    # Don't validate when no metadata
    cube = con100.load_collection("S2", fetch_metadata=False).dimension_labels("unv6lidd")
    assert cube.flat_graph()["dimensionlabels1"]["arguments"]["dimension"] == "unv6lidd"


def test_fit_curve_callback(con100: Connection):
    from openeo.processes import array_element
    def model(x, parameters):
        return array_element(parameters, 0) + array_element(parameters, 1) * x

    img = con100.load_collection("S2")
    res = img.fit_curve(parameters=[0, 0], function=model, dimension="t")
    expected = {
        'loadcollection1': {
            'process_id': 'load_collection',
            'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        },
        'fitcurve1': {
            'process_id': 'fit_curve',
            'arguments': {
                'data': {'from_node': 'loadcollection1'},
                'parameters': [0, 0],
                'function': {
                    'process_graph': {
                        'arrayelement1': {
                            'process_id': 'array_element',
                            'arguments': {'data': {'from_parameter': 'parameters'}, 'index': 0},
                        },
                        'arrayelement2': {
                            'process_id': 'array_element',
                            'arguments': {'data': {'from_parameter': 'parameters'}, 'index': 1},
                        },
                        'multiply1': {
                            'process_id': 'multiply',
                            'arguments': {'x': {'from_node': 'arrayelement2'}, 'y': {'from_parameter': 'x'}},
                        },
                        'add1': {
                            'process_id': 'add',
                            'arguments': {'x': {'from_node': 'arrayelement1'}, 'y': {'from_node': 'multiply1'}},
                            'result': True
                        },
                    }
                },
                'dimension': 't',
            },
            'result': True
        },
    }
    assert res.flat_graph() == expected


def test_predict_curve_callback(con100: Connection):
    from openeo.processes import array_element, cos
    def model(x, parameters):
        return array_element(parameters, 0) * cos(array_element(parameters, 1) * x)

    img = con100.load_collection("S2")
    res = img.predict_curve(parameters=[0, 0], function=model, dimension="t")
    expected = {
        'loadcollection1': {
            'process_id': 'load_collection',
            'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
        },
        'predictcurve1': {
            'process_id': 'predict_curve',
            'arguments': {
                'data': {'from_node': 'loadcollection1'},
                'parameters': [0, 0],
                'function': {
                    'process_graph': {
                        'arrayelement1': {
                            'process_id': 'array_element',
                            'arguments': {'data': {'from_parameter': 'parameters'}, 'index': 0},
                        },
                        'arrayelement2': {
                            'process_id': 'array_element',
                            'arguments': {'data': {'from_parameter': 'parameters'}, 'index': 1},
                        },
                        'multiply1': {
                            'process_id': 'multiply',
                            'arguments': {'x': {'from_node': 'arrayelement2'}, 'y': {'from_parameter': 'x'}},
                        },
                        'cos1': {
                            'process_id': 'cos',
                            'arguments': {'x': {'from_node': "multiply1"}},
                        },
                        'multiply2': {
                            'process_id': 'multiply',
                            'arguments': {'x': {'from_node': 'arrayelement1'}, 'y': {'from_node': 'cos1'}},
                            'result': True
                        },
                    }
                },
                'dimension': 't',
                'labels': None,
            },
            'result': True
        },
    }
    assert res.flat_graph() == expected


def test_validation(con100, requests_mock):
    def validation(request, context):
        assert request.json() == {"process_graph": {
            'loadcollection1': {
                'process_id': 'load_collection',
                'arguments': {'id': 'S2', 'spatial_extent': None, 'temporal_extent': None},
                'result': True,
            }
        }}
        return {"errors": [{"code": "Invalid", "message": "Invalid process graph"}]}

    m = requests_mock.post(API_URL + "/validation", json=validation)

    cube = con100.load_collection("S2")
    errors = cube.validate()
    assert errors == [{"code": "Invalid", "message": "Invalid process graph"}]
    assert m.call_count == 1


def test_pipe_with_args(con100):
    def ndvi_scaled(cube, in_max=2, out_max=3):
        return cube.ndvi().linear_scale_range(0, in_max, 0, out_max)

    s2cube = con100.load_collection("S2")
    im = s2cube.pipe(ndvi_scaled)
    assert im.flat_graph()["apply1"]["arguments"]["process"]["process_graph"]["linearscalerange1"]["arguments"] == {
        'inputMax': 2, 'inputMin': 0, 'outputMax': 3, 'outputMin': 0, 'x': {'from_parameter': 'x'}
    }
    im = s2cube.pipe(ndvi_scaled, 4, 5)
    assert im.flat_graph()["apply1"]["arguments"]["process"]["process_graph"]["linearscalerange1"]["arguments"] == {
        'inputMax': 4, 'inputMin': 0, 'outputMax': 5, 'outputMin': 0, 'x': {'from_parameter': 'x'}
    }
    im = s2cube.pipe(ndvi_scaled, out_max=7)
    assert im.flat_graph()["apply1"]["arguments"]["process"]["process_graph"]["linearscalerange1"]["arguments"] == {
        'inputMax': 2, 'inputMin': 0, 'outputMax': 7, 'outputMin': 0, 'x': {'from_parameter': 'x'}
    }
