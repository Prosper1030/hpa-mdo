from __future__ import annotations

from io import StringIO

import pandas as pd
import pytest

from hpa_mdo.aero.xflr5 import XFLR5Parser


def test_parse_csv_with_standard_columns(tmp_path):
    csv_buf = StringIO(
        "\n".join(
            [
                "y,chord,cl,cd,cm",
                "-0.5,1.10,0.50,0.020,-0.050",
                "0.0,1.00,0.55,0.021,-0.040",
                "1.0,0.80,0.60,0.023,-0.030",
            ]
        )
    )
    csv_path = tmp_path / "xflr5_standard.csv"
    csv_path.write_text(csv_buf.getvalue(), encoding="utf-8")

    parser = XFLR5Parser(csv_path, velocity=6.5, air_density=1.225)
    cases = parser.parse(aoa_deg=2.0)

    assert len(cases) == 1
    case = cases[0]
    assert case.aoa_deg == pytest.approx(2.0)
    assert case.y.min() >= 0.0
    assert case.chord[0] == pytest.approx(1.0)
    assert case.cl[-1] == pytest.approx(0.60)


def test_parse_csv_with_alternate_column_names(tmp_path):
    csv_buf = StringIO(
        "\n".join(
            [
                "Y (m),Chord (m),Cl Local,Cd Local,Cm Local",
                "0.0,1.20,0.52,0.022,-0.045",
                "1.5,0.90,0.58,0.024,-0.035",
            ]
        )
    )
    csv_path = tmp_path / "xflr5_alt_cols.csv"
    csv_path.write_text(csv_buf.getvalue(), encoding="utf-8")

    parser = XFLR5Parser(csv_path)
    cases = parser.parse()

    assert len(cases) == 1
    case = cases[0]
    assert case.y[0] == pytest.approx(0.0)
    assert case.chord[1] == pytest.approx(0.90)
    assert case.cl[0] == pytest.approx(0.52)


def test_parse_raises_on_empty_file(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")

    parser = XFLR5Parser(csv_path)
    with pytest.raises((IndexError, ValueError, pd.errors.EmptyDataError)):
        parser.parse()
