export interface ServiceStatus {
  team: string;
  status: string;
}

export interface RunRequest {
  case: number;
  dataset_code: string;
}

export type ProfileValue = string | number | boolean;

export interface ProfileField {
  value: ProfileValue;
  confidence: number;
}

export interface Case3Profile {
  chronotype: ProfileField;
  weekday_bedtime: ProfileField;
  weekday_wake_time: ProfileField;
  average_sleep_hours: ProfileField;
  social_jetlag: ProfileField;
  activity_level: ProfileField;
  sedentary_hours: ProfileField;
  training_days: ProfileField;
  works_from_home: ProfileField;
  phone_before_sleep: ProfileField;
  movement_index: ProfileField;
}

export interface Case3Hypothesis {
  text: string;
  confidence: number;
}

export interface Case3Week {
  record_id: string;
  profile: Case3Profile;
  hypotheses: [Case3Hypothesis, Case3Hypothesis, Case3Hypothesis];
}

export interface RunResponse {
  weeks: Case3Week[];
}

