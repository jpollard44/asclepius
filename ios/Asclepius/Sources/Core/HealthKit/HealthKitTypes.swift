import Foundation
import HealthKit

/// How a quantity type is aggregated into one value per local calendar day.
enum MetricAggregation {
    case sum
    /// Daily average; `includeMinMax` adds the day's min/max (heart rate).
    case average(includeMinMax: Bool)

    var statisticsOptions: HKStatisticsOptions {
        switch self {
        case .sum:
            return [.cumulativeSum]
        case .average(let includeMinMax):
            return includeMinMax
                ? [.discreteAverage, .discreteMin, .discreteMax]
                : [.discreteAverage]
        }
    }
}

/// One HealthKit quantity type the app syncs, with the backend metric key,
/// the HKUnit to read it in, and the unit label sent over the wire.
struct SyncedQuantityMetric {
    let key: String
    let identifier: HKQuantityTypeIdentifier
    let unit: HKUnit
    let unitLabel: String
    let aggregation: MetricAggregation
    /// Multiplier applied before upload (HealthKit's 0–1 fractions → percent).
    let scale: Double

    init(
        key: String,
        identifier: HKQuantityTypeIdentifier,
        unit: HKUnit,
        unitLabel: String,
        aggregation: MetricAggregation,
        scale: Double = 1
    ) {
        self.key = key
        self.identifier = identifier
        self.unit = unit
        self.unitLabel = unitLabel
        self.aggregation = aggregation
        self.scale = scale
    }

    var quantityType: HKQuantityType? {
        HKObjectType.quantityType(forIdentifier: identifier)
    }
}

enum HealthKitCatalog {
    private static let perMinute = HKUnit.count().unitDivided(by: .minute())
    private static let vo2MaxUnit = HKUnit.literUnit(with: .milli)
        .unitDivided(by: HKUnit.gramUnit(with: .kilo).unitMultiplied(by: .minute()))

    /// Every quantity metric synced to the backend, matching the server's
    /// metric keys and canonical units.
    static let quantityMetrics: [SyncedQuantityMetric] = [
        // Activity & fitness
        .init(key: "steps", identifier: .stepCount, unit: .count(),
              unitLabel: "count", aggregation: .sum),
        .init(key: "distance", identifier: .distanceWalkingRunning,
              unit: .meterUnit(with: .kilo), unitLabel: "km", aggregation: .sum),
        .init(key: "active_energy", identifier: .activeEnergyBurned,
              unit: .kilocalorie(), unitLabel: "kcal", aggregation: .sum),
        .init(key: "basal_energy", identifier: .basalEnergyBurned,
              unit: .kilocalorie(), unitLabel: "kcal", aggregation: .sum),
        .init(key: "exercise_time", identifier: .appleExerciseTime,
              unit: .minute(), unitLabel: "min", aggregation: .sum),
        .init(key: "stand_time", identifier: .appleStandTime,
              unit: .minute(), unitLabel: "min", aggregation: .sum),
        .init(key: "flights_climbed", identifier: .flightsClimbed,
              unit: .count(), unitLabel: "count", aggregation: .sum),
        .init(key: "vo2_max", identifier: .vo2Max,
              unit: vo2MaxUnit, unitLabel: "mL/kg·min",
              aggregation: .average(includeMinMax: false)),
        // Heart
        .init(key: "heart_rate", identifier: .heartRate,
              unit: perMinute, unitLabel: "bpm",
              aggregation: .average(includeMinMax: true)),
        .init(key: "resting_heart_rate", identifier: .restingHeartRate,
              unit: perMinute, unitLabel: "bpm",
              aggregation: .average(includeMinMax: false)),
        .init(key: "walking_heart_rate", identifier: .walkingHeartRateAverage,
              unit: perMinute, unitLabel: "bpm",
              aggregation: .average(includeMinMax: false)),
        .init(key: "hrv", identifier: .heartRateVariabilitySDNN,
              unit: .secondUnit(with: .milli), unitLabel: "ms",
              aggregation: .average(includeMinMax: false)),
        .init(key: "bp_systolic", identifier: .bloodPressureSystolic,
              unit: .millimeterOfMercury(), unitLabel: "mmHg",
              aggregation: .average(includeMinMax: false)),
        .init(key: "bp_diastolic", identifier: .bloodPressureDiastolic,
              unit: .millimeterOfMercury(), unitLabel: "mmHg",
              aggregation: .average(includeMinMax: false)),
        // Body & vitals
        .init(key: "body_mass", identifier: .bodyMass,
              unit: .gramUnit(with: .kilo), unitLabel: "kg",
              aggregation: .average(includeMinMax: false)),
        .init(key: "bmi", identifier: .bodyMassIndex,
              unit: .count(), unitLabel: "count",
              aggregation: .average(includeMinMax: false)),
        .init(key: "body_fat", identifier: .bodyFatPercentage,
              unit: .percent(), unitLabel: "%",
              aggregation: .average(includeMinMax: false), scale: 100),
        .init(key: "lean_body_mass", identifier: .leanBodyMass,
              unit: .gramUnit(with: .kilo), unitLabel: "kg",
              aggregation: .average(includeMinMax: false)),
        .init(key: "respiratory_rate", identifier: .respiratoryRate,
              unit: perMinute, unitLabel: "breaths/min",
              aggregation: .average(includeMinMax: false)),
        .init(key: "blood_oxygen", identifier: .oxygenSaturation,
              unit: .percent(), unitLabel: "%",
              aggregation: .average(includeMinMax: false), scale: 100),
        .init(key: "body_temperature", identifier: .bodyTemperature,
              unit: .degreeCelsius(), unitLabel: "degC",
              aggregation: .average(includeMinMax: false)),
    ]

