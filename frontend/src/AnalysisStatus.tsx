import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { api, ApiError, send, type components } from "./api/client";
import { ErrorMessage } from "./ErrorMessage";
import { Busy } from "./ui";

type Status = components["schemas"]["AnalysisStatus"];
type StatusData = components["schemas"]["AnalysisStatusOut"];
const steps = [
  { status: "queued", label: "В очереди" },
  { status: "extracting", label: "Извлечение текста" },
  { status: "analyzing", label: "Проверка пунктов" },
] as const;
const isActive = (status?: Status) => steps.some(step => step.status === status);

function estimate(data: StatusData, updatedAt: number) {
  const done = data.chunks_done ?? 0;
  const total = data.chunks_total ?? 0;
  const elapsed = (updatedAt - Date.parse(data.started_at ?? "")) / 1000;
  if (data.status !== "analyzing" || done < 2 || done >= total || !(elapsed >= 5)) return null;
  const seconds = elapsed * (total - done) / done;
  if (seconds < 60) return `Ориентир: около ${Math.max(10, Math.ceil(seconds / 10) * 10)} сек. Расчёт по уже проверенным пунктам.`;
  return `Ориентир: около ${Math.ceil(seconds / 60)} мин. Расчёт по уже проверенным пунктам.`;
}

export function AnalysisStatus() {
  const { id } = useParams();
  return id ? <StatusPanel key={id} id={id} /> : <Navigate to="/history" replace />;
}

function StatusPanel({ id }: { id: string }) {
  const client = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const result = useQuery({
    queryKey: ["analysis", id],
    queryFn: ({ signal }) => api<StatusData>(`/analyses/${id}`, { signal }),
    refetchInterval: query => !query.state.error && isActive(query.state.data?.status) ? 1500 : false,
  });
  const cancel = useMutation({
    mutationFn: () => send(`/analyses/${id}/cancel`, { method: "POST" }),
    onSettled: async () => {
      setConfirm(false);
      await Promise.all([result.refetch(), client.invalidateQueries({ queryKey: ["history"] })]);
    },
  });

  const data = result.data;
  if (data?.status === "completed") return <Navigate to={`/analyses/${id}/report`} replace />;
  const active = isActive(data?.status);
  const current = steps.findIndex(step => step.status === data?.status);
  const remaining = data && estimate(data, result.dataUpdatedAt);
  return <section className="panel narrow">
    <h1>Статус проверки</h1>
    <ErrorMessage error={result.error ?? cancel.error} />
    {result.isError && <button className="secondary" disabled={result.isFetching}
      onClick={() => void result.refetch()}>Повторить запрос статуса</button>}
    {result.isPending && <Busy>Загружаем статус…</Busy>}
    {data && active && <>
      <ol className="analysis-steps" aria-label="Этапы проверки">
        {steps.map((step, index) => <li key={step.status} aria-current={current === index ? "step" : undefined}
          data-done={index < current || undefined}>{index < current && <span className="sr-only">Пройдено: </span>}{step.label}</li>)}
      </ol>
      {!result.isError && <Busy>{data.stage || data.status_label}</Busy>}
      <progress aria-label="Прогресс проверки" max={1}
        value={data.status === "queued" ? undefined : data.progress ?? 0} />
      <p className="muted">{remaining
        || (data.status === "queued" ? "Время зависит от очереди. Оценка появится во время обработки."
          : "Пока недостаточно данных для оценки времени.")}</p>
      <p className="muted">Можно перейти в историю и вернуться к проверке позже.</p>
      {confirm ? <div className="cancel-confirm">
        <p>Отменить проверку? Чтобы запустить её заново, потребуется снова загрузить документ.</p>
        <div className="actions">
          <button type="button" className="danger-action" disabled={cancel.isPending || result.isError}
            onClick={() => cancel.mutate()}>{cancel.isPending ? "Отменяем…" : "Да, отменить"}</button>
          <button type="button" className="secondary" disabled={cancel.isPending} onClick={() => setConfirm(false)}>Продолжить проверку</button>
        </div>
      </div> : <button className="secondary" disabled={result.isError || cancel.isPending}
        onClick={() => { cancel.reset(); setConfirm(true); }}>Отменить проверку</button>}
    </>}
    {data?.status === "cancelled" && <p role="status" className="notice">Проверка отменена. Отчёт не сформирован.</p>}
    {data?.status === "failed" && <ErrorMessage error={new ApiError(422,
      data.error_message || "Проверка завершилась ошибкой.", data.error_code ?? undefined)} />}
    <div className="actions status-links"><Link to="/">Новая проверка</Link><Link to="/history">История проверок</Link></div>
  </section>;
}
