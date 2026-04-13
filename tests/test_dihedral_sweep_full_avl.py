# ruff: noqa: E402
from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts.dihedral_sweep_campaign import scale_avl_dihedral_text


class DihedralSweepFullAvlTests(unittest.TestCase):
    def test_scale_avl_dihedral_text_only_modifies_wing_surface(self) -> None:
        base_text = "\n".join(
            [
                "SURFACE",
                "Wing",
                "SECTION",
                "0.0  0.0  0.100000000  1.2  0.0",
                "SURFACE",
                "Elevator",
                "SECTION",
                "4.0  0.5  0.300000000  0.8  0.0 ! fixed",
                "",
            ]
        )

        scaled_text, count = scale_avl_dihedral_text(base_text, multiplier=2.0)

        self.assertEqual(count, 1)
        self.assertIn("0.200000000", scaled_text)
        self.assertIn("0.300000000", scaled_text)
        self.assertIn("! fixed", scaled_text)


if __name__ == "__main__":
    unittest.main()
