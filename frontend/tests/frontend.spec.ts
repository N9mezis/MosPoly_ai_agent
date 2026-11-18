import { expect, test, type Page } from "@playwright/test";
import { file, id, stubApi } from "./fixtures";

async function openUpload(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Перейти к проверке: Трудовой договор" }).click();
  await expect(page.getByRole("heading", { name: "Загрузите договор" })).toBeVisible();
}

test("вход после перехода по ссылке на сохранённую проверку", async ({ page }) => {
  await stubApi(page, { signedIn: false, status: "completed" });
  await page.goto(`/analyses/${id}/report`);
  await page.getByLabel("Электронная почта").fill("qa@example.test");
  await page.getByLabel("Пароль").fill("wrong-password");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("alert")).toContainText("Неверная почта или пароль");
  await page.getByLabel("Пароль").fill("local-test-password");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Отчёт о проверке" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/analyses/${id}/report$`));
});

test("пустой, большой и неподдерживаемый файлы не отправляются", async ({ page }) => {
  const state = await stubApi(page);
  await openUpload(page);
  const input = page.locator('input[type="file"]');
  const start = page.getByRole("button", { name: "Запустить проверку" });
  for (const [candidate, message] of [
    [file("text.txt"), "Выберите файл в формате"],
    [file("empty.pdf", 0), "Файл пустой"],
    [file("large.pdf", 10 * 1024 * 1024 + 1), "Файл больше 10 МБ"],
  ] as const) {
    await input.setInputFiles(candidate);
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(start).toBeDisabled();
  }
  expect(state.uploads).toBe(0);
});

for (const scenario of [
  { error: "corrupted_file", filename: "broken.docx", hint: "не защищён паролем" },
  { error: "no_text_layer", filename: "scan.pdf", hint: "можно выделить текст" },
]) {
  test(`подсказка сервера для ${scenario.error}`, async ({ page }) => {
    await stubApi(page, { uploadError: scenario.error });
    await openUpload(page);
    await page.locator('input[type="file"]').setInputFiles(file(scenario.filename));
    await page.getByRole("button", { name: "Запустить проверку" }).click();
    await expect(page.getByRole("alert")).toContainText(scenario.hint);
  });
}

test("повтор создания после сбоя не отправляет документ заново", async ({ page }) => {
  const state = await stubApi(page, { failFirstStart: true });
  await openUpload(page);
  await page.locator('input[type="file"]').setInputFiles(file());
  const start = page.getByRole("button", { name: "Запустить проверку" });
  await start.click();
  await expect(page.getByRole("alert")).toContainText("Повторите попытку позже");
  await start.click();
  await expect(page.getByRole("heading", { name: "Статус проверки" })).toBeVisible();
  expect(state.uploads).toBe(1);
  expect(state.keys).toHaveLength(2);
  expect(state.keys[0]).toMatch(/^[0-9a-f]{32}$/);
  expect(state.keys[1]).toBe(state.keys[0]);
});

test("статус обновляется до отчёта; есть прогресс и ориентир", async ({ page }) => {
  const state = await stubApi(page, { status: "queued" });
  await openUpload(page);
  await page.locator('input[type="file"]').setInputFiles(file());
  await page.getByRole("button", { name: "Запустить проверку" }).click();
  await expect(page.getByText("Время зависит от очереди.", { exact: false })).toBeVisible();
  state.status = "extracting";
  await expect(page.locator('[aria-current="step"]')).toHaveText("Извлечение текста");
  state.status = "analyzing";
  await expect(page.getByRole("status").filter({ hasText: "Проверка пунктов: 2 из 5" })).toBeVisible();
  await expect(page.getByText("Ориентир:", { exact: false })).toBeVisible();
  state.status = "completed";
  await expect(page.getByRole("heading", { name: "Отчёт о проверке" })).toBeVisible();
  expect(state.statusRequests).toBeGreaterThanOrEqual(4);
});

