import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, downloadReport, json, login, logout, type components } from "./api/client";
import { ErrorMessage } from "./ErrorMessage";
import { AnalysisStatus } from "./AnalysisStatus";
import { ContractTypeSelect } from "./ContractTypeSelect";
import { RegulationEvidence, RunEvidence } from "./ReportEvidence";
import { History } from "./History";
import { Regulations } from "./Regulations";
import { Users } from "./Users";
import { Busy, FilePicker, Icon, fileExtension } from "./ui";
import logo from "./assets/viwork-logo.png";
import "./styles.css";

type Schemas = components["schemas"];
type Finding = Schemas["FindingOut"];
const productName = "ViAgent";
const categories = [
  { id: "critical", title: "Критические" },
  { id: "recommended", title: "Рекомендательные" },
  { id: "info", title: "Информационные" },
] as const;
const clauseOrder = new Intl.Collator("ru", { numeric: true });

function goToElement(element: HTMLElement | null) {
  if (!element) return;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: "center" });
}

function Login({ onLogin }: { onLogin: () => Promise<void> }) {
  const navigate = useNavigate();
  const { state } = useLocation();
  const from = typeof state?.from === "string" && /^\/(?![\\/])/.test(state.from) ? state.from : "/";
  const mutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => login(email, password),
    onSuccess: async () => { await onLogin(); navigate(from, { replace: true }); },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    mutation.mutate({ email: String(values.get("email")), password: String(values.get("password")) });
  }
  return <section className="panel narrow">
    <p className="eyebrow">Личный кабинет</p>
    <h1>Вход в {productName}</h1>
    <p className="muted">Войдите, чтобы проверить договор и открыть историю проверок.</p>
    <form onSubmit={submit}>
      <label>Электронная почта<input name="email" type="email" autoComplete="username" required /></label>
      <label>Пароль<input name="password" type="password" autoComplete="current-password" required /></label>
      <button disabled={mutation.isPending}>Войти</button>
      {mutation.isPending && <Busy>Входим в систему…</Busy>}
      <ErrorMessage error={mutation.error} context="login" />
    </form>
  </section>;
}

