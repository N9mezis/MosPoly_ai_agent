import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { components } from "./api/client";
import { Icon } from "./ui";

type ContractType = components["schemas"]["DocumentTypeOut"];

export function ContractTypeSelect({ options = [], value, onChange, disabled }: {
  options?: ContractType[];
  value?: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const search = useRef({ text: "", time: 0 });
  const [open, setOpen] = useState(false);
  const [above, setAbove] = useState(false);
  const [activeId, setActiveId] = useState<string>();
  const enabled = options.filter(option => option.is_enabled);
  const selected = enabled.find(option => option.id === value);
  const activeIndex = enabled.findIndex(option => option.id === activeId);
  const expanded = open && !disabled;
  const optionId = (option: string) => `${id}-option-${option}`;

  useEffect(() => {
    if (!expanded) return;
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [expanded]);

  useEffect(() => {
    if (expanded && activeId) {
      document.getElementById(`${id}-option-${activeId}`)?.scrollIntoView({ block: "nearest" });
    }
  }, [expanded, activeId, id]);

  function show(option = selected ?? enabled[0]) {
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) {
      const spaceBelow = window.innerHeight - rect.bottom;
      setAbove(spaceBelow < 240 && rect.top > spaceBelow);
    }
    search.current = { text: "", time: 0 };
    setActiveId(option?.id);
    setOpen(true);
  }

  function choose(option?: ContractType) {
    if (!option?.is_enabled) return;
    if (option.id !== selected?.id) onChange(option.id);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const first = enabled[0];
    const last = enabled[enabled.length - 1];
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        const down = event.key === "ArrowDown";
        if (!expanded) {
          show(selected ?? (down ? first : last));
          return;
        }
        const nextIndex = activeIndex < 0
          ? (down ? 0 : enabled.length - 1)
          : Math.min(enabled.length - 1, Math.max(0, activeIndex + (down ? 1 : -1)));
        setActiveId(enabled[nextIndex]?.id);
        return;
      }
      case "Home":
      case "End": {
        event.preventDefault();
        const option = event.key === "Home" ? first : last;
        if (expanded) setActiveId(option?.id);
        else show(option);
        return;
      }
      case "Enter":
      case " ":
        event.preventDefault();
        if (expanded) choose(enabled[activeIndex]);
        else show();
        return;
      case "Escape":
        if (expanded) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
        }
        return;
      case "Tab":
        setOpen(false);
        return;
    }
    if (event.key.length !== 1 || event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing) return;
    const now = Date.now();
    const letter = event.key.toLocaleLowerCase("ru");
    const prefix = now - search.current.time < 650 ? search.current.text + letter : letter;
    const repeated = [...prefix].every(character => character === letter);
    const candidates = repeated && expanded
      ? [...enabled.slice(activeIndex + 1), ...enabled.slice(0, activeIndex + 1)]
      : enabled;
    const match = candidates.find(option => option.title.toLocaleLowerCase("ru").startsWith(repeated ? letter : prefix));
    if (!expanded) show(match);
    else if (match) setActiveId(match.id);
    search.current = { text: prefix, time: now };
  }

  return <div ref={root} className="contract-select" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}>
    <label id={`${id}-label`} htmlFor={id}>Тип договора</label>
    <div className="contract-select-field">
      <button ref={trigger} id={id} type="button" className="contract-select-trigger" role="combobox"
        aria-labelledby={`${id}-label`} aria-describedby={`${id}-value`}
        aria-expanded={expanded} aria-controls={`${id}-list`}
        aria-activedescendant={expanded && activeIndex >= 0 ? optionId(enabled[activeIndex].id) : undefined}
        disabled={disabled} onKeyDown={onKeyDown} onClick={event => {
          event.currentTarget.focus();
          if (expanded) setOpen(false);
          else show();
        }}>
        <span className="contract-select-icon"><Icon name="documents" size={18} /></span>
        <span id={`${id}-value`} className={selected ? undefined : "muted"}>
          {selected?.title ?? "Выберите тип договора"}
        </span>
        <span className="contract-select-chevron" aria-hidden="true" />
      </button>
      <ul id={`${id}-list`} role="listbox" aria-labelledby={`${id}-label`} hidden={!expanded}
        className="contract-select-list" data-above={above}>
        {options.map(option => <li key={option.id} id={optionId(option.id)} role="option"
          className="contract-select-option" aria-selected={option.id === selected?.id}
          aria-disabled={!option.is_enabled || undefined} data-active={option.id === activeId}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(option)}>
          <span>{option.title}</span>
          {option.is_enabled
            ? option.id === selected?.id && <span className="contract-select-check" aria-hidden="true" />
            : <span className="contract-select-status">В разработке</span>}
        </li>)}
      </ul>
    </div>
  </div>;
}
