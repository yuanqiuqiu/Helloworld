# MISO model mapper

Utility for mapping a MISO SE raw file date to the quarterly EMS model and the
four same-day SE raw files.

Default roots:

- Quarterly EMS models: `G:\Power\MISO\Quarterly EMS Models`
- SE raw files: `G:\Power\MISO\MISO_SE`

Quarter selection:

- Jan-Feb: previous December model, for example `Dec2025_final.raw`
- Mar-May: March model, for example `Mar2026_final.raw`
- Jun-Aug: June model, for example `Jun2026_final.raw`
- Sep-Nov: September model, for example `Sep2026_final.raw`
- Dec: December model, for example `Dec2026_final.raw`

Example:

```bash
python miso_model_mapper.py --date 20260511
```

This looks for:

- `G:\Power\MISO\Quarterly EMS Models\202603\Mar2026_final.raw`
- four SE files matching
  `G:\Power\MISO\MISO_SE\2026\miso_se_20260511-HHMM_AREVA.raw`

Use a SE raw filename directly:

```bash
python miso_model_mapper.py --se-file miso_se_20260427-1800_AREVA.raw
```

To print expected paths without checking the filesystem:

```bash
python miso_model_mapper.py --date 20260511 --expected-only
```

The command prints plain text, for example:

```text
Study date: 2026-05-11
Quarter model: G:\Power\MISO\Quarterly EMS Models\202603\Mar2026_final.raw
SE raw files:
  G:\Power\MISO\MISO_SE\2026\miso_se_20260511-0000_AREVA.raw
  ...
```

## Planned outage XML mapping

Install dependencies first:

```bash
pip install -r requirements.txt
```

Use `planned_outages.py` to find the planned outage XML snapshot for one SE raw
file:

```bash
python planned_outages.py --se-file miso_se_20260427-0000_AREVA.raw --planned-outage-root "G:\Power\MISO\Planned Outages"
```

Planned outage files are expected to look like:

```text
2308_Planned_Outages_2026-04-07-04-50-00.xml
```

The default filename-hour rule follows the examples:

- `miso_se_20260427-0000_AREVA.raw` -> planned outage filename hour `04`
- `miso_se_20260427-0500_AREVA.raw` -> planned outage filename hour `09`

If another dataset needs SE hour + 5 instead, pass `--hour-offset 5`.

For one SE raw file, find both required input files:

```python
from planned_outages import find_inputs_for_se_raw

inputs = find_inputs_for_se_raw(
    se_raw_file,
    quarter_model_root=r"G:\Power\MISO\Quarterly EMS Models",
    planned_outage_root=r"G:\Power\MISO\Planned Outages",
)
```

After PowerWorld reads `inputs.quarter_model.path` and the SE raw file into
BranchLists, map the active planned outages to both cases:

```python
from planned_outages import map_outage_file_to_branch_lists

mapped = map_outage_file_to_branch_lists(
    inputs.planned_outage_file,
    se_raw_file,
    quarter_branch_list=quarter_branch_list,
    se_branch_list=se_branch_list,
)
```

`mapped["quarter"]` contains planned outages mapped to the quarterly model
BranchList. `mapped["se"]` contains the same outage rows mapped to the SE model
BranchList. `mapped["future_retired"]` contains original A-B branch candidates
that should stay open when Future Equipment A-C and C-B is already in service in
the SE case.