function NewAnalysis({ initialTypeId = "" }: { initialTypeId?: string }) {
  const navigate = useNavigate();
  const types = useQuery({ queryKey: ["document-types"], queryFn: () => api<Schemas["DocumentTypeOut"][]>("/document-types") });
  const [selectedTypeId, setSelectedTypeId] = useState(initialTypeId);
  const [file, setFile] = useState<File>();
  const [validation, setValidation] = useState("");
  const [attempt, setAttempt] = useState<{ key: string; documentId: string | null }>();
  const type = types.data?.find(item => item.id === selectedTypeId && item.is_enabled);
  const hasAvailableTypes = types.data?.some(item => item.is_enabled);
  const formats = type?.allowed_extensions.map(value => value.replace(/^\./, "").toLowerCase()) ?? [];
  const mutation = useMutation({
    mutationFn: async ({ document, documentType, current }: {
      document: File; documentType: string; current: NonNullable<typeof attempt>;
    }) => {
      let documentId = current.documentId;
      if (!documentId) {
        const data = new FormData();
        data.set("file", document);
        const uploaded = await api<Schemas["DocumentUploaded"]>("/documents", { method: "POST", body: data });
        documentId = uploaded.document_id;
        setAttempt({ ...current, documentId });
      }
      const payload = json({ document_id: documentId, document_type_id: documentType });
      const headers = new Headers(payload.headers);
      headers.set("Idempotency-Key", current.key);
      return api<Schemas["AnalysisCreated"]>("/analyses", { ...payload, headers });
    },
    onSuccess: result => navigate(`/analyses/${result.analysis_id}`),
  });
  function choose(document?: File) {
    setValidation("");
    setAttempt(undefined);
    mutation.reset();
    if (document && !formats.includes(fileExtension(document.name))) {
      setFile(undefined);
      setValidation(`Выберите файл в формате ${formats.map(value => value.toUpperCase()).join(" или ")}.`);
    } else if (document && (!document.size || document.size > 10 * 1024 * 1024)) {
      setFile(undefined);
      setValidation(document.size ? "Файл больше 10 МБ. Уменьшите его размер и выберите заново."
        : "Файл пустой. Выберите заполненный договор.");
    } else {
      setFile(document);
    }
  }
  function selectType(id: string) {
    setSelectedTypeId(id);
    choose();
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !type || mutation.isPending) return;
    const key = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),
      byte => byte.toString(16).padStart(2, "0")).join("");
    const current = attempt ?? { key: key(), documentId: null };
    setAttempt(current);
    mutation.mutate({ document: file, documentType: type.id, current });
  }
  return <>
    <h1>Проверка договора</h1>
    <p className="lead">Выберите тип документа и загрузите файл для проверки.</p>
    <div className="workspace">
      <section className="panel">
        <form onSubmit={submit}>
          <ContractTypeSelect options={types.data} value={type?.id}
            onChange={selectType} disabled={!hasAvailableTypes || mutation.isPending} />
          {types.isPending && <Busy>Загружаем типы договоров…</Busy>}
          <ErrorMessage error={types.error} />
          {types.isError && <div className="actions">
            <button type="button" className="secondary" disabled={types.isFetching}
              onClick={() => void types.refetch()}>Повторить загрузку списка</button>
          </div>}
          {types.data && !hasAvailableTypes && <p className="muted">Сейчас нет доступных типов для проверки.</p>}
          {types.data && hasAvailableTypes && selectedTypeId && !type &&
            <p role="alert" className="error">Этот тип пока недоступен. Выберите другой из списка.</p>}
          {type && <p className="type-description muted">{type.description}</p>}
          <section aria-labelledby="upload-heading">
            <h2 id="upload-heading">Загрузите договор</h2>
            <FilePicker file={file} onChange={choose} disabled={!type || mutation.isPending}
              accept={formats.map(value => `.${value}`).join(",")}
              hint={type
                ? `${formats.map(value => value.toUpperCase()).join(" или ")} с текстовым слоем · до 10 МБ`
                : "Сначала выберите тип договора"} />
          </section>
          <div className="actions">
            <button className="primary" disabled={!type || !file || mutation.isPending}>Запустить проверку</button>
            {mutation.isPending && <Busy>Загружаем файл и создаём проверку…</Busy>}
            {type && !file && !validation && <span className="muted">Выберите файл, чтобы начать</span>}
          </div>
          {validation && <p role="alert" className="error">{validation}</p>}
          <ErrorMessage error={mutation.error} />
        </form>
      </section>
      <aside className="panel guide">
        <h2>Как проходит проверка</h2>
        <ol role="list">
          <li><strong>Извлекаем текст</strong><span>Разбираем документ на пункты.</span></li>
          <li><strong>Сверяем условия</strong><span>Подбираем нормы для проверки.</span></li>
          <li><strong>Готовим отчёт</strong><span>Показываем замечания и цитаты.</span></li>
        </ol>
        {type && <p className="muted">Область проверки: {type.scope}</p>}
      </aside>
    </div>
  </>;
}

function CheckRoute() {
  const { typeId } = useParams();
  return <NewAnalysis key={typeId} initialTypeId={typeId} />;
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
          className={`mark ${hit.finding.category}`} href={`#finding-${hit.finding.id}`}
          onClick={event => {
            event.preventDefault();
            goToElement(document.getElementById(`finding-${hit.finding.id}`));
          }}>{text}</a>
          : <span key={start}>{text}</span>;
      })}</p>;
    })}
  </div>;
}

function Report() {
  const { id } = useParams();
  return id ? <ReportPanel key={id} id={id} /> : <Navigate to="/history" replace />;
}

