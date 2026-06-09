#!/usr/bin/env python3
"""Generate a small synthetic Apple Health `export.xml` for testing Asclepius.

This produces a realistic-looking export with steps, heart rate, HRV, sleep,
weight, blood oxygen, and workouts over the past N days — so you can try the
app end-to-end without exporting your real data.

Usage:
    python scripts/generate_sample_export.py [days] [output_path]
"""
import math
import random
import sys
from datetime import datetime, timedelta, timezone


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    out = sys.argv[2] if len(sys.argv) > 2 else "data/sample_export.xml"

    tz = timezone(timedelta(hours=-8))
    today = datetime.now(tz).replace(hour=12, minute=0, second=0, microsecond=0)
    records: list[str] = []

    def rec(rtype, value, start, unit, end=None):
        end = end or start
        records.append(
            f'  <Record type="{rtype}" sourceName="Apple Watch" unit="{unit}" '
            f'creationDate="{iso(start)}" startDate="{iso(start)}" '
            f'endDate="{iso(end)}" value="{value}"/>'
        )

    base_weight = 78.0
    for d in range(days, 0, -1):
        day = today - timedelta(days=d)
        seasonal = math.sin(d / 14.0)  # gentle multi-week wave

        # Activity
        steps = int(max(1500, random.gauss(8500 + seasonal * 1500, 2200)))
        rec("HKQuantityTypeIdentifierStepCount", steps, day.replace(hour=20), "count")
        rec("HKQuantityTypeIdentifierActiveEnergyBurned",
            int(max(150, random.gauss(520 + seasonal * 80, 120))), day.replace(hour=20), "kcal")
        rec("HKQuantityTypeIdentifierAppleExerciseTime",
            int(max(0, random.gauss(35, 18))), day.replace(hour=20), "min")
        rec("HKQuantityTypeIdentifierDistanceWalkingRunning",
            round(steps / 1350.0, 2), day.replace(hour=20), "km")

        # Heart — resting HR trends gently down as fitness improves
        rhr = round(random.gauss(60 - (days - d) / days * 4 - seasonal, 2.5), 0)
        rec("HKQuantityTypeIdentifierRestingHeartRate", int(rhr), day.replace(hour=7), "count/min")
        rec("HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
            round(random.gauss(48 + seasonal * 6, 8), 1), day.replace(hour=3), "ms")
        for h in (9, 13, 18):
            rec("HKQuantityTypeIdentifierHeartRate",
                int(random.gauss(75, 12)), day.replace(hour=h), "count/min")
        if d % 7 == 0:
            rec("HKQuantityTypeIdentifierVO2Max", round(random.gauss(42, 1.5), 1),
                day.replace(hour=18), "mL/min·kg")

        # Body & vitals
        base_weight += random.gauss(-0.01, 0.15)
        rec("HKQuantityTypeIdentifierBodyMass", round(base_weight, 1), day.replace(hour=8), "kg")
        rec("HKQuantityTypeIdentifierOxygenSaturation",
            round(random.uniform(0.95, 0.99), 3), day.replace(hour=3), "%")
        rec("HKQuantityTypeIdentifierRespiratoryRate",
            round(random.gauss(14, 1.2), 1), day.replace(hour=3), "count/min")

        # Sleep — a session from the previous night into this morning
        sleep_start = (day - timedelta(days=0)).replace(hour=23) - timedelta(days=1)
        total = max(4.0, random.gauss(7.2 + seasonal * 0.5, 0.9))
        cursor = sleep_start
        stages = [("Core", total * 0.55), ("Deep", total * 0.18),
                  ("REM", total * 0.22), ("Awake", total * 0.05)]
        random.shuffle(stages)
        for name, hrs in stages:
            seg_end = cursor + timedelta(hours=hrs)
            records.append(
                f'  <Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                f'sourceName="Apple Watch" '
                f'startDate="{iso(cursor)}" endDate="{iso(seg_end)}" '
                f'value="HKCategoryValueSleepAnalysisAsleep{name}"/>'
            )
            cursor = seg_end

        # Workouts a few times a week
        if random.random() < 0.45:
            activity = random.choice(["Running", "Cycling", "FunctionalStrengthTraining", "Walking"])
            dur = round(random.uniform(25, 70), 1)
            dist = round(dur / 6.0, 2) if activity in ("Running", "Cycling", "Walking") else ""
            start = day.replace(hour=18)
            stats = ""
            if dist:
                stats += (f'\n    <WorkoutStatistics type="HKQuantityTypeIdentifier'
                          f'DistanceWalkingRunning" sum="{dist}" unit="km"/>')
            stats += (f'\n    <WorkoutStatistics type="HKQuantityTypeIdentifier'
                      f'ActiveEnergyBurned" sum="{int(dur * 9)}" unit="kcal"/>')
            records.append(
                f'  <Workout workoutActivityType="HKWorkoutActivityType{activity}" '
                f'duration="{dur}" durationUnit="min" sourceName="Apple Watch" '
                f'startDate="{iso(start)}" endDate="{iso(start + timedelta(minutes=dur))}">'
                f'{stats}\n  </Workout>'
            )

    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="en_US">\n'
        f'  <ExportDate value="{iso(today)}"/>\n'
        '  <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale" '
        'HKCharacteristicTypeIdentifierDateOfBirth="1990-05-01" '
        'HKCharacteristicTypeIdentifierBloodType="HKBloodTypeOPositive"/>\n'
    )
    import os
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        f.write(header)
        f.write("\n".join(records))
        f.write("\n</HealthData>\n")
    print(f"Wrote {out} with {len(records)} records over {days} days.")


if __name__ == "__main__":
    main()
