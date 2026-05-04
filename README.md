# Annual auction analysis helpers

`auction_round_analysis.py` adds helpers for reading one or more previous
auction result rounds, aggregating binding constraints, and comparing Round 2
against Round 1.

Use it in the annual auction script by replacing the single-round
`prev_files = ...; pd.read_csv(prev_files)` block with:

```python
from auction_round_analysis import (
    prepare_auction_constraints_for_mapping,
    write_round_comparison_outputs,
)

auction_result_path = [
    r"G:\Power\MISO\FTR Results\2026_00\Round 1\Public",
    r"G:\Power\MISO\FTR Results\2026_00\Round 2\Public",
]

auction_constraints_for_mapping, round_comparison, raw_constraints = (
    prepare_auction_constraints_for_mapping(
        auction_result_path,
        tou_str,
        auction_type,
        auction_name,
    )
)

write_round_comparison_outputs(round_comparison, f"{out_put_path}/feathers", tou_str)

auction_constraints_mapped, auction_monitor_ele = map_auction_constraint(
    auction_constraints_for_mapping,
    ftr_ctg_aux_mapped,
    nomg,
    flowgates,
    BranchList_ftr,
)
```

`auction_constraints_for_mapping` is labelled `DA=False`; its ranking is based
on total absolute shadow price across all loaded rounds. The comparison output
labels Round 2 constraints as new, missing, or present in both rounds and
includes the shadow-price change from Round 1 to Round 2.