function ReportPanel({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ["report", id], queryFn: ({ signal }) => api<Schemas["AnalysisResult"]>(`/analyses/${id}/result`, { signal }),
  });
  const [filter, setFilter] = useState<(typeof categories)[number]["id"] | "all">("all");
  const [sort, setSort] = useState("category");
  const download = useMutation({ mutationFn: (format: "pdf" | "docx") => downloadReport(id, format) });
  const result = query.data;
  if (!result) return <section className="panel"><h1>Отчёт</h1><ErrorMessage error={query.error} />
    {query.isPending && <Busy>Загружаем отчёт…</Busy>}
    {query.error instanceof ApiError && query.error.status === 409 && <Link to={`/analyses/${id}`}>К статусу проверки</Link>}
    {query.isError && <p><Link to="/history">К истории проверок</Link></p>}
  </section>;
  const findings = result.findings.filter(item => filter === "all" || item.category === filter);
  if (sort === "clause") findings.sort((left, right) =>
    Number(left.chunk_key === "document") - Number(right.chunk_key === "document")
    || clauseOrder.compare(left.chunk_key, right.chunk_key));
  const updated = result.findings.some(({ regulation }) =>
    regulation.update_status === "changed" || regulation.update_status === "not_in_active");
  return <section className="panel">
    <div className="report-head">
      <div><Link className="back" to="/history">← История проверок</Link>
        <h1>Отчёт о проверке</h1><p className="filename">{result.filename}</p></div>
      <div className="actions">
        <button className="secondary" disabled={download.isPending} onClick={() => download.mutate("pdf")}>Скачать PDF</button>
        <button className="secondary" disabled={download.isPending} onClick={() => download.mutate("docx")}>Скачать DOCX</button>
      </div>
    </div>
    <ErrorMessage error={download.error} />
    {download.isPending && <Busy>Готовим файл отчёта…</Busy>}
    <p className="notice">{result.disclaimer}</p>
    {result.is_partial && <p className="notice">Частичный результат. Не все пункты удалось проверить.
      {" "}{!!result.technical_issues?.length && <a href="#technical-issues">К техническим сбоям</a>}</p>}
    {updated && <p className="notice">Некоторые нормы требуют сверки с активной редакцией. Они помечены в карточках замечаний.</p>}
    <div className="metrics" role="group" aria-label="Сводка по проверке">
      {categories.map(category => <button className={`metric metric-filter ${category.id}`} key={category.id}
        aria-label={`Показать: ${category.title.toLowerCase()}`} aria-pressed={filter === category.id}
        onClick={() => { setFilter(category.id); goToElement(document.getElementById("findings-title")); }}>
        <strong>{result.summary[category.id] ?? 0}</strong><span>{category.title}</span>
      </button>)}
      <div className="metric"><strong>{result.summary.technical_errors ?? 0}</strong><span>Технические сбои</span></div>
    </div>
    <div className="columns">
      <DocumentText result={result} findings={findings} />
      <div>
        <h2 id="findings-title" tabIndex={-1}>Замечания</h2>
        <div className="filters" role="group" aria-label="Категория замечаний">
          <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>Все категории</button>
          {categories.map(category => <button key={category.id} aria-pressed={filter === category.id}
            onClick={() => setFilter(category.id)}>{category.title}</button>)}
        </div>
        <div className="finding-controls">
          <label>Сортировка<select value={sort} onChange={event => setSort(event.target.value)}>
            <option value="category">По важности</option><option value="clause">По пунктам договора</option>
          </select></label>
          <p role="status" className="muted">Показано: {findings.length} из {result.findings.length}</p>
        </div>
        {!findings.length && <p>{filter === "all"
          ? "В проверенных пунктах замечаний нет."
          : "Нет замечаний в выбранной категории."}</p>}
        {findings.map(finding => <article tabIndex={-1} id={`finding-${finding.id}`} className={`finding ${finding.category}`} key={finding.id}>
          <strong>{finding.category_label} · {finding.chunk_key === "document" ? "Весь договор" : `Пункт ${finding.chunk_key}`}</strong>
          <h3>{finding.title || "Замечание"}</h3>
          {finding.contract_quote && <blockquote>{finding.contract_quote}</blockquote>}
          <p>{finding.explanation}</p>
          {finding.recommendation && <p><strong>Рекомендация. </strong>{finding.recommendation}</p>}
          <div className="actions evidence-actions">
            {!!finding.highlights?.length && <button className="secondary" onClick={() =>
              goToElement(document.querySelector<HTMLElement>(`[data-finding~="${CSS.escape(finding.id)}"]`))
            }>К фрагменту договора</button>}
            {!finding.highlights?.length && <span className="muted">Отдельный фрагмент для подсветки не сохранён.</span>}
          </div>
          <RegulationEvidence finding={finding} />
        </article>)}
      </div>
    </div>
    {!!result.technical_issues?.length && <section id="technical-issues">
      <h2>Технические сбои</h2>
      <ul>{result.technical_issues.map((issue, index) => <li key={index}>{issue.chunk_key} · {issue.message}</li>)}</ul>
    </section>}
    <RunEvidence id={result.id} snapshot={result.snapshot} />
  </section>;
}

