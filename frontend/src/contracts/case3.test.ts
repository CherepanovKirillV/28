import { describe, expect, it } from "vitest";

import mock from "../../public/mock/case3-answers.json";
import { assertCase3Answers, PROFILE_FIELD_KEYS } from "./case3";

describe("Case3Answers contract", () => {
  it("принимает phase-0 mock", () => {
    expect(() => assertCase3Answers(mock)).not.toThrow();
    expect(Object.keys(mock.answers[0].profile)).toEqual([...PROFILE_FIELD_KEYS]);
  });

  it("отклоняет ответ без трёх гипотез", () => {
    const broken: unknown = {
      ...mock,
      answers: [{ ...mock.answers[0], hypotheses: mock.answers[0].hypotheses.slice(0, 2) }],
    };

    expect(() => assertCase3Answers(broken)).toThrow("ровно 3");
  });

  it("отклоняет confidence вне диапазона 0..1", () => {
    const broken = structuredClone(mock);
    broken.answers[0].profile.chronotype.confidence = 1.5;

    expect(() => assertCase3Answers(broken)).toThrow("chronotype");
  });
});
