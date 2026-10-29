/** Find a catalogue item by name and hand back its slug for a `[[skin:…]]` card. */
import { findItems } from "@/features/catalogue/api";
import { SkinSearch } from "@/features/catalogue/SkinSearch";

interface SkinPickerProps {
  onPick: (slug: string) => void;
}

export function SkinPicker({ onPick }: SkinPickerProps) {
  return (
    <div className="border-border bg-surface rounded-lg border p-3">
      <SkinSearch
        label="Поиск скина"
        autoFocus
        find={(q) => findItems({ q })}
        onPick={(item) => {
          onPick(item.slug);
        }}
      />
    </div>
  );
}
