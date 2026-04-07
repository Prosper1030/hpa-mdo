import csv
import argparse
from pathlib import Path
import sys

def export_cadquery(csv_file, step_file):
    try:
        import cadquery as cq
    except ImportError:
        print("Error: cadquery module not found. Please install cadquery.")
        sys.exit(1)

    y_coords = []
    ods = []
    ids = []

    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Assuming node along Y axis as per Y_Position_m
                y = float(row.get('Y_Position_m', 0.0))
                od = float(row['Outer_Diameter_m'])
                id_ = float(row['Inner_Diameter_m'])
                
                # Convert meters to millimeters for standard step file format (often expected in mm)
                y_coords.append(y * 1000)
                ods.append(od * 1000)
                ids.append(id_ * 1000)
    except Exception as e:
        print(f"Error reading {csv_file}: {e}")
        sys.exit(1)

    print(f"Read {len(y_coords)} sections from {csv_file}")
    print("Building 3D model with CadQuery...")

    # Build outer solid
    # We use the XZ plane which has its normal pointing along the Y axis
    outer_wp = cq.Workplane("XZ")
    for i, y in enumerate(y_coords):
        if i == 0:
            outer_wp = outer_wp.workplane(offset=y).circle(ods[i] / 2.0)
        else:
            delta_y = y - y_coords[i-1]
            outer_wp = outer_wp.workplane(offset=delta_y).circle(ods[i] / 2.0)
            
    outer_solid = outer_wp.loft(ruled=True)
    
    # Build inner solid
    inner_wp = cq.Workplane("XZ")
    for i, y in enumerate(y_coords):
        if i == 0:
            inner_wp = inner_wp.workplane(offset=y).circle(ids[i] / 2.0)
        else:
            delta_y = y - y_coords[i-1]
            inner_wp = inner_wp.workplane(offset=delta_y).circle(ids[i] / 2.0)
            
    inner_solid = inner_wp.loft(ruled=True)
    
    # Hollow pipe
    spar_tube = outer_solid.cut(inner_solid)

    Path(step_file).parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(spar_tube, str(step_file))
    print(f"Successfully exported 3D spar model to {step_file}")

def export_build123d(csv_file, step_file):
    try:
        from build123d import BuildPart, BuildSketch, Plane, Circle, loft, export_step
    except ImportError:
        print("Error: build123d module not found. Please install build123d.")
        sys.exit(1)
        
    y_coords = []
    ods = []
    ids = []

    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                y = float(row.get('Y_Position_m', 0.0))
                od = float(row['Outer_Diameter_m'])
                id_ = float(row['Inner_Diameter_m'])
                
                # Convert meters to millimeters
                y_coords.append(y * 1000)
                ods.append(od * 1000)
                ids.append(id_ * 1000)
    except Exception as e:
        print(f"Error reading {csv_file}: {e}")
        sys.exit(1)

    print(f"Read {len(y_coords)} sections from {csv_file}")
    print("Building 3D model with build123d...")

    with BuildPart() as outer_solid:
        for y, od in zip(y_coords, ods):
            with BuildSketch(Plane.XZ.offset(y)):
                Circle(od / 2.0)
        loft(ruled=True)

    with BuildPart() as inner_solid:
        for y, id_ in zip(y_coords, ids):
            with BuildSketch(Plane.XZ.offset(y)):
                Circle(id_ / 2.0)
        loft(ruled=True)
        
    spar_tube = outer_solid.part - inner_solid.part

    Path(step_file).parent.mkdir(parents=True, exist_ok=True)
    export_step(spar_tube, str(step_file))
    print(f"Successfully exported 3D spar model to {step_file}")

def main():
    parser = argparse.ArgumentParser(description="Export Spar Optimization Data to STEP file.")
    parser.add_argument("--input", default="output/blackcat_004/ansys/spar_data.csv", help="Input CSV file path")
    parser.add_argument("--output", default="output/blackcat_004/spar_model.step", help="Output STEP file path")
    parser.add_argument("--engine", choices=["cadquery", "build123d", "auto"], default="auto", help="CAD engine to use")

    args = parser.parse_args()

    # Determine which engine to use
    engine = args.engine
    if engine == "auto":
        try:
            import build123d
            engine = "build123d"
        except ImportError:
            try:
                import cadquery
                engine = "cadquery"
            except ImportError:
                print("Error: Neither build123d nor cadquery is installed.")
                print("Please install one of them: pip install build123d OR pip install cadquery")
                sys.exit(1)

    if engine == "cadquery":
        export_cadquery(args.input, args.output)
    else:
        export_build123d(args.input, args.output)

if __name__ == "__main__":
    main()
