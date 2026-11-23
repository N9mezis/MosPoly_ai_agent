import { expect, test, type Page } from "@playwright/test";
import { documentType, file, id, stubApi } from "./fixtures";

async function openUpload(page: Page) {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Тип договора" }).click();
  await page.getByRole("option", { name: "Трудовой договор", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Загрузите договор" })).toBeVisible();
}

test("на одном экране выбор типа открывает загрузку, а недоступные типы отключены", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  const picker = page.getByRole("button", { name: "Выбрать файл" });
  const types = page.getByRole("combobox", { name: "Тип договора" });
  await expect(types).toBeEnabled();
  await expect(picker).toBeDisabled();
  await types.click();
  const disabledType = page.getByRole("option", { name: /NDA/ });
  await expect(disabledType).toBeDisabled();
  await expect(disabledType).toContainText("В разработке");
  await page.getByRole("option", { name: "Трудовой договор", exact: true }).click();
  await expect(picker).toBeEnabled();
  await expect(types).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByText("Область проверки: Выборочные нормы")).toBeVisible();
  await expect(page).toHaveURL("/");
});

test("смена типа очищает файл, а старая ссылка открывается с выбранным типом", async ({ page }) => {
  await stubApi(page, { documentTypes: [documentType, {
    ...documentType, id: "test-other", title: "Другой тестовый профиль", allowed_extensions: ["pdf"],
  }] });
  await page.goto("/check/employment-contract");
  const types = page.getByRole("combobox", { name: "Тип договора" });
  await expect(types).toContainText("Трудовой договор");
  const input = page.locator('input[type="file"]');
  await input.setInputFiles(file());
  const start = page.getByRole("button", { name: "Запустить проверку" });
  await expect(start).toBeEnabled();
  await types.press("Space");
  await types.press("ArrowDown");
  await types.press("Escape");
  await expect(types).toContainText("Трудовой договор");
  await expect(start).toBeEnabled();
  await types.press("Enter");
  await types.press("ArrowDown");
  await types.press("Enter");
  await expect(types).toContainText("Другой тестовый профиль");
  await expect(page.getByText("test-contract.docx")).toHaveCount(0);
  await expect(start).toBeDisabled();
  await expect(input).toHaveAttribute("accept", ".pdf");
});

test("меню на узком экране закрывается по клику вне списка", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await stubApi(page);
  await page.goto("/");
  const types = page.getByRole("combobox", { name: "Тип договора" });
  await types.click();
  const list = page.getByRole("listbox", { name: "Тип договора" });
  await expect(list).toBeVisible();
  const box = await list.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.getByRole("heading", { name: "Проверка договора", exact: true }).click();
  await expect(list).toBeHidden();
  await expect(types).toContainText("Выберите тип договора");
});

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
