import unittest

from post_render_tool.timecode import Timecode, unwrap_timecode_frames


class TestTimecodeParse(unittest.TestCase):
    def test_24fps_non_drop(self):
        tc = Timecode.parse("09:44:23:22", 24.0)
        self.assertEqual((tc.hours, tc.minutes, tc.seconds, tc.frames), (9, 44, 23, 22))
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (24, 1))

    def test_25fps_non_drop(self):
        tc = Timecode.parse("00:00:01:24", 25.0)
        self.assertEqual(tc.frames, 24)
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (25, 1))

    def test_50fps_non_drop(self):
        # take_4 production case
        tc = Timecode.parse("10:00:00:49", 50.0)
        self.assertEqual(tc.frames, 49)
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (50, 1))

    def test_2997_drop_frame(self):
        tc = Timecode.parse("09:44:23;22", 29.97)
        self.assertTrue(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (30000, 1001))

    def test_5994_drop_frame(self):
        tc = Timecode.parse("01:00:00;30", 59.94)
        self.assertTrue(tc.drop_frame)

    def test_23976_non_drop(self):
        tc = Timecode.parse("00:01:00:00", 23.976)
        self.assertFalse(tc.drop_frame)
        self.assertEqual((tc.rate_num, tc.rate_den), (24000, 1001))

    def test_dot_separator_accepted(self):
        # Disguise CSV uses . to separate frames
        tc = Timecode.parse("09:44:23.22", 24.0)
        self.assertEqual(tc.frames, 22)

    def test_str_round_trip_non_drop(self):
        self.assertEqual(str(Timecode.parse("09:44:23:22", 24.0)), "09:44:23:22")

    def test_str_round_trip_drop(self):
        self.assertEqual(str(Timecode.parse("09:44:23;22", 29.97)), "09:44:23;22")

    def test_unsupported_fps_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Timecode.parse("00:00:00:00", 48.0)
        self.assertIn("48", str(ctx.exception))

    def test_fullwidth_digits_rejected(self):
        # \d would match fullwidth; we use [0-9] to keep ASCII-only.
        with self.assertRaises(ValueError):
            Timecode.parse("０９:４４:２３:２２", 24.0)

    def test_semicolon_with_non_drop_fps_rejects(self):
        with self.assertRaises(ValueError):
            Timecode.parse("00:00:00;00", 24.0)

    def test_colon_with_drop_fps_rejects(self):
        with self.assertRaises(ValueError):
            Timecode.parse("00:00:00:00", 29.97)


class TestTimecodeValidation(unittest.TestCase):
    def test_hours_out_of_range(self):
        with self.assertRaises(ValueError):
            Timecode(hours=24, minutes=0, seconds=0, frames=0,
                     drop_frame=False, rate_num=24, rate_den=1)

    def test_minutes_out_of_range(self):
        with self.assertRaises(ValueError):
            Timecode.parse("00:60:00:00", 24.0)

    def test_seconds_out_of_range(self):
        with self.assertRaises(ValueError):
            Timecode.parse("00:00:60:00", 24.0)

    def test_frames_out_of_range_50fps(self):
        with self.assertRaises(ValueError):
            Timecode.parse("00:00:00:50", 50.0)

    def test_frames_out_of_range_24fps(self):
        with self.assertRaises(ValueError):
            Timecode.parse("00:00:00:24", 24.0)

    def test_dropframe_illegal_label_2997(self):
        # 00:01:00;00 and ;01 are dropped at non-10th minute boundary.
        with self.assertRaises(ValueError):
            Timecode.parse("00:01:00;00", 29.97)
        with self.assertRaises(ValueError):
            Timecode.parse("00:01:00;01", 29.97)

    def test_dropframe_legal_label_2997_first_valid(self):
        # 00:01:00;02 is the first valid label of minute 1.
        Timecode.parse("00:01:00;02", 29.97)  # no raise

    def test_dropframe_legal_label_2997_tenth_minute(self):
        # 00:10:00;00 is legal: 10-minute boundary has no drop.
        Timecode.parse("00:10:00;00", 29.97)  # no raise

    def test_dropframe_illegal_label_5994(self):
        # 59.94 drops 4 labels per non-10th minute.
        for ff in range(4):
            with self.assertRaises(ValueError):
                Timecode.parse(f"00:01:00;{ff:02d}", 59.94)

    def test_dropframe_legal_label_5994_first_valid(self):
        Timecode.parse("00:01:00;04", 59.94)  # no raise

    def test_direct_construction_runs_validation(self):
        # Bypassing parse() must still validate (DataAsset roundtrip path).
        with self.assertRaises(ValueError):
            Timecode(hours=0, minutes=1, seconds=0, frames=0,
                     drop_frame=True, rate_num=30000, rate_den=1001)


