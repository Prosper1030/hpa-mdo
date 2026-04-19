from __future__ import annotations

from pathlib import Path
import csv

import matplotlib.pyplot as plt

BASE = Path("docs/research/xfoil_fx76mp140_re410000")
POLAR_PATH = BASE / "fx76mp140_re410000.polar"
CSV_PATH = BASE / "fx76mp140_re410000.csv"


def parse_polar(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            alpha, cl, cd, cdp, cm, top_xtr, bot_xtr, top_itr, bot_itr = map(float, parts[:9])
        except ValueError:
            continue
        rows.append(
            {
                "alpha": alpha,
                "cl": cl,
                "cd": cd,
                "cdp": cdp,
                "cm": cm,
                "top_xtr": top_xtr,
                "bot_xtr": bot_xtr,
                "top_itr": top_itr,
                "bot_itr": bot_itr,
                "cl_cd": cl / cd if cd > 0 else float("nan"),
            }
        )
    if not rows:
        raise RuntimeError(f"No polar rows parsed from {path}")
    return rows


def write_csv(rows: list[dict[str, float]], path: Path) -> None:
    fieldnames = [
        "alpha",
        "cl",
        "cd",
        "cdp",
        "cm",
        "top_xtr",
        "bot_xtr",
        "top_itr",
        "bot_itr",
        "cl_cd",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot_xy(
    x: list[float],
    y: list[float],
    x_label: str,
    y_label: str,
    title: str,
    out_name: str,
) -> None:
    plt.figure(figsize=(8, 5.2))
    plt.plot(x, y, marker="o", markersize=3, linewidth=1.2)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(BASE / out_name, dpi=180)
    plt.close()


def main() -> None:
    rows = parse_polar(POLAR_PATH)
    write_csv(rows, CSV_PATH)

    alpha = [r["alpha"] for r in rows]
    cl = [r["cl"] for r in rows]
    cd = [r["cd"] for r in rows]
    cl_cd = [r["cl_cd"] for r in rows]

    plot_xy(alpha, cl, "Alpha (deg)", "CL", "FX 76-MP-140 @ Re=410000: CL vs Alpha", "cl_vs_alpha.png")
    plot_xy(cd, cl, "CD", "CL", "FX 76-MP-140 @ Re=410000: CL vs CD", "cl_vs_cd.png")
    plot_xy(alpha, cl_cd, "Alpha (deg)", "CL/CD", "FX 76-MP-140 @ Re=410000: CL/CD vs Alpha", "clcd_vs_alpha.png")
    plot_xy(alpha, cd, "Alpha (deg)", "CD", "FX 76-MP-140 @ Re=410000: CD vs Alpha", "cd_vs_alpha.png")

    print(f"Parsed {len(rows)} rows from {POLAR_PATH}")
    print(f"Wrote CSV to {CSV_PATH}")


if __name__ == "__main__":
    main()
