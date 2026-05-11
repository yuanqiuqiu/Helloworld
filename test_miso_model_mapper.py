import tempfile
import unittest
from datetime import date
from pathlib import Path

from miso_model_mapper import (
    build_expected_mapping,
    build_mapping,
    expected_quarter_model,
    format_path_for_output,
    find_quarter_model,
    find_se_raw_files,
    parse_se_datetime,
    parse_study_date,
    quarter_for_date,
)
from planned_outages import (
    active_oos_outages,
    find_inputs_for_se_raw,
    find_planned_outage_file,
    parse_planned_outage_timestamp,
    planned_outage_hour_for_se_time,
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

    def test_build_expected_mapping_does_not_require_existing_files(self):
        mapping = build_expected_mapping("20260511", quarter_model_root="/models", se_root="/se")

        self.assertEqual(mapping.quarter_model.path, Path("/models/202603/Mar2026_final.raw"))
        self.assertEqual([path.name for path in mapping.se_raw_files], [
            "miso_se_20260511-0000_AREVA.raw",
            "miso_se_20260511-0600_AREVA.raw",
            "miso_se_20260511-1200_AREVA.raw",
            "miso_se_20260511-1800_AREVA.raw",
        ])

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

    def test_planned_outage_hour_uses_se_hour_plus_default_offset(self):
        se_time = parse_se_datetime("miso_se_20260427-0500_AREVA.raw")

        self.assertEqual(planned_outage_hour_for_se_time(se_time), 9)

    def test_find_planned_outage_file_matches_adjusted_hour(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "2308_Planned_Outages_2026-04-07-04-50-00.xml"
            target.write_text("<Outages />", encoding="utf-8")
            (root / "2308_Planned_Outages_2026-04-07-05-50-00.xml").write_text("<Outages />", encoding="utf-8")

            self.assertEqual(find_planned_outage_file("miso_se_20260427-0000_AREVA.raw", root), target)

    def test_find_inputs_for_se_raw_returns_quarter_model_and_planned_outage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_root = root / "models"
            model_file = model_root / "202603" / "Mar2026_final.raw"
            model_file.parent.mkdir(parents=True)
            model_file.write_text("raw", encoding="utf-8")

            outage_root = root / "outages"
            outage_root.mkdir()
            outage_file = outage_root / "2308_Planned_Outages_2026-04-07-09-50-00.xml"
            outage_file.write_text("<Outages />", encoding="utf-8")

            result = find_inputs_for_se_raw("miso_se_20260427-0500_AREVA.raw", model_root, outage_root)

            self.assertEqual(result.quarter_model.path, model_file)
            self.assertEqual(result.planned_outage_file, outage_file)

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
    <Equipment_Request_Type>OOS</Equipment_Request_Type>
    <Planned_Start>2026-04-28 00:00:00</Planned_Start>
    <Planned_End>2026-04-28 01:00:00</Planned_End>
  </Outage>
</Outages>
""",
                encoding="utf-8",
            )

            records = read_planned_outage_xml(xml_file)
            active = active_oos_outages(records, parse_se_datetime("miso_se_20260427-0000_AREVA.raw"))

            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["Outage_Request_ID"], "1")


if __name__ == "__main__":
    unittest.main()