class TestTimecodeToFrames(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(Timecode.parse("00:00:00:00", 24.0).to_frames(), 0)

    def test_one_second_24fps(self):
        self.assertEqual(Timecode.parse("00:00:01:00", 24.0).to_frames(), 24)

    def test_one_minute_50fps(self):
        self.assertEqual(Timecode.parse("00:01:00:00", 50.0).to_frames(), 50 * 60)

    def test_one_hour_24fps(self):
        self.assertEqual(Timecode.parse("01:00:00:00", 24.0).to_frames(), 24 * 60 * 60)

    def test_2997_drop_one_minute(self):
        # NTSC drop-frame, Bevin standard formula:
        # nominal_30fps(00:01:00;02) = 1*60*30 + 2 = 1802
        # dropFrames = 2 * (totalMinutes - totalMinutes//10) = 2 * (1 - 0) = 2
        # frame_index = 1802 - 2 = 1800
        # (00:01:00;02 is the next continuous frame after 00:00:59;29 = 1799)
        self.assertEqual(Timecode.parse("00:01:00;02", 29.97).to_frames(), 1800)

    def test_2997_drop_ten_minutes(self):
        # 00:10:00;00 is a 10-minute boundary (no drop at this minute itself)
        # nominal = 600*30 = 18000, drops = 2*(10 - 1) = 18, frame_index = 17982
        self.assertEqual(Timecode.parse("00:10:00;00", 29.97).to_frames(), 17982)

    def test_2997_drop_one_hour(self):
        # 1 hour @ 29.97 DF: nominal = 3600*30 = 108000;
        # drops = 2*(60 - 6) = 108; frame_index = 107892.
        self.assertEqual(Timecode.parse("01:00:00;00", 29.97).to_frames(), 107892)

    def test_5994_drop_one_minute(self):
        # 59.94 DF: nominal_fps = 60, drop_count = 4.
        # 00:01:00;04 → nominal = 60*60 + 4 = 3604; drops = 4*(1 - 0) = 4; index = 3600.
        self.assertEqual(Timecode.parse("00:01:00;04", 59.94).to_frames(), 3600)

    def test_5994_drop_one_hour(self):
        # nominal = 3600*60 = 216000; drops = 4*(60 - 6) = 216; index = 215784.
        self.assertEqual(Timecode.parse("01:00:00;00", 59.94).to_frames(), 215784)


class TestUnwrapAcrossMidnight(unittest.TestCase):
    def test_no_wrap_returns_actual_delta(self):
        first = Timecode.parse("23:59:58:00", 24.0)
        later = Timecode.parse("23:59:59:23", 24.0)
        # 1 second 23 frames = 24 + 23 = 47 frames
        self.assertEqual(unwrap_timecode_frames(first, later), 47)

    def test_wrap_at_midnight_24fps(self):
        first = Timecode.parse("23:59:58:00", 24.0)
        # cross 00:00:00:00, actual delta = 2 seconds 1 frame = 49 frames
        later = Timecode.parse("00:00:00:01", 24.0)
        self.assertEqual(unwrap_timecode_frames(first, later), 49)

    def test_wrap_at_midnight_50fps(self):
        first = Timecode.parse("23:59:59:48", 50.0)
        later = Timecode.parse("00:00:00:02", 50.0)
        # actual delta = 4 frames (23:59:59:48 → 49 → 00:00:00:00 → 01 → 02)
        self.assertEqual(unwrap_timecode_frames(first, later), 4)

    def test_24h_constant_2997_drop(self):
        # 24h @ 29.97 DF wrap value = 144 ten-minute blocks × (30*600 - 2*9)
        # = 144 × 17982 = 2,589,408
        from post_render_tool.timecode import _frames_per_24h
        self.assertEqual(_frames_per_24h(30000, 1001, True), 2_589_408)

    def test_24h_constant_2997_non_drop_24fps(self):
        from post_render_tool.timecode import _frames_per_24h
        self.assertEqual(_frames_per_24h(24, 1, False), 24 * 24 * 3600)

    def test_unwrap_none_first_raises(self):
        with self.assertRaises(ValueError):
            unwrap_timecode_frames(None, Timecode.parse("00:00:00:00", 24.0))

    def test_unwrap_none_later_raises(self):
        with self.assertRaises(ValueError):
            unwrap_timecode_frames(Timecode.parse("00:00:00:00", 24.0), None)

    def test_unwrap_mismatched_rates_raises(self):
        with self.assertRaises(ValueError):
            unwrap_timecode_frames(
                Timecode.parse("00:00:00:00", 24.0),
                Timecode.parse("00:00:00:00", 25.0),
            )


if __name__ == "__main__":
    unittest.main()
