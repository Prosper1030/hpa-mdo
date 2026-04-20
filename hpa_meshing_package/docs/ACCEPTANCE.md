# Acceptance

## 第一階段 acceptance checklist

### A. CLI
- [ ] `hpa-mesh run` works
- [ ] `hpa-mesh batch` works
- [ ] `hpa-mesh validate-geometry` works

### B. Config
- [ ] default yaml can be loaded
- [ ] overrides can be merged
- [ ] missing required fields produce readable error message

### C. Geometry
- [ ] STEP import works
- [ ] IGES import works or fails clearly if unsupported in current env
- [ ] volume/surface counts are extracted
- [ ] bbox is extracted

### D. Mesh output
- [ ] `.msh` written
- [ ] `.su2` written
- [ ] physical groups/markers preserved
- [ ] output directory structure stable

### E. Report
- [ ] `report.json` exists
- [ ] `report.md` exists
- [ ] `retry_history.json` exists
- [ ] failure code exists when failed

### F. Recipes
- [ ] fairing_solid existing special case works
- [ ] main_wing basic recipe works on at least one example
- [ ] tail_wing basic recipe works on at least one example
- [ ] fairing_vented skeleton exists even if partial

### G. Fallback
- [ ] retry order is deterministic
- [ ] retry actions are logged
- [ ] final error is classified

## 第二階段 acceptance（未來）
- robust BL strategy
- more geometry families
- stronger quality metrics
- batch benchmark summary
