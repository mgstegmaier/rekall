"""The one check for the calendar watch's diff. No network.

Run: cd cos && python3 test_watch.py
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("watch", Path(__file__).with_name("calendar-watch.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

a = {"title": "QVAL", "start": "14:00", "attendees": ["Jeffrey Gottlieb", "Michael Stegmaier"]}
b = {"title": "QVAL", "start": "15:00", "attendees": ["Jeffrey Gottlieb", "Michael Stegmaier"]}
c = {"title": "QVAL", "start": "14:00", "attendees": ["Brent Danberg", "Jeffrey Gottlieb", "Michael Stegmaier"]}

assert w.diff({"1": a}, {"1": a}) == ([], [], [])                 # quiet run
assert w.diff({}, {"1": a}) == (["1"], [], [])                    # new meeting
assert w.diff({"1": a}, {"1": b}) == ([], ["1"], [])              # moved
assert w.diff({"1": a}, {"1": c}) == ([], ["1"], [])              # gained a person
assert w.diff({"1": a}, {}) == ([], [], ["1"])                    # cancelled
assert w.signature({"title": "X", "start": "09:00", "attendees": ["A"], "body": "ignored", "id": "z"}) == \
    {"title": "X", "start": "09:00", "attendees": ["A"]}          # body changes never trigger

print("ok: calendar diff holds")
