import { ApiError } from "./api/client";

export type Problem = { title: string; hint: string };

const fileFormat: Problem = { title: "Формат файла не поддерживается", hint: "Сохраните договор в DOCX или PDF с текстовым слоем." };
const fileLarge: Problem = { title: "Файл превышает допустимый размер", hint: "Уменьшите размер файла и выберите его заново." };
const missingFile: Problem = { title: "Исходный файл недоступен", hint: "Загрузите документ заново." };
const fileBroken: Problem = { title: "Не удалось прочитать файл", hint: "Проверьте, что он открывается, не защищён паролем, и сохраните его заново." };
const serverError: Problem = { title: "Сервис не смог выполнить запрос", hint: "Повторите попытку позже. Если сбой повторяется, сообщите администратору." };
const nonCancellable: Problem = { title: "Проверка уже завершилась", hint: "Откройте её актуальный статус или отчёт." };
const problems: Record<string, Problem> = {
  network_error: { title: "Нет связи с сервером", hint: "Проверьте подключение и повторите запрос." },
  unsupported_format: fileFormat,
  http_415: fileFormat,
  file_too_large: fileLarge,
  http_413: fileLarge,
  empty_file: { title: "Файл пустой", hint: "Выберите заполненный договор." },
  corrupted_file: fileBroken,
  parse_failed: fileBroken,
  no_text_layer: { title: "У PDF нет текстового слоя", hint: "Загрузите исходный DOCX или PDF, в котором можно выделить текст." },
  document_rejected: { title: "Документ не принят", hint: "Проверьте формат, размер и доступность текста в файле." },
  file_missing: missingFile,
  document_already_processed: missingFile,
  not_employment_contract: { title: "Документ не похож на трудовой договор", hint: "Выберите трудовой договор. Другие типы пока недоступны." },
  document_type_disabled: { title: "Этот тип договора пока недоступен", hint: "Вернитесь в каталог и выберите доступный тип." },
  knowledge_base_empty: { title: "Нет активной нормативной базы", hint: "Попросите эксперта активировать редакцию и запустите новую проверку." },
  worker_lost: { title: "Обработка прервалась при перезапуске сервиса", hint: "Загрузите документ и запустите новую проверку." },
  analysis_exists: { title: "Проверка уже запущена", hint: "Откройте её в истории проверок." },
  bad_request: { title: "Запрос не принят", hint: "Проверьте заполненные данные и попробуйте ещё раз." },
  analysis_not_completed: { title: "Отчёт пока недоступен", hint: "Откройте статус проверки, чтобы узнать причину." },
  analysis_not_cancellable: nonCancellable,
  unauthorized: { title: "Нужно войти в аккаунт", hint: "Войдите повторно и продолжите работу." },
  forbidden: { title: "Недостаточно прав", hint: "Если доступ нужен для работы, обратитесь к администратору." },
  not_found: { title: "Запись не найдена или недоступна", hint: "Сверьте ссылку и убедитесь, что вошли в нужный аккаунт." },
  regulation_rejected: { title: "Файл нормативной базы не принят", hint: "Проверьте формат JSON, идентификатор источника и список фрагментов." },
  duplicate_version: { title: "Такая редакция уже загружена", hint: "Откройте её в списке версий." },
  version_not_ready: { title: "Редакция ещё не готова", hint: "Дождитесь успешной индексации и повторите действие." },
  validation_error: { title: "Не удалось проверить данные", hint: "Проверьте заполненные поля и повторите действие." },
  not_implemented: { title: "Функция пока недоступна", hint: "Продолжите работу в доступных разделах." },
  internal_error: serverError,
};

export function describeProblem(error: Error, context?: "login"): Problem {
  if (error instanceof ApiError) {
    if (context === "login" && error.status === 401) {
      return { title: "Неверная почта или пароль", hint: "Проверьте раскладку и повторите вход." };
    }
    if (error.code && Object.prototype.hasOwnProperty.call(problems, error.code)) return problems[error.code];
    if (error.status >= 500) return serverError;
    return {
      title: error.message,
      hint: error.status === 409 ? "Обновите данные и проверьте состояние записи."
        : "Проверьте данные и повторите попытку.",
    };
  }
  return serverError;
}
