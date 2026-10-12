import { useEffect, useRef, useState } from 'react';

export type LabItem = { id: string; label: string; caption: string };

type LabsMenuProps = {
  labs: LabItem[];
  /** The lab currently open, if any. */
  currentId: string | null;
  onSelect: (id: string) => void;
};

/** The admin header's "Course labs" dropdown: one entry per week's page. */
export default function LabsMenu({ labs, currentId, onSelect }: LabsMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="labs-menu" ref={rootRef}>
      <button
        type="button"
        className="header-btn"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        Course labs ▾
      </button>
      {open ? (
        <ul className="labs-menu-list">
          {labs.map((lab) => (
            <li key={lab.id}>
              <button
                type="button"
                className={lab.id === currentId ? 'is-active' : undefined}
                aria-current={lab.id === currentId ? 'page' : undefined}
                onClick={() => {
                  setOpen(false);
                  onSelect(lab.id);
                }}
              >
                <strong>{lab.label}</strong>
                <span>{lab.caption}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
