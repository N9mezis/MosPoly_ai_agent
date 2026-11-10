import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type components } from "./api/client";
import { ErrorMessage } from "./ErrorMessage";

type Schemas = components["schemas"];
const statusLabels: Record<Schemas["RegulationVersionStatus"], string> = {
  draft: "Черновик", indexing: "Индексируется", ready: "Готова",
  active: "Активна", archived: "В архиве", failed: "Ошибка",
};
const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeZone: "UTC" });

export function Regulations() {
  const cache = useQueryClient();
  const [versionId, setVersionId] = useState<string>();
  const sources = useQuery({
    queryKey: ["regulations"],
    queryFn: () => api<Schemas["RegulationSourceOut"][]>("/regulations"),
    refetchInterval: query => query.state.data?.some(source =>
      source.versions?.some(version => version.status === "draft" || version.status === "indexing"),
    ) ? 2500 : false,
  });
  const chunks = useQuery({
    queryKey: ["regulation-chunks", versionId],
    queryFn: () => api<Schemas["RegulationChunkOut"][]>(`/regulations/versions/${versionId}/chunks`),
    enabled: Boolean(versionId),
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.set("file", file);
      return api<Schemas["RegulationVersionOut"]>("/regulations", { method: "POST", body });
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: ["regulations"] }),
  });
  const action = useMutation({
    mutationFn: ({ id, operation }: { id: string; operation: "activate" | "archive" }) =>
      api<Schemas["RegulationVersionOut"]>(`/regulations/versions/${id}/${operation}`, { method: "POST" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["regulations"] }),
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (file instanceof File && file.size) {
      try {
        await upload.mutateAsync(file);
        form.reset();
      } catch {
        // Ошибка отображается из состояния запроса.
      }
    }
  }

  return <section className="panel">
    <h1>Нормативная база</h1>
    <form className="admin-form" onSubmit={submit}>
      <label>Новая версия источника<input name="file" type="file" accept=".json,application/json" required /></label>
      <button disabled={upload.isPending}>Загрузить JSON</button>
      {upload.isSuccess && <p role="status">Версия принята на индексацию.</p>}
      <ErrorMessage error={upload.error} />
    </form>
    <ErrorMessage error={sources.error ?? action.error} />
    {sources.isPending && <p role="status">Загрузка нормативной базы…</p>}
    {sources.data?.length === 0 && <p>Источников пока нет.</p>}
    {sources.data?.map(source => <section className="regulation-source" key={source.id}>
      <h2>{source.title}</h2>
      <div className="table-scroll">
        <table className="history-table">
          <thead><tr><th>Версия</th><th>Статус</th><th>Фрагменты</th><th>Действия</th></tr></thead>
          <tbody>{source.versions?.map(version => {
            const operation = version.status === "active" ? "archive" : "activate";
            const label = version.status === "archived" ? "Откатить" : operation === "archive" ? "Архивировать" : "Активировать";
            const actionable = ["active", "ready", "archived"].includes(version.status);
            return <tr key={version.id}>
              <td>{version.label || version.id}
                {version.edition_date && <><br /><span className="muted">Редакция {dateFormat.format(new Date(version.edition_date))}</span></>}
              </td>
              <td>{statusLabels[version.status]}
                {version.error_message && <p className="error">{version.error_message}</p>}
              </td>
              <td>{version.chunks_count ?? 0}</td>
              <td><div className="actions">
                <button className="secondary" aria-expanded={versionId === version.id} onClick={() =>
                  setVersionId(versionId === version.id ? undefined : version.id)}>
                  {versionId === version.id ? "Скрыть фрагменты" : "Фрагменты"}
                </button>
                {actionable && <button className="secondary" disabled={action.isPending} onClick={() => {
                  if (window.confirm(`${label} версию «${version.label || version.id}»?`)) {
                    action.mutate({ id: version.id, operation });
                  }
                }}>{label}</button>}
              </div></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {source.versions?.some(version => version.id === versionId) && <section className="regulation-chunks">
        <h3>Фрагменты версии</h3>
        <ErrorMessage error={chunks.error} />
        {chunks.isPending && <p role="status">Загрузка фрагментов…</p>}
        {chunks.data?.length === 0 && <p>Фрагментов нет.</p>}
        {chunks.data?.map(chunk => <details key={chunk.id}>
          <summary>{chunk.title || chunk.chunk_key}{chunk.part && ` · ч. ${chunk.part}`}</summary>
          <p>{chunk.text}</p>
        </details>)}
      </section>}
    </section>)}
  </section>;
}
