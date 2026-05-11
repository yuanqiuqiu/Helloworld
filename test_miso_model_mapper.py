import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from MISO_SE_po_EMS_mapper import (
    build_mapping,
    build_case_mappings,
    build_case_mappings_for_dates,
    combine_unquoted_date_hours,
    expected_quarter_model,
    format_path_for_output,
    find_inputs_for_se_raw,
    find_se_raw_file,
    find_planned_outage_file,
    find_quarter_model,
    find_se_raw_files,
    normalize_se_time,
    parse_date_request,
    parse_planned_outage_timestamp,
    parse_se_datetime,
    parse_study_date,
    planned_outage_folder_for_date,
    planned_outage_hour_for_se_time,
    quarter_for_date,
)
from MISO_planned_outage_process import (
    active_oos_outages,
    active_planned_outages,
    baseline_branch_actions,
    read_planned_outage_xml,
)


class MisoModelMapperTests(unittest.TestCase):
    def test_parse_study_date_accepts_dates_and_se_filenames(self):
        self.assertEqual(parse_study_date("20260427"), date(2026, 4, 27))
        self.assertEqual(parse_study_date("2026-04-27"), date(2026, 4, 27))
        self.assertEqual(parse_study_date("miso_se_20260427-1800_AREVA.raw"), date(2026, 4, 27))
        self.assertEqual(parse_study_date(r"G:\Power\MISO\MISO_SE\2026\miso_se_20260427-1800_AREVA.raw"), date(2026, 4, 27))

    def test_parse_se_datetime_accepts_windows_paths(self):
        self.assertEqual(
            parse_se_datetime(r"G:\Power\MISO\MISO_SE\2026\miso_se_20260427-0500_AREVA.raw").strftime("%Y%m%d-%H%M"),
            "20260427-0500",
        )

    def test_parse_date_request_accepts_optional_hour(self):
        self.assertEqual(parse_date_request("20260414"), (date(2026, 4, 14), None))
        self.assertEqual(parse_date_request("20260414 00"), (date(2026, 4, 14), "0000"))
        self.assertEqual(parse_date_request("20260420 05"), (date(2026, 4, 20), "0500"))
        self.assertEqual(parse_date_request("20260418 018"), (date(2026, 4, 18), "1800"))

    def test_normalize_se_time_accepts_common_hour_forms(self):
        self.assertEqual(normalize_se_time("0"), "0000")
        self.assertEqual(normalize_se_time("05"), "0500")
        self.assertEqual(normalize_se_time("018"), "1800")
        self.assertEqual(normalize_se_time("1800"), "1800")

    def test_combine_unquoted_date_hours(self):
        self.assertEqual(
            combine_unquoted_date_hours(["20260414", "00", "20260418", "018", "20260420"]),
            ("20260414 00", "20260418 018", "20260420"),
        )

    def test_quarter_for_date_uses_expected_quarter_model_months(self):
        cases = {
            date(2026, 1, 10): (2025, 12, "Dec"),
            date(2026, 2, 28): (2025, 12, "Dec"),
            date(2026, 3, 1): (2026, 3, "Mar"),
            date(2026, 5, 31): (2026, 3, "Mar"),
            date(2026, 6, 1): (2026, 6, "Jun"),
            date(2026, 8, 31): (2026, 6, "Jun"),
            date(2026, 9, 1): (2026, 9, "Sep"),
            date(2026, 11, 30): (2026, 9, "Sep"),
            date(2026, 12, 1): (2026, 12, "Dec"),
        }
        for study_date, expected in cases.items():
            with self.subTest(study_date=study_date):
                self.assertEqual(quarter_for_date(study_date), expected)

    def test_expected_quarter_model_path_uses_yyyymm_folder_and_final_raw_name(self):
        model = expected_quarter_model(date(2026, 5, 11), "/models")

        self.assertEqual(model.folder, Path("/models/202603"))
        self.assertEqual(model.file_name, "Mar2026_final.raw")
        self.assertEqual(model.path, Path("/models/202603/Mar2026_final.raw"))

    def test_find_quarter_model_accepts_exact_final_raw_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "models"
            model_file = root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            model = find_quarter_model(date(2026, 4, 27), root)

            self.assertEqual(model.path, model_file)

    def test_find_se_raw_files_returns_four_files_in_hhmm_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MISO_SE"
            folder = root / "2026"
            folder.mkdir(parents=True)
            for hour in ("1800", "0000", "1200", "0600"):
                (folder / f"miso_se_20260427-{hour}_AREVA.raw").write_text("raw", encoding="utf-8")
            (folder / "miso_se_20260428-0000_AREVA.raw").write_text("raw", encoding="utf-8")
            (folder / "not_a_match.raw").write_text("raw", encoding="utf-8")

            files = find_se_raw_files(date(2026, 4, 27), root)

            self.assertEqual(
                [path.name for path in files],
                [
                    "miso_se_20260427-0000_AREVA.raw",
                    "miso_se_20260427-0600_AREVA.raw",
                    "miso_se_20260427-1200_AREVA.raw",
                    "miso_se_20260427-1800_AREVA.raw",
                ],
            )

    def test_find_se_raw_files_requires_four_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MISO_SE"
            folder = root / "2026"
            folder.mkdir(parents=True)
            (folder / "miso_se_20260427-1800_AREVA.raw").write_text("raw", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                find_se_raw_files(date(2026, 4, 27), root)

    def test_find_se_raw_file_returns_one_requested_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "MISO_SE"
            folder = root / "2026"
            folder.mkdir(parents=True)
            expected = folder / "miso_se_20260420-0500_AREVA.raw"
            expected.write_text("raw", encoding="utf-8")

            self.assertEqual(find_se_raw_file(date(2026, 4, 20), "0500", root), expected)

    def test_build_mapping_maps_se_date_to_quarter_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            model_root = temp_path / "Quarterly EMS Models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            se_root = temp_path / "MISO_SE"
            se_folder = se_root / "2026"
            se_folder.mkdir(parents=True)
            for hour in ("0000", "0600", "1200", "1800"):
                (se_folder / f"miso_se_20260427-{hour}_AREVA.raw").write_text("raw", encoding="utf-8")

            mapping = build_mapping(
                "miso_se_20260427-1800_AREVA.raw",
                quarter_model_root=model_root,
                se_root=se_root,
            )

            self.assertEqual(mapping.study_date, date(2026, 4, 27))
            self.assertEqual(mapping.quarter_model.path, model_file)
            self.assertEqual(len(mapping.se_raw_files), 4)

    def test_format_path_for_output_formats_windows_roots_with_backslashes(self):
        self.assertEqual(
            format_path_for_output(r"G:\Power\MISO\Quarterly EMS Models/202603/Mar2026_final.raw"),
            r"G:\Power\MISO\Quarterly EMS Models\202603\Mar2026_final.raw",
        )

    def test_parse_planned_outage_timestamp(self):
        self.assertEqual(
            parse_planned_outage_timestamp("2308_Planned_Outages_2026-04-07-04-50-00.xml").strftime("%Y-%m-%d %H:%M:%S"),
            "2026-04-07 04:50:00",
        )
        self.assertEqual(
            parse_planned_outage_timestamp("9999_Planned_Outages_2026-04-07-04-50-00.xml").strftime("%Y-%m-%d %H:%M:%S"),
            "2026-04-07 04:50:00",
        )

    def test_planned_outage_hour_uses_se_hour_plus_default_offset(self):
        se_time = parse_se_datetime("miso_se_20260427-0500_AREVA.raw")

        self.assertEqual(planned_outage_hour_for_se_time(se_time), 9)

    def test_planned_outage_folder_for_date_adds_yyyymm(self):
        self.assertEqual(
            planned_outage_folder_for_date(date(2026, 4, 14), "/outages"),
            Path("/outages/202604"),
        )
        self.assertEqual(
            planned_outage_folder_for_date(date(2026, 4, 14), "/outages/YYYYMM"),
            Path("/outages/202604"),
        )
        self.assertEqual(
            planned_outage_folder_for_date(date(2026, 4, 14), "/outages/202604"),
            Path("/outages/202604"),
        )

    def test_find_planned_outage_file_matches_adjusted_hour(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "202604"
            root.mkdir()
            target = root / "2308_Planned_Outages_2026-04-07-04-50-00.xml"
            target.write_text("<Outages />", encoding="utf-8")
            (root / "2308_Planned_Outages_2026-04-07-05-50-00.xml").write_text("<Outages />", encoding="utf-8")

            self.assertEqual(find_planned_outage_file("miso_se_20260427-0000_AREVA.raw", temp_dir), target)

    def test_find_planned_outage_file_allows_same_day_minutes_after_target_hour(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "202604"
            root.mkdir()
            target = root / "2308_Planned_Outages_2026-04-14-04-50-00.xml"
            target.write_text("<Outages />", encoding="utf-8")

            self.assertEqual(find_planned_outage_file("miso_se_20260414-0000_AREVA.raw", temp_dir), target)

    def test_find_planned_outage_file_falls_back_to_previous_hour(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "202604"
            root.mkdir()
            target = root / "2308_Planned_Outages_2026-04-14-08-50-00.xml"
            target.write_text("<Outages />", encoding="utf-8")
            (root / "2308_Planned_Outages_2026-04-14-07-50-00.xml").write_text("<Outages />", encoding="utf-8")
            (root / "2308_Planned_Outages_2026-04-14-10-50-00.xml").write_text("<Outages />", encoding="utf-8")

            self.assertEqual(find_planned_outage_file("miso_se_20260414-0500_AREVA.raw", temp_dir), target)

    def test_find_planned_outage_file_can_fall_back_to_previous_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "202604"
            root.mkdir()
            target = root / "2308_Planned_Outages_2026-04-13-23-50-00.xml"
            target.write_text("<Outages />", encoding="utf-8")
            (root / "2308_Planned_Outages_2026-04-14-01-50-00.xml").write_text("<Outages />", encoding="utf-8")

            self.assertEqual(find_planned_outage_file("miso_se_20260413-2000_AREVA.raw", temp_dir), target)

    def test_find_planned_outage_file_error_shows_available_hours(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "202604"
            root.mkdir()
            (root / "2308_Planned_Outages_2026-04-14-05-50-00.xml").write_text("<Outages />", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "at or before filename hour 04.*Available planned outage filename hours.*05"):
                find_planned_outage_file("miso_se_20260414-0000_AREVA.raw", temp_dir)

    def test_find_inputs_for_se_raw_returns_quarter_model_and_planned_outage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_root = root / "models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            outage_root = root / "outages"
            outage_folder = outage_root / "202604"
            outage_folder.mkdir(parents=True)
            outage_file = outage_folder / "2308_Planned_Outages_2026-04-07-09-50-00.xml"
            outage_file.write_text("<Outages />", encoding="utf-8")

            result = find_inputs_for_se_raw("miso_se_20260427-0500_AREVA.raw", model_root, outage_root)

            self.assertEqual(result.quarter_model.path, model_file)
            self.assertEqual(result.planned_outage_file, outage_file)

    def test_build_case_mappings_returns_se_outage_and_quarter_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_root = root / "models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            se_root = root / "se"
            se_folder = se_root / "2026"
            se_folder.mkdir(parents=True)
            for hour in ("0000", "0600", "1200", "1800"):
                (se_folder / f"miso_se_20260427-{hour}_AREVA.raw").write_text("raw", encoding="utf-8")

            outage_root = root / "outages"
            outage_folder = outage_root / "202604"
            outage_folder.mkdir(parents=True)
            for hour in ("0400", "1000", "1600", "2200"):
                (outage_folder / f"2308_Planned_Outages_2026-04-07-{hour[:2]}-50-00.xml").write_text(
                    "<Outages />",
                    encoding="utf-8",
                )

            result = build_case_mappings(
                "20260427",
                quarter_model_root=model_root,
                se_root=se_root,
                planned_outage_root=outage_root,
            )

            self.assertEqual(len(result), 4)
            self.assertTrue(all(item.quarter_model.path == model_file for item in result))
            self.assertEqual(result[0].planned_outage_file.name, "2308_Planned_Outages_2026-04-07-04-50-00.xml")

    def test_build_case_mappings_for_dates_accepts_multiple_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_root = root / "models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            se_root = root / "se"
            se_folder = se_root / "2026"
            se_folder.mkdir(parents=True)
            outage_root = root / "outages"
            outage_folder = outage_root / "202604"
            outage_folder.mkdir(parents=True)

            for day in ("20260414", "20260415"):
                for hour in ("0000", "0600", "1200", "1800"):
                    (se_folder / f"miso_se_{day}-{hour}_AREVA.raw").write_text("raw", encoding="utf-8")
                for hour in ("04", "10", "16", "22"):
                    (outage_folder / f"2308_Planned_Outages_2026-04-{day[-2:]}-{hour}-50-00.xml").write_text(
                        "<Outages />",
                        encoding="utf-8",
                    )

            result = build_case_mappings_for_dates(
                ["20260414", "20260415"],
                quarter_model_root=model_root,
                se_root=se_root,
                planned_outage_root=outage_root,
            )

            self.assertEqual(len(result), 8)
            self.assertEqual(result[0].se_time.strftime("%Y%m%d-%H%M"), "20260414-0000")
            self.assertEqual(result[-1].se_time.strftime("%Y%m%d-%H%M"), "20260415-1800")

    def test_build_case_mappings_for_dates_accepts_date_hour_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_root = root / "models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            se_root = root / "se"
            se_folder = se_root / "2026"
            se_folder.mkdir(parents=True)
            outage_root = root / "outages"
            outage_folder = outage_root / "202604"
            outage_folder.mkdir(parents=True)

            for day, se_time, outage_hour in (
                ("20260414", "0000", "04"),
                ("20260418", "1800", "22"),
                ("20260420", "0000", "04"),
                ("20260420", "0500", "09"),
            ):
                (se_folder / f"miso_se_{day}-{se_time}_AREVA.raw").write_text("raw", encoding="utf-8")
                (outage_folder / f"2308_Planned_Outages_2026-04-{day[-2:]}-{outage_hour}-50-00.xml").write_text(
                    "<Outages />",
                    encoding="utf-8",
                )

            result = build_case_mappings_for_dates(
                ["20260414 00", "20260418 018", "20260420 00", "20260420 05"],
                quarter_model_root=model_root,
                se_root=se_root,
                planned_outage_root=outage_root,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual([item.se_time.strftime("%Y%m%d-%H%M") for item in result], [
                "20260414-0000",
                "20260418-1800",
                "20260420-0000",
                "20260420-0500",
            ])

    def test_build_case_mappings_for_dates_accepts_unquoted_date_hour_pairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_root = root / "models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            se_root = root / "se"
            se_folder = se_root / "2026"
            se_folder.mkdir(parents=True)
            outage_root = root / "outages"
            outage_folder = outage_root / "202604"
            outage_folder.mkdir(parents=True)

            (se_folder / "miso_se_20260414-0000_AREVA.raw").write_text("raw", encoding="utf-8")
            (outage_folder / "2308_Planned_Outages_2026-04-14-04-50-00.xml").write_text("<Outages />", encoding="utf-8")

            result = build_case_mappings_for_dates(
                ["20260414", "00"],
                quarter_model_root=model_root,
                se_root=se_root,
                planned_outage_root=outage_root,
            )

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].se_time.strftime("%Y%m%d-%H%M"), "20260414-0000")

    def test_read_planned_outage_xml_and_filter_active_oos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_file = Path(temp_dir) / "2308_Planned_Outages_2026-04-07-04-50-00.xml"
            xml_file.write_text(
                """
<Outages>
  <Outage>
    <Outage_Request_ID>1</Outage_Request_ID>
    <Equipment_Request_Type>OOS</Equipment_Request_Type>
    <Equipment_Type>Line</Equipment_Type>
    <EMS_Equipment_Name>AB LINE</EMS_Equipment_Name>
    <EMS_Key>1</EMS_Key>
    <Planned_Start>2026-04-26 22:00:00</Planned_Start>
    <Planned_End>2026-04-27 01:00:00</Planned_End>
  </Outage>
  <Outage>
    <Outage_Request_ID>2</Outage_Request_ID>
    <Equipment_Request_Type>InSvrNo</Equipment_Request_Type>
    <Planned_Start>2026-04-26 22:00:00</Planned_Start>
    <Planned_End>2026-04-27 01:00:00</Planned_End>
  </Outage>
</Outages>
""",
                encoding="utf-8",
            )

            outages = read_planned_outage_xml(xml_file)
            active = active_oos_outages(xml_file, parse_se_datetime("miso_se_20260427-0000_AREVA.raw"))
            active_planned = active_planned_outages(xml_file, parse_se_datetime("miso_se_20260427-0000_AREVA.raw"))

            self.assertEqual(len(outages), 2)
            self.assertEqual(len(active), 1)
            self.assertEqual(len(active_planned), 2)
            self.assertEqual(str(active.iloc[0]["Outage_Request_ID"]), "1")

    def test_baseline_branch_actions_follow_outage_type_and_future_equipment_rules(self):
        mapped = pd.DataFrame(
            [
                {
                    "FromBusNum": 1,
                    "ToBusNum": 2,
                    "Circuit": "1",
                    "Equipment_Request_Type": "OOS",
                    "Priority": "",
                },
                {
                    "FromBusNum": 3,
                    "ToBusNum": 4,
                    "Circuit": "1",
                    "Equipment_Request_Type": "InSvrNo",
                    "Priority": "",
                },
                {
                    "FromBusNum": 5,
                    "ToBusNum": 6,
                    "Circuit": "1",
                    "Equipment_Request_Type": "OOS",
                    "Priority": "Future Equipment",
                },
            ]
        )
        future_retired = pd.DataFrame([{"FromBusNum": 7, "ToBusNum": 8, "Circuit": "1"}])

        actions = baseline_branch_actions(mapped, future_retired)

        self.assertEqual(
            actions[["FromBusNum", "ToBusNum", "TargetStatus"]].values.tolist(),
            [
                [1, 2, "Closed"],
                [3, 4, "Open"],
                [5, 6, "Open"],
                [7, 8, "Closed"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
