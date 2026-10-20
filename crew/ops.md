---
title: Ops, morning brief
schedule: *-*-* 06:30
model: sonnet
verbs: today agenda get list
web: api.open-meteo.com geocoding-api.open-meteo.com
budget: 0.40
timeout: 600
notes: today list get stats agenda
---
The captain reads this with the first coffee. Give the captain the day in under a minute of reading.

1. Run `agenda` (today). It names the place for the weather and why, lists what is scheduled, the lines yesterday's
   notes left for today, every open task (overdue ones marked; older ones without a due date on one line) and
   recent trips.
2. If a scheduled item or task is unclear from its title, `get <id>` it; no more than three gets.
3. Weather: for the agenda's "Weather place", never one you pick yourself. (Its rule: the first stop of a trip
   running today; else the newest trip started in the last three days, if it has not ended; else home, a "home"
   settings value or the city of the captain's zone, `LCARS_TZ`; "none" when there is neither: then skip the
   forecast and say so in one line.) If it gives lat and lon, use them; else geocode the place. Then fetch the forecast:
   https://geocoding-api.open-meteo.com/v1/search?name=<place>&count=1
   https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,weather_code&hourly=precipitation_probability&forecast_days=1&timezone=auto

Report, in this order:
- **Weather** at the place: one line, whole °C, rain chance and when, wind if it matters for the plans.
- **Today**: the scheduled items in time order, local times, with ids.
- **For today, from yesterday's notes**: the agenda's lines of that heading, as they are, with the entry id.
- **Tasks**: overdue first, then at most five open ones worth doing today, with ids. Say how many others are open.
  The agenda's older tasks go on one line, as "3 older tasks: #2722 Budget review, ...", never one each; on a Monday
  (the agenda says so) ask once whether they still matter.
- One line on anything that clashes (two things at once, a hike with rain coming).
Leave out a section that is empty. URGENT only for something overdue that has a cost today.
