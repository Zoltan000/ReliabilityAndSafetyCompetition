# Which Parts Give Advance Warning Before They Fail? (Plain-Language Summary)

**For the technical version** (z-scores, effect sizes, statistical tests): see §5-§8 of
[`failure_interactions_findings.md`](failure_interactions_findings.md). This file is
the same findings, no jargon, for anyone who wants the short version.

**What we did:** for each of the 7 things that can break on a conveyor, we checked 16
different measurements (temperature, vibration, electricity use, weather, how much
weight it's carrying, etc.) to see: *does anything act weird in the weeks before this
part breaks?* Like checking if a car makes a funny noise before the engine dies.

## Part by part

- **Motor-reducer — gives lots of warning.** In the ~2 months before it breaks, it
  gradually runs hotter, pulls more electrical current, and vibrates more — all at the
  same time, all creeping up steadily, not a sudden jump. Like a car engine that
  slowly starts running rougher and hotter before it finally quits. This is the part
  where watching the sensors would actually help you see trouble coming.
  (See [`precursor_trajectory_motor_reducer.png`](precursor_trajectory_motor_reducer.png).)

- **Belt — gives a little warning.** Only one thing changes: it starts vibrating more
  in the weeks before it fails. Same slow build-up pattern as the motor, just one clue
  instead of several. (See [`precursor_trajectory_conveyor_belt.png`](precursor_trajectory_conveyor_belt.png).)

- **Bearings — gives basically no warning.** Nothing we measured budges before a
  bearing fails. It just breaks, with no lead-up we can detect from these sensors.
  This is already known to be the hardest part to predict this way.

- **Controller PC — also no real warning.** Fails more or less randomly; nothing ramps
  up beforehand.

- **Speed sensor and Control software — looked interesting, but it was a false lead.**
  It first looked like "the weather gets colder right before these fail." We checked,
  and that's not real: it's not that cold weather breaks these parts. It's that both
  of these parts just happen to fail more often in autumn for some other, unrelated
  reason, and autumn is also when temperatures are naturally dropping. So it's a
  coincidence of the calendar, not a useful warning sign.

- **Contactor — too rare to say anything.** Only 12 failures across the entire fleet's
  20-year history, not enough to reliably tell if there's a warning sign or not.

## One more thing worth knowing

Right after any part gets repaired, its readings actually drop *below* normal for a
while — because the brand-new replacement runs cooler and smoother than the old
worn-out part it just replaced. Like a new phone battery lasting longer than the old
one it replaced. That's a good sign, not a problem, and it happens for essentially
every component, not just the ones with a warning sign beforehand.

## Bottom line

If you had to pick where advance warning is actually usable: **motor-reducer first**
(strong, multi-signal, ~2-month lead time), **belt second** (one useful clue,
vibration), and **bearings/controller PC are basically unpredictable** from these
sensors — they just fail when they fail, with no build-up to watch for.
