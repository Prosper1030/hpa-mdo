# Recommended Fourier Bridge

- Cases calibrated: 10
- Statuses: outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited, outer_underloaded_authority_limited
- Recommendation: Advance to MVP 2 only with the measured commanded-to-realized rows carried as bridge uncertainty. Do not use raw commanded Fourier coefficients as truth.

## Bridge Policy

- Use `fourier_command_to_avl_realized.csv` as an explicit measured table.
- Treat Fourier theoretical `e` as a design-language diagnostic, not the induced-drag authority.
- Treat AVL `e_CDi` and AVL actual spanload as the aerodynamic evidence for downstream structure-budgeted search.
- If a result is ambiguous, carry the status label forward instead of forcing a design decision.
