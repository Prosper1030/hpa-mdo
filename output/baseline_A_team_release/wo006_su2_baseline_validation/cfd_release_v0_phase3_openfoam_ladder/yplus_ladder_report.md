# yPlus Ladder Report

| case | acceptance | y+ upper min | y+ upper mean | y+ upper max | y+ lower min | y+ lower mean | y+ lower max | band |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `layers_0` | `accepted` | `7.47463` | `325.5238` | `1323.791` | `17.41203` | `398.1273` | `1171.601` | `very_high_yplus_sanity` |
| `layers_3` | `rejected` | `2.189015` | `193.8764` | `1571.604` | `6.285849` | `134.6553` | `1173.716` | `high_yplus_sanity` |
| `layers_8` | `accepted` | `2.631601` | `183.2387` | `1437.448` | `5.166011` | `164.5427` | `1191.102` | `high_yplus_sanity` |
| `layers_12` | `rejected` | `2.916205` | `188.8339` | `1388.44` | `4.244358` | `174.16` | `1191.417` | `high_yplus_sanity` |
| `layers_16` | `accepted` | `6.247234` | `194.7079` | `1364.542` | `7.318836` | `186.3026` | `1172.569` | `high_yplus_sanity` |
| `layers_24` | `accepted` | `4.717453` | `209.5007` | `1437.047` | `7.129226` | `193.3586` | `1175.667` | `very_high_yplus_sanity` |
| `layers_12_low_yplus_factor_0p44` | `rejected` | `not_available` | `not_available` | `not_available` | `not_available` | `not_available` | `not_available` | `missing_yplus` |
| `layers_8_refined_surface_plus1` | `rejected` | `2.273142` | `89.9788` | `819.205` | `4.945745` | `86.52465` | `652.5112` | `wall_function_sanity` |
| `layers_8_kOmegaSST_same_mesh` | `rejected` | `3.615681` | `47.7129` | `266.2735` | `4.52467` | `45.58173` | `357.6448` | `wall_function_sanity` |

Interpretation: mean y+ below 200 is still high-yPlus sanity unless it lands in a defensible wall-function band, roughly 30-100 here.  Max y+ spikes above 1000 remain a warning against final drag claims.