"""A slot's intro card (FieldStation42's start_bump) and folders inside a list, on the Stations form. Run: python3 test_intro.py

A station made by a script (each hour: one show folder per show, picked at random, with a card as the hour starts) must open
on the Stations page and come back out of it unchanged when saved."""
import json
import unittest
from datetime import date

import schedules
import stationform as sf

SHOWS = ["Night Shift/After Dark/Futurama", "Night Shift/After Dark/The Simpsons (1989)"]


def scripted():
    late = {"start_bump": "Night Shift/~bumps/night", "tags": SHOWS, "random_tags": True}
    movie = {"start_bump": "Night Shift/~bumps/graveyard", "tags": "Night Shift/Graveyard"}
    weekday = {str(h): dict(late if h < 2 or h >= 20 else movie) for h in range(24)}
    weekend = {str(h): dict(late) for h in range(24)}
    return {"network_name": "Night Shift", "channel_number": 101, "network_type": "standard", "content_dir": sf.CONTENT_DIR,
            "off_air_video": sf.OFF_AIR_CLIP, "bump_dir": sf.OFF_CARDS, "wrapper_start_cards": "bump", "wrapper_end_cards": "bump",
            "wrapper_mid_cards": False, "schedule_increment": 30, "break_strategy": "standard", "commercial_free": False,
            "commercial_dir": "commercials", "day_templates": {"weekday": weekday, "weekend": weekend},
            **{d: "weekend" if d in ("friday", "saturday") else "weekday" for d in sf.DAYS}}


class Intro(unittest.TestCase):
    def test_a_scripted_station_opens_and_saves_back_unchanged(self):
        conf = scripted()
        form, why = sf.parse(conf)
        self.assertIsNone(why)
        monday = form["days"]["monday"]
        self.assertEqual(monday[0], {"from": 0, "to": 2, "lists": SHOWS, "intro": "Night Shift/~bumps/night"})
        self.assertEqual(monday[1]["intro"], "Night Shift/~bumps/graveyard")
        out = sf.to_conf(sf.validate(dict(form, schedule=schedules.from_legacy(form)), [], {}, None), conf, today=date(2026, 11, 10))
        for d in sf.DAYS:
            self.assertEqual(json.dumps(out["day_templates"][out[d]], sort_keys=True),
                             json.dumps(conf["day_templates"][conf[d]], sort_keys=True), d)
        self.assertEqual({k: v for k, v in out.items() if k not in ("day_templates",) + sf.DAYS},
                         {k: v for k, v in conf.items() if k not in ("day_templates",) + sf.DAYS})

    def test_an_intro_whose_folder_is_empty_is_left_out_of_the_hour(self):
        day = {"videos": [{"from": 0, "to": 24, "lists": ["Cartoons"], "intro": "Cards/morning"}], "commercials": [], "cards": []}
        self.assertEqual(schedules.hours_of(day)["5"], {"tags": "Cartoons", "start_bump": "Cards/morning"})
        self.assertNotIn("start_bump", schedules.hours_of(day, skip={"Cards/morning"})["5"])
        self.assertIn("Cards/morning", schedules.lists_of({"default": {d: day for d in sf.DAYS}, "seasons": {}, "events": []}))

    def test_a_path_stays_inside_the_lists(self):
        self.assertEqual(schedules.list_path(" Night Shift / After Dark ", "x"), "Night Shift/After Dark")
        for bad in ("../etc", "/etc", "A//B", "A/.hidden", "A\\B", "", None, "A/..", "A/"):
            with self.assertRaises(schedules.ScheduleError, msg=repr(bad)):
                schedules.list_path(bad, "x")

    def test_slots_the_form_still_cannot_hold_keep_the_station_read_only(self):
        for extra in ({"tags": "A", "random_tags": False}, {"tags": "A", "end_bump": "B"}, {"tags": "A", "start_bump": 5}):
            conf = scripted()
            conf["day_templates"]["weekday"]["3"] = extra
            self.assertIsNone(sf.parse(conf)[0], extra)


if __name__ == "__main__":
    unittest.main()
