# Open Questions

這些是需要專案 owner 補充的參數；沒有也能先做骨架，但 recipe 很難收斂：

1. 你們 SU2 的標準 marker 命名要不要固定成：
   - wall
   - farfield
   - symmetry
   - inlet
   - outlet

2. 主翼與尾翼的 farfield 規則：
   - upstream = ?
   - downstream = ?
   - radial / vertical = ?

3. 第一版要不要強制 BL？
   - yes / optional / no

4. fairing_vented:
   - 最大孔數
   - 最小孔寬
   - 最小孔間距
   - 支援孔型清單

5. 目前 fairing 無洞 special case：
   - 哪些 refinement 其實是硬編碼？
   - 哪些規則可抽象成 config？

6. 目前已有網格品質門檻嗎？
   - skewness
   - Jacobian
   - aspect ratio
   - element count upper bound

7. `.su2` export 目前要不要保留特定 marker 次序？

8. 你們是否需要之後接 batch optimization loop？
   - 如果需要，report.json 應該加 case_id / design_id / hash
