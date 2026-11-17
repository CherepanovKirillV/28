export const PROFILE_FIELD_KEYS = [
  "chronotype",
  "weekday_bedtime",
  "weekday_wake_time",
  "sleep_duration",
  "social_jetlag",
  "activity_level",
  "sitting_hours",
  "training_days",
  "work_from_home",
  "phone_before_sleep",
  "movement_index",
] as const;

export type ProfileFieldKey = (typeof PROFILE_FIELD_KEYS)[number];
export type ProfileValue = string | number | "unknown";

export interface ProfileField {
  value: ProfileValue;
  confidence: number;
}

export type Case3Profile = Record<ProfileFieldKey, ProfileField>;

export interface Case3Hypothesis {
  text: string;
  confidence: number;
}

export interface Case3WeekAnswer {
  week_id: string;
  profile: Case3Profile;
  hypotheses: [Case3Hypothesis, Case3Hypothesis, Case3Hypothesis];
}

export interface Case3Answers {
  answers: Case3WeekAnswer[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isConfidence = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;

const isProfileValue = (value: unknown): value is ProfileValue =>
  typeof value === "string" || (typeof value === "number" && Number.isFinite(value));

export function assertCase3Answers(payload: unknown): asserts payload is Case3Answers {
  if (!isRecord(payload) || !Array.isArray(payload.answers) || payload.answers.length === 0) {
    throw new Error("Case3Answers: требуется непустой массив answers");
  }

  payload.answers.forEach((answer, answerIndex) => {
    if (!isRecord(answer) || typeof answer.week_id !== "string" || !answer.week_id) {
      throw new Error(`answers[${answerIndex}].week_id: требуется строка`);
    }
    const profile = answer.profile;
    if (!isRecord(profile)) {
      throw new Error(`answers[${answerIndex}].profile: требуется объект`);
    }

    PROFILE_FIELD_KEYS.forEach((key) => {
      const field = profile[key];
      if (!isRecord(field) || !isProfileValue(field.value) || !isConfidence(field.confidence)) {
        throw new Error(`answers[${answerIndex}].profile.${key}: неверный value/confidence`);
      }
    });

    if (!Array.isArray(answer.hypotheses) || answer.hypotheses.length !== 3) {
      throw new Error(`answers[${answerIndex}].hypotheses: требуется ровно 3 элемента`);
    }
    answer.hypotheses.forEach((hypothesis, hypothesisIndex) => {
      if (
        !isRecord(hypothesis) ||
        typeof hypothesis.text !== "string" ||
        !hypothesis.text.trim() ||
        !isConfidence(hypothesis.confidence)
      ) {
        throw new Error(
          `answers[${answerIndex}].hypotheses[${hypothesisIndex}]: неверный text/confidence`,
        );
      }
    });
  });
}
