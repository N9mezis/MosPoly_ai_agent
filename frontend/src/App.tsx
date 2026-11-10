import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, downloadReport, json, login, logout, type components } from "./api/client";
import { History } from "./History";
import "./styles.css";

type Schemas = components["schemas"];
type Finding = Schemas["FindingOut"];
const terminal = ["completed", "failed", "cancelled"];

function ErrorMessage({ error }: { error: Error | null }) {
  if (error instanceof ApiError && error.status === 401) return <Navigate to="/login" replace />;
  return error && <p role="alert" className="error">{error.message}</p>;
}

function Login({ onLogin }: { onLogin: () => Promise<void> }) {
  const navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => login(email, password),
    onSuccess: async () => { await onLogin(); navigate("/", { replace: true }); },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    mutation.mutate({ email: String(values.get("email")), password: String(values.get("password")) });
  }
  return <section className="panel narrow">
    <h1>Вход</h1>
    <form onSubmit={submit}>
      <label>Электронная почта<input name="email" type="email" autoComplete="username" required /></label>
      <label>Пароль<input name="password" type="password" autoComplete="current-password" required /></label>
      <button disabled={mutation.isPending}>Войти</button>
      {mutation.error && <p role="alert" className="error">{mutation.error.message}</p>}
    </form>
  </section>;
}

function NewAnalysis() {
  const navigate = useNavigate();
  const types = useQuery({ queryKey: ["document-types"], queryFn: () => api<Schemas["DocumentTypeOut"][]>("/document-types") });
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File>();
  const [dragging, setDragging] = useState(false);
  const [validation, setValidation] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const type = types.data?.find(item => item.id === selected) ?? types.data?.find(item => item.is_enabled);
  const mutation = useMutation({
    mutationFn: async ({ document, documentType }: { document: File; documentType: string }) => {
      const data = new FormData();
      data.set("file", document);
      const uploaded = await api<Schemas["DocumentUploaded"]>("/documents", { method: "POST", body: data });
      return api<Schemas["AnalysisCreated"]>("/analyses", json({
        document_id: uploaded.document_id, document_type_id: documentType,
      }));
    },
    onSuccess: result => navigate(`/analyses/${result.analysis_id}`),
  });
  function choose(document?: File) {
    setFile(document);
    setValidation("");
    mutation.reset();
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !type) return;
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!type.allowed_extensions.some(value => extension === `.${value.replace(/^\./, "")}`)) {
      setValidation("Выберите файл допустимого формата.");
    } else if (!file.size || file.size > 10 * 1024 * 1024) {
      setValidation("Размер файла должен быть больше нуля и не превышать 10 МБ.");
    } else {
      setValidation("");
      mutation.mutate({ document: file, documentType: type.id });
    }
  }
  return <section className="panel narrow">
    <h1>Новая проверка</h1>
    <p>Загрузите трудовой договор для проверки по ТК РФ.</p>
    <form onSubmit={submit}>
      <label>Тип документа
        <select value={type?.id ?? ""} onChange={e => setSelected(e.target.value)} disabled={mutation.isPending}>
          {!type && <option value="">Выберите тип</option>}
          {types.data?.map(item => <option key={item.id} value={item.id} disabled={!item.is_enabled}>{item.title}</option>)}
        </select>
      </label>
      <div className={dragging ? "drop active" : "drop"}
        onDragOver={event => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={event => {
          event.preventDefault();
          setDragging(false);
          if (!mutation.isPending) choose(event.dataTransfer.files[0]);
        }}>
        <p>{file?.name ?? "Перетащите договор сюда"}</p>
        <p className="muted">DOCX или PDF, до 10 МБ</p>
        <input hidden ref={input} type="file" accept=".docx,.pdf"
          onChange={event => { choose(event.target.files?.[0]); event.target.value = ""; }} />
        <button type="button" className="secondary" onClick={() => input.current?.click()} disabled={mutation.isPending}>Выбрать файл</button>
      </div>
      <button disabled={!file || !type || mutation.isPending}>{mutation.isPending ? "Загрузка…" : "Запустить проверку"}</button>
      {validation && <p role="alert" className="error">{validation}</p>}
      <ErrorMessage error={types.error ?? mutation.error} />
    </form>
  </section>;
}

function AnalysisStatus() {
  const { id } = useParams();
  const result = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => api<Schemas["AnalysisStatusOut"]>(`/analyses/${id}`),
    refetchInterval: query => !query.state.error && !terminal.includes(query.state.data?.status ?? "") ? 1500 : false,
  });
  if (result.data?.status === "completed") return <Navigate to={`/analyses/${id}/report`} replace />;
  return <section className="panel narrow">
    <h1>Статус проверки</h1>
    <ErrorMessage error={result.error} />
    {result.error && <button onClick={() => void result.refetch()}>Повторить запрос</button>}
    {result.isPending && <p role="status">Загрузка статуса…</p>}
    {result.data && <>
      <p role="status">{result.data.status_label}{result.data.stage ? ` · ${result.data.stage}` : ""}</p>
      <progress aria-label="Прогресс проверки" max={1} value={result.data.progress ?? 0} />
      {result.data.error_message && <p role="alert" className="error">{result.data.error_message}</p>}
    </>}
    <p><Link to="/">Новая проверка</Link></p>
  </section>;
}

