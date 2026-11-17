import { useId, useRef, useState } from "react";

type IconName = "documents" | "history" | "library" | "users" | "upload";

const paths: Record<IconName, string> = {
  documents: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h5",
  history: "M3 12a9 9 0 1 1 2.64 6.36 M3 6v6h6 M12 7v5l3 2",
  library: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z M8 7h8 M8 11h6",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M22 21v-2a4 4 0 0 0-3-3.87 M13 7a4 4 0 1 1-8 0a4 4 0 0 1 8 0 M16 3.13a4 4 0 0 1 0 7.75",
  upload: "M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4",
};

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={paths[name]} />
  </svg>;
}

export function Busy({ children }: { children: string }) {
  return <p className="busy" role="status"><span aria-hidden="true" className="spinner" />{children}</p>;
}

export function fileExtension(name: string) {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot + 1).toLowerCase();
}

export function FilePicker({ file, onChange, accept, hint, disabled }: {
  file?: File;
  onChange: (file?: File) => void;
  accept: string;
  hint: string;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const hintId = useId();
  return <div className="file-picker">
    <input hidden ref={input} type="file" accept={accept} disabled={disabled}
      onChange={event => {
        const next = event.target.files?.[0];
        if (next) onChange(next);
        event.target.value = "";
      }} />
    <button type="button" className={dragging ? "drop active" : "drop"} aria-label="Выбрать файл"
      aria-describedby={hintId} disabled={disabled}
      onClick={() => input.current?.click()}
      onDragOver={event => { event.preventDefault(); if (!disabled) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={event => {
        event.preventDefault();
        setDragging(false);
        if (!disabled && event.dataTransfer.files[0]) onChange(event.dataTransfer.files[0]);
      }}>
      <span>
        <span className="upload-icon"><Icon name="upload" size={24} /></span>
        <strong>Выберите файл или перетащите его сюда</strong>
        <span className="muted file-hint" id={hintId}>{hint}</span>
      </span>
    </button>
    {file && <div className="file-card">
      <span className="file-type" aria-hidden="true">{fileExtension(file.name).toUpperCase()}</span>
      <span className="file-details"><strong>{file.name}</strong>
        <span>{new Intl.NumberFormat("ru-RU").format(Math.ceil(file.size / 1024))} КБ</span>
      </span>
      <button type="button" className="secondary" disabled={disabled}
        aria-label="Убрать выбранный файл" onClick={() => onChange()}>Убрать</button>
    </div>}
  </div>;
}