test("отмена требует подтверждения и не использует удаление", async ({ page }) => {
  const state = await stubApi(page, { status: "analyzing" });
  await page.goto(`/analyses/${id}`);
  const cancel = page.getByRole("button", { name: "Отменить проверку" });
  await cancel.click();
  await page.getByRole("button", { name: "Продолжить проверку" }).click();
  expect(state.cancellations).toBe(0);
  await cancel.click();
  await page.getByRole("button", { name: "Да, отменить" }).click();
  await expect(page.getByText("Проверка отменена. Отчёт не сформирован.")).toBeVisible();
  expect(state.cancellations).toBe(1);
});

test("при завершении во время отмены открывается сохранённый отчёт", async ({ page }) => {
  const state = await stubApi(page, { status: "analyzing", completesOnCancel: true });
  await page.goto(`/analyses/${id}`);
  await page.getByRole("button", { name: "Отменить проверку" }).click();
  await page.getByRole("button", { name: "Да, отменить" }).click();
  await expect(page.getByRole("heading", { name: "Отчёт о проверке" })).toBeVisible();
  expect(state.cancellations).toBe(1);
});

test("отчёт можно проверить по тексту, норме и сохранённым версиям", async ({ page }) => {
  await stubApi(page);
  await page.goto(`/analyses/${id}/report`);
  await expect(page.getByText("Частичный результат.", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Технические сбои" })).toBeVisible();
  await page.getByRole("button", { name: "Показать: критические" }).click();
  const findings = page.locator("article.finding");
  await expect(findings).toHaveCount(2);
  await page.getByLabel("Сортировка").selectOption("clause");
  await expect(findings.locator("h3")).toHaveText(["Замечание 3.2", "Замечание 3.10"]);
  const changed = findings.filter({ hasText: "Замечание 3.10" });
  await changed.getByText("Открыть норму и редакцию", { exact: true }).click();
  await expect(changed).toContainText("Текст нормы в активной редакции базы изменился");
  await expect(changed.getByText("Полный тестовый фрагмент нормы в архивной редакции.")).toBeVisible();
  await expect(changed.getByRole("link", { name: "Открыть источник нормы" })).toHaveAttribute("href", "https://example.test/norm");
  await findings.first().getByRole("button", { name: "К фрагменту договора" }).click();
  await expect(page.getByRole("link", { name: "Пример условия", exact: true })).toBeFocused();
  await page.getByRole("link", { name: "Пример условия", exact: true }).click();
  await expect(findings.first()).toBeFocused();
  await page.getByText("Номер проверки и использованные версии", { exact: true }).click();
  await expect(page.getByText(id, { exact: true })).toBeVisible();
  for (const format of ["PDF", "DOCX"]) {
    const waiting = page.waitForEvent("download");
    await page.getByRole("button", { name: "Скачать " + format }).click();
    expect((await waiting).suggestedFilename()).toBe("report." + format.toLowerCase());
  }
});

test("история показывает пометки и открывает результат по номеру", async ({ page }) => {
  await stubApi(page, { status: "completed" });
  await page.goto("/history");
  await expect(page.getByText("Есть нормы для сверки")).toBeVisible();
  await expect(page.getByText("Частичный результат")).toBeVisible();
  await page.getByLabel("Номер проверки").fill("123");
  await page.getByRole("button", { name: "Открыть сохранённую проверку" }).click();
  await expect(page.getByRole("alert")).toContainText("Скопируйте номер целиком");
  await page.getByLabel("Номер проверки").fill(id);
  await page.getByRole("button", { name: "Открыть сохранённую проверку" }).click();
  await expect(page.getByRole("heading", { name: "Отчёт о проверке" })).toBeVisible();
});

test("чужая запись не раскрывается", async ({ page }) => {
  await stubApi(page, { inaccessible: true });
  await page.goto(`/analyses/${id}/report`);
  await expect(page.getByRole("alert")).toContainText("Запись не найдена или недоступна");
  await expect(page.getByRole("heading", { name: "Текст договора" })).toHaveCount(0);
});

test("ошибка типа документа объясняет, что загрузить взамен", async ({ page }) => {
  await stubApi(page, { status: "failed", stageError: "not_employment_contract" });
  await page.goto(`/analyses/${id}`);
  await expect(page.getByRole("alert")).toContainText("Выберите трудовой договор");
  await expect(page.getByRole("link", { name: "Новая проверка", exact: true })).toBeVisible();
});
