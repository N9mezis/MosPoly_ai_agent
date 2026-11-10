import { useEffect, useState } from "react";

// Временная страница-заглушка (Шаг 0). Настоящий интерфейс делает агент B.
type Ready = {
  status: string;
  database: boolean;
  redis: boolean;
  llm_provider: string;
  embedding_provider: string;
  reranker: string;
};

export function App() {
  const [ready, setReady] = useState<Ready | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/readyz")
      .then((r) => r.json())
      .then(setReady)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 720, margin: "40px auto", padding: "0 16px" }}>
      <h1>Проверка трудовых договоров по ТК РФ</h1>
      <p>Интерфейс в разработке. Документация API: <a href="/docs">/docs</a></p>
      {error && <p style={{ color: "crimson" }}>API недоступен: {error}</p>}
      {ready && (
        <ul>
          <li>Статус: {ready.status}</li>
          <li>PostgreSQL: {ready.database ? "доступен" : "недоступен"}</li>
          <li>Redis: {ready.redis ? "доступен" : "недоступен"}</li>
          <li>LLM: {ready.llm_provider}, эмбеддинги: {ready.embedding_provider}, реранкер: {ready.reranker}</li>
        </ul>
      )}
    </main>
  );
}
