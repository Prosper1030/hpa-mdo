from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hpa_mdo.utils.cad_export import export_step_from_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export spar geometry CSV to a STEP file."
    )
    parser.add_argument(
        "--input",
        default="output/blackcat_004/ansys/spar_data.csv",
        help="Input CSV file path",
    )
    parser.add_argument(
        "--output",
        default="output/blackcat_004/spar_model.step",
        help="Output STEP file path",
    )
    parser.add_argument(
        "--engine",
        choices=["cadquery", "build123d", "auto"],
        default="auto",
        help="CAD engine to use",
    )

    args = parser.parse_args()
    try:
        engine_name = export_step_from_csv(args.input, args.output, engine=args.engine)
        print(f"Successfully exported 3D spar model to {args.output} ({engine_name})")
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
