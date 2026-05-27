# Command Log

```bash
/opt/homebrew/bin/openfoam -c 'simpleFoam -listTurbulenceModels | grep -i -E "kOmegaSSTLM|transition|Langtry|gamma|ReTheta|kOmegaSST"'
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases sa_outlet_fixedValue0 --end-time 2005 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases sa_outlet_zeroGradient_pRef sa_outlet_freestreamPressure --end-time 2005 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases sa_outlet_zeroGradient_pRef --end-time 2050 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases sst_Tu0p5_L0p001c --end-time 2005 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases sst_Tu0p5_L0p001c --end-time 2050 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases lm_Tu0p5_L0p001c_r1 --end-time 2005 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases lm_Tu0p5_L0p001c_r1 --end-time 2050 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases lm_Tu0p5_L0p001c_r2 --end-time 2005 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases lm_Tu0p5_L0p001c_r2 --end-time 2050 --np 1
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --cases pimple_sst_Tu0p5_L0p001c --end-time 2000.1 --np 1
python3 -m py_compile scripts/run_wo006_hpa_model_architecture_sensitivity.py
```

All OpenFOAM solves were run serial after the parallel smoke showed RAM/disk/path risk. A no-space APFS run volume `/Volumes/hpa_tmp` was used for temporary OpenFOAM execution.
