import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, runCase } from "./api";
import type { Case3Hypothesis, Case3Profile, Case3Week, ProfileField, RunResponse } from "./api";
import "./App.css";
import "./visual-fixes.css";

type Group = "top" | "left" | "right" | "bottom";
type Source = "wearable" | "phone" | "smart_home";
type MetricConfig = {
  key: keyof Case3Profile;
  group: Group;
  label: string;
  description: string;
  sources: { key: Source; label: string }[];
  format: (value: ProfileField["value"]) => string;
};

const sourceLabels: Record<Source, string> = {
  wearable: "Носимое",
  phone: "Телефон",
  smart_home: "Умный дом",
};

const booleanLabel = (value: ProfileField["value"]) => {
  if (value === true || value === "yes" || value === "Да") return "Да";
  if (value === false || value === "no" || value === "Нет") return "Нет";
  return String(value);
};
const valueFromMap = (value: ProfileField["value"], map: Record<string, string>) =>
  map[String(value)] ?? String(value);

const metricConfig: MetricConfig[] = [
  { key: "phone_before_sleep", group: "top", label: "Телефон перед сном", description: "Использование телефона перед началом ночного сна за эту неделю.", sources: [{ key: "phone", label: "Телефон" }], format: booleanLabel },
  { key: "chronotype", group: "left", label: "Хронотип", description: "Определяется по времени сна и стабильности пробуждения в течение недели.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "phone", label: "Телефон" }], format: (value) => valueFromMap(value, { early: "Ранний", intermediate: "Промежуточный", late: "Поздний" }) },
  { key: "weekday_bedtime", group: "left", label: "Время отбоя в будни", description: "Расчётное время начала ночного сна с понедельника по пятницу.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "phone", label: "Телефон" }], format: String },
  { key: "weekday_wake_time", group: "left", label: "Время подъёма в будни", description: "Расчётное время пробуждения в рабочие дни.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "phone", label: "Телефон" }], format: String },
  { key: "average_sleep_hours", group: "left", label: "Длительность сна", description: "Средняя продолжительность ночного сна за семь дней.", sources: [{ key: "wearable", label: "Носимое устройство" }], format: (value) => typeof value === "number" ? `${String(value).replace(".", ",")} ч` : String(value) },
  { key: "social_jetlag", group: "left", label: "Социальный джетлаг", description: "Есть ли заметный сдвиг режима сна между буднями и выходными.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "phone", label: "Телефон" }], format: booleanLabel },
  { key: "activity_level", group: "right", label: "Уровень активности", description: "Сводная оценка бытового движения и шагов в течение суток.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "phone", label: "Телефон" }], format: (value) => valueFromMap(value, { low: "Низкий", medium: "Средний", high: "Высокий" }) },
  { key: "sedentary_hours", group: "right", label: "Часы сидя", description: "Среднее малоподвижное время в течение дня.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "smart_home", label: "Умный дом" }], format: (value) => valueFromMap(value, { lt6: "Меньше 6 ч", "<6": "Меньше 6 ч", "6to9": "6–9 ч", "6-9": "6–9 ч", gt9: "Больше 9 ч", ">9": "Больше 9 ч" }) },
  { key: "training_days", group: "right", label: "Дни тренировок", description: "Количество дней за неделю с выраженной физической нагрузкой.", sources: [{ key: "wearable", label: "Носимое устройство" }], format: (value) => valueFromMap(value, { "0": "0 дней", "1to2": "1–2 дня", "1-2": "1–2 дня", "3plus": "3 и больше", "3+": "3 и больше" }) },
  { key: "movement_index", group: "right", label: "Индекс движения", description: "Сводный индекс подвижности с учётом шагов и пауз в сидении.", sources: [{ key: "wearable", label: "Носимое устройство" }, { key: "phone", label: "Телефон" }, { key: "smart_home", label: "Умный дом" }], format: (value) => valueFromMap(value, { below50: "Меньше 50", "<50": "Меньше 50", "50to70": "От 50 до 70", "50-70": "От 50 до 70", "70to85": "От 70 до 85", "70-85": "От 70 до 85", above85: "85 и больше", ">=85": "85 и больше" }) },
  { key: "works_from_home", group: "bottom", label: "Работа из дома", description: "Вероятность удалённой работы по дневным перемещениям и утреннему распорядку.", sources: [{ key: "smart_home", label: "Умный дом" }, { key: "phone", label: "Телефон" }], format: booleanLabel },
];

const clampConfidence = (value: number) => Math.max(0, Math.min(1, value));
const isUnknown = (field?: ProfileField) => !field || field.value === null || field.value === undefined || String(field.value).trim().toLowerCase() === "unknown" || String(field.value).trim() === "";

function getApiError(error: unknown) {
  if (error instanceof ApiError) {
    return typeof error.body === "object" && error.body && "detail" in error.body
      ? String((error.body as { detail: unknown }).detail)
      : `Сервер ответил с кодом ${error.status}`;
  }
  return error instanceof Error ? error.message : "Не удалось получить данные";
}

function computeProgress(week: Case3Week) {
  const groups: Record<Group, number[]> = { top: [], left: [], right: [], bottom: [] };
  metricConfig.forEach((metric) => {
    const field = week.profile[metric.key];
    groups[metric.group].push(isUnknown(field) ? 0 : clampConfidence(field.confidence));
  });
  return Object.fromEntries(Object.entries(groups).map(([group, values]) => [group, values.reduce((sum, value) => sum + value, 0) / values.length])) as Record<Group, number>;
}

function LogoMark({ small = false }: { small?: boolean }) {
  return <svg className={small ? "brand-mark" : undefined} viewBox="0 0 1085 862" aria-hidden="true"><ellipse cx="542.5" cy="117" rx="122" ry="85" /><ellipse cx="542.5" cy="745" rx="122" ry="85" /><path d="M242 126C314 126 364 166 364 214C364 264 304 282 276 312C248 342 292 388 302 444C312 500 284 532 308 574C332 616 392 634 392 688C392 742 332 776 266 776C200 776 154 734 154 680C154 628 182 596 168 552C154 508 42 496 42 434C42 368 158 352 178 308C196 268 128 242 128 196C128 154 176 126 242 126Z" /><path d="M843 126C771 126 721 166 721 214C721 264 781 282 809 312C837 342 793 388 783 444C773 500 801 532 777 574C753 616 693 634 693 688C693 742 753 776 819 776C885 776 931 734 931 680C931 628 903 596 917 552C931 508 1043 496 1043 434C1043 368 927 352 907 308C889 268 957 242 957 196C957 154 909 126 843 126Z" /></svg>;
}

function ProgressLogo({ progress, knownCount }: { progress: Record<Group, number>; knownCount: number }) {
  const bounds: Record<Group, { x: number; y: number; width: number; height: number }> = { top: { x: 400, y: 32, width: 285, height: 170 }, bottom: { x: 400, y: 660, width: 285, height: 170 }, left: { x: 40, y: 126, width: 360, height: 650 }, right: { x: 685, y: 126, width: 360, height: 650 } };
  const overall = Math.round(Object.values(progress).reduce((sum, value) => sum + value, 0) / 4 * 100);
  return <div className="logo-hub"><svg viewBox="0 0 1085 862" role="img" aria-label={`Полнота профиля ${overall}%`}><defs><clipPath id="clip-up"><ellipse cx="542.5" cy="117" rx="122" ry="85" /></clipPath><clipPath id="clip-down"><ellipse cx="542.5" cy="745" rx="122" ry="85" /></clipPath><clipPath id="clip-left"><path d="M242 126C314 126 364 166 364 214C364 264 304 282 276 312C248 342 292 388 302 444C312 500 284 532 308 574C332 616 392 634 392 688C392 742 332 776 266 776C200 776 154 734 154 680C154 628 182 596 168 552C154 508 42 496 42 434C42 368 158 352 178 308C196 268 128 242 128 196C128 154 176 126 242 126Z" /></clipPath><clipPath id="clip-right"><path d="M843 126C771 126 721 166 721 214C721 264 781 282 809 312C837 342 793 388 783 444C773 500 801 532 777 574C753 616 693 634 693 688C693 742 753 776 819 776C885 776 931 734 931 680C931 628 903 596 917 552C931 508 1043 496 1043 434C1043 368 927 352 907 308C889 268 957 242 957 196C957 154 909 126 843 126Z" /></clipPath></defs>{(Object.keys(bounds) as Group[]).map((group) => { const box = bounds[group]; const fillHeight = box.height * progress[group]; return <g key={group} clipPath={`url(#clip-${group === "top" ? "up" : group === "bottom" ? "down" : group})`}><rect {...box} className="logo-empty" /><rect x={box.x} y={box.y + box.height - fillHeight} width={box.width} height={fillHeight} className="logo-fill" /></g>; })}</svg><div className="logo-readout"><strong>{overall}%</strong><span>Полнота профиля</span><small>{knownCount} из 11 метрик</small></div></div>;
}

function MetricCard({ config, field, expanded, onToggle }: { config: MetricConfig; field: ProfileField; expanded: boolean; onToggle: () => void }) {
  const unknown = isUnknown(field);
  const confidence = unknown ? 0 : Math.round(clampConfidence(field.confidence) * 100);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onToggle(); } };
  return <article className={`metric-card${unknown ? " is-unknown" : ""}${expanded ? " is-expanded" : ""}`} role="button" tabIndex={0} aria-expanded={expanded} onClick={onToggle} onKeyDown={onKeyDown}><div className="metric-card-top"><div className="metric-name"><span className="status-dot" /><span>{config.label}</span></div><div className="metric-value">{unknown ? "Неизвестно" : config.format(field.value)}<span className="chevron">⌄</span></div></div><div className="metric-details"><div className="metric-details-inner"><div className="confidence-line"><span>{unknown ? "Статус расчёта" : "Уверенность модели"}</span><strong>{unknown ? "Недостаточно данных" : `${confidence}%`}</strong></div><div className="confidence-track"><span style={{ width: `${unknown ? 12 : confidence}%` }} /></div><p>{config.description}</p><div className="tags">{config.sources.map((source) => <span key={source.key}>{source.label}</span>)}</div></div></div></article>;
}

function HypothesisRow({ hypothesis, index }: { hypothesis: Case3Hypothesis; index: number }) {
  const [rejected, setRejected] = useState(false);
  const confidence = Math.round(clampConfidence(hypothesis.confidence) * 100);
  const label = confidence >= 80 ? "Высокая уверенность" : confidence >= 65 ? "Средняя уверенность" : "Осторожное наблюдение";
  return <article className={`hypothesis${rejected ? " is-rejected" : ""}`}><span className="hyp-number">0{index + 1}</span><div className="hyp-content"><p>{hypothesis.text}</p><div className="hyp-meta"><span>{label}</span><strong>{confidence}%</strong></div><div className="hyp-track"><span style={{ width: `${confidence}%` }} /></div></div><div className="hyp-action"><button type="button" aria-pressed={rejected} onClick={() => setRejected((value) => !value)}>{rejected ? "Отмечено: не про меня" : "Это не про меня"}</button><small>Учтём и не будем опираться на это</small></div></article>;
}

export default function App() {
  const [response, setResponse] = useState<RunResponse | null>(null);
  const [selectedWeek, setSelectedWeek] = useState(0);
  const [expanded, setExpanded] = useState<Set<keyof Case3Profile>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const hasStartedLoading = useRef(false);
  const week = response?.weeks[selectedWeek];
  const progress = useMemo(() => week ? computeProgress(week) : null, [week]);
  const knownCount = week ? metricConfig.filter((item) => !isUnknown(week.profile[item.key])).length : 0;
  const activeSources = useMemo(() => { const sources = new Set<Source>(); if (week) metricConfig.forEach((item) => { if (!isUnknown(week.profile[item.key])) item.sources.forEach((source) => sources.add(source.key)); }); return sources; }, [week]);
  const loadAnswers = useCallback(async () => {
    setLoading(true); setError("");
    try { const dataset = import.meta.env.VITE_DATASET_CODE || "case3-dev-v1"; const data = await runCase({ case: 3, dataset_code: dataset }); if (!Array.isArray(data.weeks) || data.weeks.length === 0) throw new Error("Бэкенд вернул пустой массив weeks"); setResponse(data); setSelectedWeek(0); setExpanded(new Set()); }
    catch (requestError) { setError(getApiError(requestError)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    if (hasStartedLoading.current) return;
    hasStartedLoading.current = true;
    void loadAnswers();
  }, [loadAnswers]);
  const toggleMetric = (key: keyof Case3Profile) => setExpanded((current) => { const next = new Set(current); next.has(key) ? next.delete(key) : next.add(key); return next; });
  const byGroup = (group: Group) => metricConfig.filter((item) => item.group === group);

  return <><header className="topbar"><div className="topbar-inner"><div className="brand"><LogoMark small /><strong>Сэйн</strong><span>Неделя без анкеты</span></div><div className="source-badges">{(Object.keys(sourceLabels) as Source[]).map((source) => <span className={activeSources.has(source) ? "active" : ""} key={source}><i />{sourceLabels[source]}</span>)}</div></div></header><main className="container"><section className="hero"><div><span className="eyebrow">Профиль недели · 11 параметров</span><h1>Вот что мы о тебе узнали</h1></div><div className="hero-meta">{response && <label className="week-select">Неделя<select value={selectedWeek} onChange={(event) => { setSelectedWeek(Number(event.target.value)); setExpanded(new Set()); }}>{response.weeks.map((item, index) => <option value={index} key={`${item.record_id}-${index}`}>{index + 1} · {item.record_id}</option>)}</select></label>}<p>Нажмите на карточку метрики, чтобы раскрыть точность расчёта и источники данных.</p></div></section>{!week || !progress ? <section className="empty-state"><LogoMark /><span className="eyebrow">{loading ? "Получаем данные" : "Не удалось загрузить профиль"}</span><h2>{loading ? "Собираем профиль недели…" : "Бэкенд временно недоступен"}</h2><p>{loading ? "Карточки заполнятся автоматически после ответа сервера." : error}</p>{!loading && <button className="primary-button" onClick={() => void loadAnswers()}>Повторить запрос</button>}</section> : <><section className="profile-canvas"><div className="canvas-head"><div><h2>Карта привычек за 7 дней</h2><p>Четыре элемента знака заполняются по средней уверенности метрик своей группы.</p></div><div className="legend"><span><i className="known" />Определено</span><span><i />Нет данных</span></div></div><div className="orbital-grid"><div className="slot-top">{byGroup("top").map((item) => <MetricCard key={item.key} config={item} field={week.profile[item.key]} expanded={expanded.has(item.key)} onToggle={() => toggleMetric(item.key)} />)}</div><div className="slot-left"><div className="group-caption"><span>Сон и ритм</span><strong>{Math.round(progress.left * 100)}%</strong></div>{byGroup("left").map((item) => <MetricCard key={item.key} config={item} field={week.profile[item.key]} expanded={expanded.has(item.key)} onToggle={() => toggleMetric(item.key)} />)}</div><div className="slot-center"><ProgressLogo progress={progress} knownCount={knownCount} /></div><div className="slot-right"><div className="group-caption"><span>Движение</span><strong>{Math.round(progress.right * 100)}%</strong></div>{byGroup("right").map((item) => <MetricCard key={item.key} config={item} field={week.profile[item.key]} expanded={expanded.has(item.key)} onToggle={() => toggleMetric(item.key)} />)}</div><div className="slot-bottom">{byGroup("bottom").map((item) => <MetricCard key={item.key} config={item} field={week.profile[item.key]} expanded={expanded.has(item.key)} onToggle={() => toggleMetric(item.key)} />)}</div></div></section><section className="hypotheses"><div className="hyp-head"><div><span className="eyebrow">Три гипотезы</span><h2>Похоже на тебя?</h2></div><p>Это наблюдения об образе жизни, а не медицинские выводы.</p></div><div>{week.hypotheses.map((hypothesis, index) => <HypothesisRow key={`${week.record_id}-${index}`} hypothesis={hypothesis} index={index} />)}</div></section><section className="transparency"><div><h2>Как мы это посчитали и что происходит с данными</h2><p>Профиль собран автоматически из обезличенных сигналов за семь дней. Если данных не хватило для уверенного вывода, карточка честно показывает «неизвестно».</p></div><div className="transparency-pills"><span><strong>Без анкет и опросов</strong>Только паттерны недели</span><span><strong>Калибровка уверенности</strong>Значение приходит из бэка</span><span><strong>Обратная связь</strong>Можно отметить неточную гипотезу</span></div></section></>}</main></>;
}
