#!/usr/bin/env python3
"""One-off importer for the smart-scale body-composition export.

Parses the tab-separated weigh-in data below, de-duplicates to one reading per
day (keeping the row with the most data), and writes it to daily_metrics with
source='scale' via the shared backend.body_import module. Safe to re-run — each
metric/day is upserted.

Run from the repo root:  python scripts/import_body_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import body_import  # noqa: E402

RAW = """\
Number	Date and Time	Weight(lb)	Weight(kg)	BMI	Body Fat	Muscle Mass	Muscle Mass %	Body Water	Lean Body Mass	Bone Mass	Protein	Visceral Fat	BMR	Metabolic Age	Skeletal Muscle Rate %	Fat Content	Subcutaneous Fat
1	2026.05.10 08:34 PM	130.1lb	59.0kg	20.4	15.0%	103.6lb	79.6%	62.2%	110.6lb	6.8lb	17.5%	5	1453	27	47.4%	19.6lb	10.8%
2	2026.05.06 02:53 PM	126.3lb	57.3kg	19.8	13.3%	102.5lb	81.2%	63.4%	109.5lb	6.6lb	17.9%	4	1443	28	48.3%	16.8lb	9.5%
3	2026.04.29 03:25 PM	124.6lb	56.5kg	19.5	12.4%	102.3lb	82.1%	64.1%	109.1lb	6.6lb	18.1%	4	1439	28	- -	15.4lb	- -
4	2026.04.29 03:24 PM	124.6lb	56.5kg	19.5	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -
5	2026.04.14 04:56 PM	121.9lb	55.3kg	19.1	11.0%	101.6lb	83.4%	65.1%	108.5lb	6.6lb	18.4%	4	1433	28	- -	13.4lb	- -
6	2026.04.14 04:56 PM	121.9lb	55.3kg	19.1	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -
7	2026.04.14 04:55 PM	121.9lb	55.3kg	19.1	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -
8	2026.04.09 08:04 PM	123.5lb	56.0kg	19.4	11.7%	102.1lb	82.7%	64.6%	109.0lb	6.6lb	18.2%	4	1438	28	- -	14.6lb	- -
9	2026.03.29 05:37 PM	125.4lb	56.9kg	19.7	12.6%	102.7lb	81.9%	63.9%	109.6lb	6.6lb	18.0%	4	1444	28	- -	15.9lb	- -
10	2026.02.12 03:26 PM	125.4lb	56.9kg	19.7	12.8%	102.5lb	81.8%	63.8%	109.3lb	6.6lb	18.0%	4	1441	28	- -	16.1lb	- -
11	2026.01.02 06:33 PM	130.5lb	59.2kg	20.5	15.0%	104.1lb	79.7%	62.2%	110.9lb	6.8lb	17.5%	5	1456	27	- -	19.6lb	- -
12	2025.12.16 04:31 PM	124.6lb	56.5kg	19.5	12.4%	102.3lb	82.1%	64.1%	109.1lb	6.6lb	18.1%	4	1439	27	- -	15.4lb	- -
13	2025.10.31 11:47 AM	126.5lb	57.4kg	19.9	13.3%	102.7lb	81.2%	63.4%	109.7lb	6.6lb	17.9%	4	1444	27	- -	16.8lb	- -
14	2025.10.17 04:04 PM	127.0lb	57.6kg	19.9	13.4%	103.0lb	81.1%	63.3%	110.0lb	6.6lb	17.9%	4	1447	27	- -	17.0lb	- -
15	2025.10.14 02:41 PM	127.0lb	57.6kg	19.9	13.4%	103.0lb	81.1%	63.3%	110.0lb	6.6lb	17.9%	4	1447	27	- -	17.0lb	- -
16	2025.10.06 01:27 PM	125.0lb	56.7kg	19.6	12.4%	102.5lb	82.0%	64.1%	109.5lb	6.6lb	18.1%	4	1442	27	- -	15.4lb	- -
17	2025.09.28 06:33 AM	123.7lb	56.1kg	19.4	11.6%	102.5lb	82.9%	64.7%	109.3lb	6.6lb	18.2%	4	1441	27	- -	14.3lb	- -
18	2025.09.12 02:41 PM	125.4lb	56.9kg	19.7	12.5%	103.0lb	82.1%	64.0%	109.7lb	6.6lb	18.1%	4	1445	27	- -	15.7lb	- -
19	2025.09.04 06:47 AM	125.4lb	56.9kg	19.7	12.4%	103.0lb	82.1%	64.1%	109.8lb	6.6lb	18.1%	4	1446	27	- -	15.7lb	- -
20	2025.08.14 08:43 PM	127.4lb	57.8kg	20.0	13.2%	103.6lb	81.3%	63.5%	110.6lb	6.8lb	17.9%	4	1453	26	- -	16.8lb	- -
21	2025.08.14 08:43 PM	127.4lb	57.8kg	20.0	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -	- -
22	2025.08.03 09:44 AM	125.4lb	56.9kg	19.7	12.3%	103.2lb	82.3%	64.1%	110.0lb	6.6lb	18.1%	4	1447	27	- -	15.4lb	- -
23	2025.07.20 10:32 AM	129.6lb	58.8kg	20.3	14.1%	104.3lb	80.5%	62.8%	111.3lb	6.8lb	17.7%	5	1460	26	- -	18.3lb	- -
24	2025.07.09 10:44 PM	127.6lb	57.9kg	20.0	13.2%	103.8lb	81.4%	63.5%	110.8lb	6.8lb	17.9%	4	1455	26	- -	16.8lb	- -
25	2025.07.05 04:01 PM	128.1lb	58.1kg	20.1	13.4%	103.8lb	81.1%	63.3%	110.9lb	6.8lb	17.9%	5	1456	26	- -	17.2lb	- -
26	2025.06.26 10:45 AM	129.0lb	58.5kg	20.2	13.9%	104.1lb	80.7%	63.0%	111.1lb	6.8lb	17.8%	5	1457	26	- -	17.9lb	- -
27	2025.06.19 09:48 AM	127.6lb	57.9kg	20.0	13.3%	103.6lb	81.2%	63.4%	110.6lb	6.8lb	17.9%	4	1454	26	- -	17.0lb	- -
"""


def main() -> None:
    summary = body_import.import_tsv(RAW)
    rng = summary["date_range"]
    print("Smart-scale body composition import")
    print("-" * 40)
    print(f"  Rows parsed:         {summary['rows_parsed']}")
    print(f"  Duplicate rows skipped: {summary['duplicates_skipped']}")
    print(f"  Days imported:       {summary['dates_imported']}")
    print(f"  Values written:      {summary['values_written']}")
    if rng:
        print(f"  Date range:          {rng['start']} → {rng['end']}")
    print("  Per metric:")
    for key, count in sorted(summary["metrics"].items()):
        print(f"    {key:18s} {count} days")


if __name__ == "__main__":
    main()