function DocumentText({ result, findings }: { result: Schemas["AnalysisResult"]; findings: Finding[] }) {
  return <div className="document">
    <h2>Текст договора</h2>
    {result.blocks.map(block => {
      const chars = Array.from(block.text);
      const highlights = findings.flatMap(finding => finding.highlights
        ?.filter(item => item.block_id === block.block_id)
        .map(item => ({ ...item, finding })) ?? []);
      const boundaries = Array.from(new Set([0, chars.length, ...highlights.flatMap(item => [
        Math.max(0, Math.min(chars.length, item.start)), Math.max(0, Math.min(chars.length, item.end)),
      ])])).sort((a, b) => a - b);
      return <p key={block.block_id}>{boundaries.slice(0, -1).map((start, index) => {
        const end = boundaries[index + 1];
        const text = chars.slice(start, end).join("");
        const hits = highlights.filter(item => item.start <= start && end <= item.end);
        const hit = hits[0];
        return hit ? <a key={start} id={`fragment-${hit.finding.id}-${block.block_id}-${start}`}
          data-finding={hits.map(item => item.finding.id).join(" ")}
          className={`mark ${hit.finding.category}`} href={`#finding-${hit.finding.id}`}>{text}</a>
          : <span key={start}>{text}</span>;
      })}</p>;
    })}
  </div>;
}

function Report() {
  const { id } = useParams();
  const query = useQuery({
    queryKey: ["report", id], queryFn: () => api<Schemas["AnalysisResult"]>(`/analyses/${id}/result`),
  });
  const [filter, setFilter] = useState("all");
  const download = useMutation({ mutationFn: (format: "pdf" | "docx") => downloadReport(id!, format) });
  const result = query.data;
  if (!result) return <section className="panel"><h1>Отчёт</h1><ErrorMessage error={query.error} />
    {query.isPending && <p role="status">Загрузка отчёта…</p>}
    {query.error instanceof ApiError && query.error.status === 409 && <Link to={`/analyses/${id}`}>К статусу проверки</Link>}
  </section>;
  const findings = result.findings.filter(item => filter === "all" || item.category === filter);
  return <section className="panel">
    <div className="report-head">
      <div><h1>Отчёт о проверке</h1><p className="filename">{result.filename}</p></div>
      <div className="actions">
        <button disabled={download.isPending} onClick={() => download.mutate("pdf")}>Скачать PDF</button>
        <button disabled={download.isPending} onClick={() => download.mutate("docx")}>Скачать DOCX</button>
      </div>
    </div>
    <ErrorMessage error={download.error} />
    <p className="notice">{result.disclaimer}</p>
    {result.is_partial && <p className="notice">Проверка частичная. Не все пункты удалось проверить.</p>}
    <p>Критические: {result.summary.critical ?? 0} · Рекомендательные: {result.summary.recommended ?? 0} · Информационные: {result.summary.info ?? 0}</p>
    <div className="columns">
      <DocumentText result={result} findings={findings} />
      <div>
        <h2>Замечания</h2>
        <label>Категория<select value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="all">Все категории</option><option value="critical">Критические</option>
          <option value="recommended">Рекомендательные</option><option value="info">Информационные</option>
        </select></label>
        {!findings.length && <p>Нет замечаний в выбранной категории.</p>}
        {findings.map(finding => <article id={`finding-${finding.id}`} className={`finding ${finding.category}`} key={finding.id}>
          <strong>{finding.category_label} · {finding.chunk_key}</strong>
          <h3>{finding.title || "Замечание"}</h3>
          <blockquote>{finding.contract_quote}</blockquote>
          <p>{finding.regulation.source_title}{finding.regulation.article && `, ст. ${finding.regulation.article}`}{finding.regulation.part && `, ч. ${finding.regulation.part}`}</p>
          <blockquote>{finding.law_quote}</blockquote>
          <p>{finding.explanation}</p>
          {finding.recommendation && <p><strong>Рекомендация. </strong>{finding.recommendation}</p>}
          {!!finding.highlights?.length && <button className="secondary" onClick={() => {
            document.querySelector<HTMLElement>(`[data-finding~="${finding.id}"]`)?.scrollIntoView({ block: "center" });
          }}>К фрагменту договора</button>}
        </article>)}
      </div>
    </div>
    {!!result.technical_issues?.length && <section>
      <h2>Технические сбои</h2>
      <ul>{result.technical_issues.map((issue, index) => <li key={index}>{issue.chunk_key} · {issue.message}</li>)}</ul>
    </section>}
  </section>;
}

export function App() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const cache = useQueryClient();
  const user = useQuery({ queryKey: ["session"], queryFn: () => api<Schemas["MeOut"]>("/auth/me") });
  const leaving = useMutation({
    mutationFn: logout,
    onSuccess: () => { cache.clear(); navigate("/login", { replace: true }); },
  });
  const loginScreen = <Login onLogin={async () => { await cache.invalidateQueries({ queryKey: ["session"] }); }} />;
  const protectedView = user.isPending ? <p role="status">Проверяем сессию…</p>
    : user.error ? <ErrorMessage error={user.error} />
    : <Routes>
        <Route path="/" element={<NewAnalysis />} />
        <Route path="/history" element={<History />} />
        <Route path="/analyses/:id" element={<AnalysisStatus />} />
        <Route path="/analyses/:id/report" element={<Report />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>;
  return <>
    <header><Link to="/">Проверка договоров</Link>
      {user.data && pathname !== "/login" && <div className="actions"><span>{user.data.full_name}</span>
        <Link to="/history">История проверок</Link>
        <button className="secondary" disabled={leaving.isPending} onClick={() => leaving.mutate()}>Выйти</button></div>}
    </header>
    <main><ErrorMessage error={leaving.error} />
      <Routes>
        <Route path="/login" element={loginScreen} />
        <Route path="/*" element={protectedView} />
      </Routes>
    </main>
  </>;
}