    /// Everything the app asks permission to read.
    static var readTypes: Set<HKObjectType> {
        var types = Set<HKObjectType>()
        for metric in quantityMetrics {
            if let type = metric.quantityType {
                types.insert(type)
            }
        }
        if let sleep = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            types.insert(sleep)
        }
        types.insert(HKObjectType.workoutType())
        return types
    }

    /// Types whose new samples should trigger a background sync.
    static var observedTypes: [HKSampleType] {
        var types: [HKSampleType] = []
        for id: HKQuantityTypeIdentifier in [.stepCount, .heartRate, .activeEnergyBurned] {
            if let type = HKObjectType.quantityType(forIdentifier: id) {
                types.append(type)
            }
        }
        if let sleep = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            types.append(sleep)
        }
        types.append(HKObjectType.workoutType())
        return types
    }

    /// A readable activity name for a workout, matching what users see in
    /// the Fitness app.
    static func activityName(for type: HKWorkoutActivityType) -> String {
        switch type {
        case .running: return "Running"
        case .walking: return "Walking"
        case .hiking: return "Hiking"
        case .cycling: return "Cycling"
        case .swimming: return "Swimming"
        case .traditionalStrengthTraining: return "Strength Training"
        case .functionalStrengthTraining: return "Functional Training"
        case .highIntensityIntervalTraining: return "HIIT"
        case .yoga: return "Yoga"
        case .pilates: return "Pilates"
        case .rowing: return "Rowing"
        case .elliptical: return "Elliptical"
        case .stairClimbing: return "Stair Climbing"
        case .coreTraining: return "Core Training"
        case .flexibility: return "Flexibility"
        case .dance: return "Dance"
        case .kickboxing: return "Kickboxing"
        case .martialArts: return "Martial Arts"
        case .basketball: return "Basketball"
        case .soccer: return "Soccer"
        case .tennis: return "Tennis"
        case .golf: return "Golf"
        case .climbing: return "Climbing"
        case .jumpRope: return "Jump Rope"
        case .crossTraining: return "Cross Training"
        case .mixedCardio: return "Mixed Cardio"
        case .cooldown: return "Cooldown"
        case .mindAndBody: return "Mind & Body"
        case .preparationAndRecovery: return "Recovery"
        case .other: return "Workout"
        default: return "Workout"
        }
    }
}
