# Recommended Full-Alpha Strategy

Do not use `archive_source_quality` alone as the inclusion rule. The next database should preserve candidates because they are useful evidence sources: archive mission-grade, actual-sidecar-query pass, strong screening performers, Pareto-front members, repair-worthy diagnostics, final-generation survivors, and seed/DAE/ClarkY references.

## Tier Summary

| tier | candidate count | expected polar points | runtime vs Tier 1 | estimated CSV+JSON storage | recommendation |
| --- | ---: | ---: | ---: | ---: | --- |
| Tier 1 minimum_high_value_set | 170 | 276,916 | 1x | 142.281201 MB | First reusable full-alpha DB build; high value and diversity without paying for all screening-pass records. |
| Tier 2 recommended_reusable_db_set | 2832 | 4,613,098 | 16.6588235x | 2370.23742 MB | Preferred reusable DB if runtime is acceptable; enough data to guide NSGA v2 without relying on sparse target-Cl screening. |
| Tier 3 exhaustive_current_candidate_set | 4102 | 6,681,825 | 24.1294118x | 3433.16168 MB | Exhaustive archive of the current search, useful only if runtime/storage budget is deliberately allocated. |

## Recommended Path

1. Build Tier 1 first if the goal is quick, auditable reusable evidence. It includes the high-value top-k/top32 screening candidates, all actual-query passes, repair-worthy/repaired candidates, and FX76/ClarkY/DAE references.
2. Prefer Tier 2 if runtime is acceptable. It converts all screening-pass CST records into full-alpha evidence, which is the cleanest way to guide NSGA v2 without letting sparse target-Cl screening overrule real polar quality.
3. Avoid Tier 3 unless the goal is archival completeness. It is roughly the full 4096 CST set plus references and should be treated as an intentionally expensive evidence build.

## Quality Label Policy

- Keep `screening_quality`, `archive_source_quality`, `actual_sidecar_query_quality`, and repaired diagnostic labels as separate columns.
- A candidate included through actual-sidecar or repair-worthy evidence is not automatically archive mission-grade.
- CST coefficients were not exported in the current screening artifacts; the manifest preserves coordinate paths and geometry hashes instead.
