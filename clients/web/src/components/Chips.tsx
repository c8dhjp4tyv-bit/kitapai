import type { TaxonomyEntry } from '@kitapai/shared';

interface Props {
  entries: TaxonomyEntry[];
  selected: string[];
  onToggle: (slug: string) => void;
  max?: number;
}

/** Çoklu seçim rozetleri (tür, ruh hali). */
export function ChipGroup({ entries, selected, onToggle, max }: Props) {
  const visible = max ? entries.slice(0, max) : entries;
  return (
    <div className="chips" role="group">
      {visible.map((entry) => {
        const active = selected.includes(entry.slug);
        return (
          <button
            key={entry.slug}
            type="button"
            className={active ? 'chip chip--active' : 'chip'}
            aria-pressed={active}
            title={entry.description}
            onClick={() => onToggle(entry.slug)}
          >
            {entry.label}
          </button>
        );
      })}
    </div>
  );
}

interface SingleProps {
  entries: TaxonomyEntry[];
  value: string | null;
  onChange: (slug: string | null) => void;
  label: string;
}

/** Tek seçim (dönem, uzunluk, okur kitlesi) — seçiliye tekrar basınca temizlenir. */
export function ChipSelect({ entries, value, onChange, label }: SingleProps) {
  return (
    <div className="field">
      <span className="field__label">{label}</span>
      <div className="chips">
        {entries.map((entry) => (
          <button
            key={entry.slug}
            type="button"
            className={value === entry.slug ? 'chip chip--active' : 'chip'}
            aria-pressed={value === entry.slug}
            onClick={() => onChange(value === entry.slug ? null : entry.slug)}
          >
            {entry.label}
          </button>
        ))}
      </div>
    </div>
  );
}
