# MISO model mapper

Utility for mapping MISO SE raw files to the quarterly EMS model and planned
outage XML files.

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
python MISO_quarter_model_mapper.py --date 20260511
```

This looks for:

- `G:\Power\MISO\Quarterly EMS Models\202603\Mar2026_final.raw`
- four SE files matching
  `G:\Power\MISO\MISO_SE\2026\miso_se_20260511-HHMM_AREVA.raw`
- planned outage XML files with filename hour = SE hour + 4

Use a SE raw filename directly:

```bash
python MISO_quarter_model_mapper.py --se-file miso_se_20260427-1800_AREVA.raw --planned-outage-root "G:\Power\MISO\Planned Outages"
```

The command prints plain text, for example:

```text
SE raw file: G:\Power\MISO\MISO_SE\2026\miso_se_20260511-0000_AREVA.raw
SE time: 2026-05-11 00:00
Quarter model: G:\Power\MISO\Quarterly EMS Models\202603\Mar2026_final.raw
Planned outage XML: G:\Power\MISO\Planned Outages\...\2308_Planned_Outages_2026-...
```

## Planned outage processing

Install dependencies first:

```bash
pip install -r requirements.txt
```

`MISO_quarter_model_mapper.py` is the file lookup script. It maps each SE raw
file to:

- the quarterly model
- the planned outage XML

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
from MISO_quarter_model_mapper import find_inputs_for_se_raw

inputs = find_inputs_for_se_raw(
    se_raw_file,
    quarter_model_root=r"G:\Power\MISO\Quarterly EMS Models",
    planned_outage_root=r"G:\Power\MISO\Planned Outages",
)
```

After PowerWorld reads `inputs.quarter_model.path` and the SE raw file into
BranchLists, process the active planned outages:

```python
from MISO_planned_outage_process import map_outage_file_to_branch_lists

mapped = map_outage_file_to_branch_lists(
    inputs.planned_outage_file,
    se_raw_file,
    quarter_branch_list=quarter_branch_list,
    se_branch_list=se_branch_list,
)
```

`mapped["quarter"]` contains planned outages mapped to the quarterly model
BranchList. `mapped["se"]` contains the same outage rows mapped to the SE model
BranchList. `mapped["baseline_actions"]` contains branch status changes to build
the baseline topology:

- active `OOS` planned outage -> `Closed`
- active `InSvrNo` planned outage -> `Open`
- `Future Equipment` -> keep future equipment `Open`
- previous A-B device replaced by future A-C/C-B equipment -> `Closed`