interface Props {
  suggestions: string[];
  disabled: boolean;
  onPick: (text: string) => void;
}

export default function SuggestionChips({ suggestions, disabled, onPick }: Props) {
  if (suggestions.length === 0) return null;
  return (
    <div className="mb-2 flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Suggested messages">
      {suggestions.map((text) => (
        <button
          key={text}
          type="button"
          disabled={disabled}
          onClick={() => onPick(text)}
          className="shrink-0 rounded-full border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs text-sky-900 hover:bg-sky-100 disabled:opacity-50"
        >
          {text}
        </button>
      ))}
    </div>
  );
}
