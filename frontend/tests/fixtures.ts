import type { Page, Route } from "@playwright/test";
import type { components } from "../src/api/schema";

type Schemas = components["schemas"];
export const id = "10000000-0000-4000-8000-000000000001";
const userId = "10000000-0000-4000-8000-000000000002";
const orgId = "10000000-0000-4000-8000-000000000003";
const documentId = "10000000-0000-4000-8000-000000000004";
const versionId = "10000000-0000-4000-8000-000000000005";
const created = "2026-11-17T10:00:00Z";
const quote = "Пример условия";
const filename = "test-contract.docx";
const documentType = {
  id: "employment-contract", title: "Трудовой договор", description: "Тестовый профиль.",
  scope: "Выборочные нормы", allowed_extensions: ["docx", "pdf"], is_enabled: true,
};
const categories = { critical: "Критическая", recommended: "Рекомендательная", info: "Информационная" };

function finding(n: number, clause: string, category: keyof typeof categories): Schemas["FindingOut"] {
  return {
    id: `10000000-0000-4000-8000-00000000001${n}`, chunk_key: clause, category, category_label: categories[category],
    origin: "rule", status: "violation", title: `Замечание ${clause}`, contract_quote: quote,
    regulation: {
      source_title: "Тестовый источник", article: "91", part: "1", edition_date: "2025-07-31",
      full_text: "Полный тестовый фрагмент нормы в архивной редакции.",
      version_id: versionId, url: "https://example.test/norm", update_status: n === 1 ? "changed" : "unchanged",
      active_edition_date: "2026-01-01",
    },
    law_quote: "Короткая цитата", explanation: "Тестовое пояснение", recommendation: "Проверить формулировку.",
    highlights: [{ block_id: "p1", start: 0, end: quote.length }],
  };
}

export const report: Schemas["AnalysisResult"] = {
  id, status: "completed", filename, document_type_id: documentType.id, created_at: created,
  is_partial: true, summary: { critical: 2, recommended: 1, technical_errors: 1 },
  blocks: [{ block_id: "p1", text: quote + " договора." }],
  findings: [finding(1, "3.10", "critical"), finding(2, "3.2", "critical"), finding(3, "2.1", "recommended")],
  technical_issues: [{ chunk_key: "4.2", message: "Модель не ответила." }],
  disclaimer: "Результат не является юридическим заключением.",
  snapshot: {
    regulation_version_ids: [versionId], llm_provider: "mock", llm_model: "mock",
    embedding_model: "hashing-test", reranker: "none", prompt_hashes: { chunk_check: "abcdef0123456789" },
  },
};

type State = {
  signedIn: boolean;
  status: Schemas["AnalysisStatus"];
  uploads: number;
  statusRequests: number;
  cancellations: number;
  keys: (string | undefined)[];
  uploadError?: string;
  stageError?: string;
  completesOnCancel?: boolean;
  failFirstStart?: boolean;
  inaccessible?: boolean;
};

const success = (route: Route, json: unknown, status = 200) => route.fulfill({ status, json });
const failure = (route: Route, status: number, code: string) =>
  success(route, { error: { code, message: "Пояснение сервера", details: {} } }, status);

export async function stubApi(page: Page, options: Partial<State> = {}) {
  const state: State = {
    signedIn: true, status: "queued", uploads: 0, statusRequests: 0, cancellations: 0, keys: [],
    ...options,
  };
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const { pathname, searchParams } = new URL(request.url());
    const path = pathname.replace("/api/v1", "");
    const method = request.method();
    if (path === "/auth/token") {
      if (request.postDataJSON().password !== "local-test-password") return failure(route, 401, "unauthorized");
      state.signedIn = true;
      return success(route, { access_token: "test-access", refresh_token: "test-refresh", expires_in: 60 });
    }
    if (!state.signedIn) return failure(route, 401, "unauthorized");
    if (path === "/auth/me") return success(route, {
      id: userId, organization_id: orgId, email: "qa@example.test", full_name: "Тестовый пользователь",
      permissions: [], is_active: true, role: "user",
      organization: { id: orgId, name: "Тестовая организация", created_at: created },
      created_at: created,
    });
    if (path === "/document-types") return success(route, [documentType]);
    if (path === "/documents" && method === "POST") {
      state.uploads++;
      if (state.uploadError) return failure(route, 422, state.uploadError);
      return success(route, { document_id: documentId, filename, size_bytes: 1 }, 201);
    }
    if (path === "/analyses" && method === "POST") {
      state.keys.push(request.headers()["idempotency-key"]);
      if (state.failFirstStart && state.keys.length === 1) return failure(route, 503, "internal_error");
      return success(route, { analysis_id: id, status: state.status }, 202);
    }
    if (path === "/analyses") return success(route, {
      items: [{ id, filename, status: "completed", status_label: "Завершена", summary: report.summary,
        created_at: created, is_partial: true, has_regulation_updates: true }],
      page: 1, page_size: 20, total: 1,
    });
    if (state.inaccessible) return failure(route, 404, "not_found");
    if (path === `/analyses/${id}/cancel`) {
      state.cancellations++;
      if (state.completesOnCancel) state.status = "completed";
      if (state.status === "completed") return failure(route, 409, "analysis_not_cancellable");
      state.status = "cancelled";
      return route.fulfill({ status: 204 });
    }
    if (path === `/analyses/${id}`) {
      state.statusRequests++;
      return success(route, {
        id, status: state.status, status_label: state.status, stage: state.status === "analyzing" ? "Проверка пунктов: 2 из 5" : "",
        progress: .4, chunks_done: 2, chunks_total: 5, started_at: new Date(Date.now() - 20_000).toISOString(),
        error_code: state.stageError, created_at: created,
      });
    }
    if (path === `/analyses/${id}/result`) return success(route, report);
    if (path === `/analyses/${id}/report`) {
      const format = searchParams.get("format") === "pdf" ? "pdf" : "docx";
      return route.fulfill({
        status: 200, body: "Synthetic download; document content is tested in backend.",
        headers: { "Content-Disposition": `attachment; filename*=UTF-8''report.${format}` },
      });
    }
    return failure(route, 404, "not_found");
  });
  return state;
}

export const file = (name = filename, size = 4) => ({
  name, buffer: Buffer.alloc(size, 65), mimeType: "application/octet-stream",
});