export function App() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  useEffect(() => { document.getElementById("main-content")?.focus({ preventScroll: true }); }, [pathname]);
  const cache = useQueryClient();
  const user = useQuery({ queryKey: ["session"], queryFn: () => api<Schemas["MeOut"]>("/auth/me") });
  const canManageUsers = user.data?.permissions?.includes("users:manage");
  const canManageRegulations = user.data?.permissions?.includes("regulations:manage");
  const leaving = useMutation({
    mutationFn: logout,
    onSuccess: () => { cache.clear(); navigate("/login", { replace: true }); },
  });
  const loginScreen = <Login onLogin={async () => { await cache.invalidateQueries({ queryKey: ["session"] }); }} />;
  const protectedView = user.isPending ? <Busy>Проверяем сессию…</Busy>
    : user.error ? <ErrorMessage error={user.error} />
    : <Routes>
        <Route path="/" element={<NewAnalysis />} />
        <Route path="/check/:typeId" element={<CheckRoute />} />
        <Route path="/history" element={<History />} />
        {canManageUsers && user.data && <Route path="/users" element={<Users current={user.data} />} />}
        {canManageRegulations && <Route path="/regulations" element={<Regulations />} />}
        <Route path="/analyses/:id" element={<AnalysisStatus />} />
        <Route path="/analyses/:id/report" element={<Report />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>;
  const showMenu = Boolean(user.data && pathname !== "/login");
  return <>
    <a className="skip-link" href="#main-content">Перейти к содержимому</a>
    <header className="portal-header">
      <div className="topbar">
        <div className="brand">
          <Link to="/" aria-label="ViWork — главная"><img src={logo} alt="ViWork" width={126} height={28} /></Link>
          <span>{productName}</span>
        </div>
        {showMenu && <div className="actions">
          <span className="muted account-name">{user.data?.full_name}</span>
          <button className="secondary" disabled={leaving.isPending} onClick={() => leaving.mutate()}>Выйти</button>
        </div>}
      </div>
    </header>
    <div className={showMenu ? "portal-layout with-menu" : "portal-layout"}>
      {showMenu && <aside className="sidebar">
        <p className="eyebrow">Документы</p>
        <nav aria-label="Основная навигация">
          <NavLink to="/" end className="nav-item" data-section-active={/^\/(analyses|check)\//.test(pathname) || undefined}>
            <Icon name="documents" />Проверка договоров
          </NavLink>
          <NavLink to="/history" className="nav-item"><Icon name="history" />История проверок</NavLink>
          {canManageRegulations && <NavLink to="/regulations" className="nav-item"><Icon name="library" />Нормативная база</NavLink>}
          {canManageUsers && <NavLink to="/users" className="nav-item"><Icon name="users" />Пользователи</NavLink>}
        </nav>
      </aside>}
      <main id="main-content" tabIndex={-1}><ErrorMessage error={leaving.error} />
        <Routes>
          <Route path="/login" element={loginScreen} />
          <Route path="/*" element={protectedView} />
        </Routes>
      </main>
    </div>
  </>;
}
