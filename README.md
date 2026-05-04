# Auction Results to YesEnergy Portfolio

Use `auction_to_yesenergy_portfolio.py` to append new MISO FTR auction award
results to an active master file, expand quarterly awards into monthly paths,
combine matching paths, and write a YesEnergy portfolio workbook.

Default run:

```bash
python3 -m pip install -r requirements.txt
python3 auction_to_yesenergy_portfolio.py
```

Useful overrides:

```bash
python3 auction_to_yesenergy_portfolio.py \
  --rootpath "G:\Power\MISO\FTR Results" \
  --auction-folder "2026_05" \
  --auction-name "May26" \
  --auction-date "05/01/2026"
```

The script reads `AUCTION_PRIVATE_RESULTS*.csv` files from the auction
`Private` folder, updates `yesenergy_awarded_paths_master.xlsx`, removes paths
with `contractstartdate` before the prompt month, and writes the combined
`*_yesenergy_portfolio.xlsx` output.
