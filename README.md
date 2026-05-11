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