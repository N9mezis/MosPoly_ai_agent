import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type components } from "./api/client";
import { ErrorMessage } from "./ErrorMessage";
import { Busy } from "./ui";

type Schemas = components["schemas"];
const statuses: Record<Schemas["AnalysisStatus"], string> = {
  queued: "В очереди",
  extracting: "Извлечение текста",
  analyzing: "Анализ",
  completed: "Завершена",
  failed: "Ошибка",
  cancelled: "Отменена",
};
const pageSize = 20;
const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" });

export function History() {
  const navigate = useNavigate();
  const [analysisId, setAnalysisId] = useState("");
  const [invalidId, setInvalidId] = useState(false);
  const [params, setParams] = useSearchParams();
  const requestedStatus = params.get("status") ?? "";
  const status = Object.prototype.hasOwnProperty.call(statuses, requestedStatus) ? requestedStatus : "";
  const requestedPage = Number(params.get("page"));
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const query = useQuery({
    queryKey: ["history", status, page],
    queryFn: ({ signal }) => {
      const filters = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (status) filters.set("status", status);
      return api<Schemas["Page_AnalysisListItem_"]>(`/analyses?${filters}`, { signal });
    },
  });

  function changePage(next: number) {
    const filters = new URLSearchParams();
    if (status) filters.set("status", status);
    if (next > 1) filters.set("page", String(next));
    setParams(filters);
  }

  function openSaved(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = analysisId.trim();
    if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)) {
      setInvalidId(true);
      return;
    }
    navigate(`/analyses/${id}`);
  }
  const data = query.data;
  const lastPage = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  return <section className="panel">
    <h1>История проверок</h1>
    <form className="lookup-form" onSubmit={openSaved}>
      <label>Номер проверки<input value={analysisId} aria-invalid={invalidId}
        aria-describedby={invalidId ? "invalid-analysis-number" : undefined}
        onChange={event => { setAnalysisId(event.target.value); setInvalidId(false); }}
        placeholder="UUID из отчёта" required /></label>
      <button className="secondary">Открыть сохранённую проверку</button>
      {invalidId && <p id="invalid-analysis-number" role="alert" className="error">Скопируйте номер целиком из отчёта.</p>}
    </form>
    <label className="history-filter">Статус проверки
      <select value={status} onChange={event => setParams(event.target.value ? { status: event.target.value } : {})}>
        <option value="">Все статусы</option>
        {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
    {query.isPending && <Busy>Загружаем историю…</Busy>}
    <ErrorMessage error={query.error} />
    {data && <>
      {data.items.length ? <div className="table-scroll">
        <table className="history-table">
          <thead><tr><th>Дата</th><th>Файл</th><th>Статус</th><th>Замечания</th></tr></thead>
          <tbody>{data.items.map(item => <tr key={item.id}>
            <td>{dateFormat.format(new Date(item.created_at))}</td>
            <td><Link to={`/analyses/${item.id}${item.status === "completed" ? "/report" : ""}`}>{item.filename}</Link></td>
            <td>{item.status_label}
              {item.is_partial && <span className="history-flag badge">Частичный результат</span>}
              {item.has_regulation_updates && <span className="history-flag badge">Есть нормы для сверки</span>}
            </td>
            <td>{item.status === "completed"
              ? `Критические: ${item.summary.critical ?? 0} · Рекомендательные: ${item.summary.recommended ?? 0} · Информационные: ${item.summary.info ?? 0}`
              : "—"}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p>Проверок на этой странице нет.</p>}
      {(lastPage > 1 || page > 1) && <div className="actions">
        <button className="secondary" disabled={page <= 1} onClick={() => changePage(Math.min(lastPage, page - 1))}>Назад</button>
        <span>Страница {page} из {lastPage}</span>
        <button className="secondary" disabled={page >= lastPage} onClick={() => changePage(page + 1)}>Далее</button>
      </div>}
    </>}
  </section>;
}
