import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type components } from "./api/client";
import { ErrorMessage } from "./ErrorMessage";
import { Busy, FilePicker, fileExtension } from "./ui";

type Schemas = components["schemas"];
const statusLabels: Record<Schemas["RegulationVersionStatus"], string> = {
  draft: "Черновик", indexing: "Индексируется", ready: "Готова",
  active: "Активна", archived: "В архиве", failed: "Ошибка",
};
const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeZone: "UTC" });

export function Regulations() {
  const cache = useQueryClient();
  const [versionId, setVersionId] = useState<string>();
  const [file, setFile] = useState<File>();
  const [validation, setValidation] = useState("");
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

  function choose(next?: File) {
    setValidation("");
    upload.reset();
    if (next && (fileExtension(next.name) !== "json" || !next.size || next.size > 5 * 1024 * 1024)) {
      setFile(undefined);
      setValidation("Выберите непустой JSON-файл размером до 5 МБ.");
    } else {
      setFile(next);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file && !upload.isPending) {
      try {
        await upload.mutateAsync(file);
        setFile(undefined);
      } catch {
        // Ошибка отображается из состояния запроса.
      }
    }
  }

  const versions = sources.data?.flatMap(source => source.versions ?? []) ?? [];
  const active = versions.filter(version => version.status === "active");
  return <>
    <h1>Нормативная база</h1>
    <p className="lead">Активные редакции участвуют в проверке договоров. Архивную редакцию можно восстановить.</p>
    {sources.data && <div className="metrics three" aria-label="Состояние нормативной базы">
      <div className="metric"><strong>{active.length}</strong><span>Активных редакций</span></div>
      <div className="metric"><strong>{active.reduce((sum, version) => sum + (version.chunks_count ?? 0), 0)}</strong><span>Фрагментов в проверке</span></div>
      <div className="metric"><strong>{versions.filter(version => version.status === "archived").length}</strong><span>Редакций в архиве</span></div>
    </div>}
    <section className="panel">
      <h2>Добавить новую редакцию</h2>
      <div className="workspace">
        <form onSubmit={submit}>
          <FilePicker file={file} onChange={choose} accept=".json,application/json"
            hint="JSON в кодировке UTF-8 · до 5 МБ" disabled={upload.isPending} />
          <div className="actions"><button className="primary" disabled={upload.isPending || !file}>Загрузить JSON</button>
            {upload.isPending && <Busy>Отправляем редакцию…</Busy>}
          </div>
          {validation && <p role="alert" className="error">{validation}</p>}
          {upload.isSuccess && <p role="status" className="status-note">Версия принята на индексацию.</p>}
          <ErrorMessage error={upload.error} />
        </form>
        <aside className="requirements">
          <h3>Что должно быть в файле</h3>
          <ul><li>Идентификатор и название источника</li><li>Дата редакции</li><li>Непустой список нормативных фрагментов</li></ul>
          <p>После индексации активируйте редакцию в списке ниже.</p>
        </aside>
      </div>
    </section>
    <ErrorMessage error={sources.error ?? action.error} />
    {sources.isPending && <Busy>Загружаем нормативную базу…</Busy>}
    {action.isPending && <Busy>Обновляем статус редакции…</Busy>}
    {sources.data?.length === 0 && <p className="panel">Источников пока нет.</p>}
    {sources.data?.map(source => <section className="panel regulation-source" key={source.id}>
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
              <td>{version.status === "indexing" || version.status === "draft"
                ? <Busy>{statusLabels[version.status]}</Busy>
                : <span className={`badge ${version.status === "active" || version.status === "ready" ? "success" : version.status === "failed" ? "danger" : ""}`}>{statusLabels[version.status]}</span>}
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
        {chunks.isPending && <Busy>Загружаем фрагменты…</Busy>}
        {chunks.data?.length === 0 && <p>Фрагментов нет.</p>}
        {chunks.data?.map(chunk => <details key={chunk.id}>
          <summary>{chunk.title || chunk.chunk_key}{chunk.part && ` · ч. ${chunk.part}`}</summary>
          <p>{chunk.text}</p>
        </details>)}
      </section>}
    </section>)}
  </>;
}
