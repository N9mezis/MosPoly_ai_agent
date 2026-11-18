import type { components } from "./api/client";

type Schemas = components["schemas"];
const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "long", timeZone: "UTC" });
const displayDate = (date?: string | null) => date ? dateFormat.format(new Date(date)) : "";

function sourceLink(url?: string | null) {
  if (!url) return undefined;
  try {
    const absolute = new URL(url);
    if (["https:", "http:"].includes(absolute.protocol) && !absolute.username && !absolute.password) return absolute.href;
  } catch {
    // Legacy data may not have a valid absolute public source.
  }
}

export function RegulationEvidence({ finding }: { finding: Schemas["FindingOut"] }) {
  const { regulation, law_quote: quote } = finding;
  const source = sourceLink(regulation.url);
  const edition = displayDate(regulation.edition_date);
  const activeEdition = displayDate(regulation.active_edition_date);
  const effectiveFrom = displayDate(regulation.effective_from);
  const effectiveTo = displayDate(regulation.effective_to);
  const citation = [regulation.source_title, regulation.article && `ст. ${regulation.article}`,
    regulation.part && `ч. ${regulation.part}`].filter(Boolean).join(", ");
  return <div className="regulation-evidence">
    <strong>{citation}</strong>
    <p className="muted">{edition ? `Редакция от ${edition}` : "Дата редакции не сохранена"}</p>
    {(regulation.update_status === "changed" || regulation.update_status === "not_in_active") &&
      <p className="notice">{regulation.update_status === "changed"
        ? "Текст нормы в активной редакции базы изменился."
        : "Фрагмент не найден в активной редакции базы."}
      {activeEdition && ` Активная редакция от ${activeEdition}.`} В отчёте показан текст на момент проверки.</p>}
    {quote && <blockquote>{quote}</blockquote>}
    <details>
      <summary>Открыть норму и редакцию</summary>
      {regulation.full_text
        ? <p className="regulation-text">{regulation.full_text}</p>
        : <p className="muted">Полный фрагмент не сохранён для этого замечания. Доступна только цитата из отчёта.</p>}
      {(effectiveFrom || effectiveTo) && <p className="muted">
        {effectiveFrom && `Действует с ${effectiveFrom}`}{effectiveFrom && effectiveTo && " · "}
        {effectiveTo && `Действует до ${effectiveTo}`}
      </p>}
      {source ? <a href={source} target="_blank" rel="noreferrer">Открыть источник нормы ↗</a>
        : <p className="muted">Ссылка на источник не сохранена.</p>}
    </details>
  </div>;
}

export function RunEvidence({ id, snapshot }: { id: string; snapshot?: Schemas["AnalysisSnapshotOut"] | null }) {
  return <details className="run-evidence">
    <summary>Номер проверки и использованные версии</summary>
    <dl>
      <dt>Номер проверки</dt><dd><code>{id}</code></dd>
      {snapshot?.profile_id && <><dt>Профиль проверки</dt><dd><code>{snapshot.profile_id}</code></dd></>}
      {snapshot?.llm_provider && <><dt>Языковая модель</dt>
        <dd>{[snapshot.llm_provider, snapshot.llm_model].filter(Boolean).join(" · ")}</dd></>}
      {snapshot?.embedding_model && <><dt>Модель эмбеддингов</dt><dd>{snapshot.embedding_model}</dd></>}
      {snapshot?.reranker && <><dt>Переранжирование</dt><dd>{snapshot.reranker}</dd></>}
      {!!snapshot?.regulation_version_ids?.length && <><dt>Версии нормативной базы</dt>
        <dd><ul>{snapshot.regulation_version_ids.map(version => <li key={version}><code>{version}</code></li>)}</ul></dd></>}
      {!!Object.keys(snapshot?.prompt_hashes ?? {}).length && <><dt>Отпечатки инструкций модели</dt>
        <dd><ul>{Object.entries(snapshot?.prompt_hashes ?? {}).map(([name, hash]) =>
          <li key={name}>{name === "chunk_check" ? "Проверка пунктов" : "Проверка полноты"}: <code>{hash}</code></li>)}</ul></dd></>}
    </dl>
    <p className="muted">{snapshot
      ? "По номеру можно открыть сохранённый результат без повторного анализа."
      : "Снимок параметров для этой проверки не сохранён."}</p>
  </details>;
}
