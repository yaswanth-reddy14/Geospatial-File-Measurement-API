from datetime import date

import numpy as np
import pandas as pd

from app.services.geospatial_service import json_value


def test_attribute_normalization_preserves_values_and_removes_nonfinite_numbers():
    properties = {
        "missing": pd.NA,
        "nan": np.nan,
        "infinity": np.inf,
        "integer": np.int64(7),
        "flag": np.bool_(True),
        "date": date(2026, 1, 1),
        "array": np.array([1, 2]),
        "nested": {"value": (np.float64(1.25), None)},
    }
    assert json_value(properties) == {
        "missing": None,
        "nan": None,
        "infinity": None,
        "integer": 7,
        "flag": True,
        "date": "2026-01-01",
        "array": [1, 2],
        "nested": {"value": [1.25, None]},
    }
