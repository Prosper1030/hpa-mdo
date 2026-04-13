from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts.dihedral_sweep_campaign import (
    parse_avl_eigenvalue_file,
    parse_avl_mode_stdout,
    scale_avl_dihedral_text,
    select_dutch_roll_mode,
)


class DihedralSweepCampaignTests(unittest.TestCase):
    def test_scale_avl_dihedral_text_multiplies_section_z(self) -> None:
        base_text = "\n".join(
            [
                "SURFACE",
                "Wing",
                "SECTION",
                "0.0  0.0  0.100000000  1.2  0.0",
                "SECTION",
                "0.0  5.0  0.300000000  1.0  0.0 ! tip",
                "",
            ]
        )

        scaled_text, count = scale_avl_dihedral_text(base_text, multiplier=2.0)

        self.assertEqual(count, 2)
        self.assertIn("0.200000000", scaled_text)
        self.assertIn("0.600000000", scaled_text)
        self.assertIn("! tip", scaled_text)

    def test_parse_mode_stdout_and_select_dutch_roll(self) -> None:
        stdout_text = """
 Run case  1:   example

  mode 1:  -0.20000       2.50000
 u  :     0.1000     0.0000      v  :     4.0000     0.0000      x  :   0.000       0.000
 w  :     0.0500     0.0000      p  :     2.0000     0.0000      y  :   0.100       0.000
 q  :     0.0200     0.0000      r  :     3.0000     0.0000      z  :   0.000       0.000
 the:     0.0100     0.0000      phi:     1.5000     0.0000      psi:   1.200       0.000

  mode 2:  -0.05000       0.40000
 u  :     5.0000     0.0000      v  :     0.2000     0.0000      x  :   0.000       0.000
 w  :     2.0000     0.0000      p  :     0.1000     0.0000      y  :   0.000       0.000
 q  :     1.0000     0.0000      r  :     0.1000     0.0000      z  :   0.000       0.000
 the:     0.5000     0.0000      phi:     0.1000     0.0000      psi:   0.100       0.000
"""
        blocks = parse_avl_mode_stdout(stdout_text)
        found, selection, real, imag = select_dutch_roll_mode(
            eigenvalues=(),
            mode_blocks=blocks,
            allow_missing_mode=False,
        )

        self.assertTrue(found)
        self.assertEqual(selection, "oscillatory_lateral_mode")
        self.assertAlmostEqual(real, -0.2)
        self.assertAlmostEqual(imag, 2.5)

    def test_parse_avl_eigenvalue_file_reads_saved_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "modes.st"
            path.write_text(
                "\n".join(
                    [
                        "# demo",
                        "       1    -0.3000000         1.1000000",
                        "       1    -0.3000000        -1.1000000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            eigs = parse_avl_eigenvalue_file(path)

        self.assertEqual(len(eigs), 2)
        self.assertAlmostEqual(eigs[0].real, -0.3)
        self.assertAlmostEqual(eigs[0].imag, 1.1)


if __name__ == "__main__":
    unittest.main()
