import mock from "../public/mock/case3-answers.json";
import { assertCase3Answers, PROFILE_FIELD_KEYS } from "./contracts/case3";

assertCase3Answers(mock);

function App() {
  return (
    <main>
      <h1>Sain Case 3 — фаза 0</h1>
      <p>React-проект запущен. Контракт mock JSON валиден.</p>
      <dl>
        <dt>Ответов недель</dt>
        <dd>{mock.answers.length}</dd>
        <dt>Полей профиля</dt>
        <dd>{PROFILE_FIELD_KEYS.length}</dd>
        <dt>Гипотез</dt>
        <dd>{mock.answers[0].hypotheses.length}</dd>
      </dl>
    </main>
  );
}

export default App;
