import type { QuickReply } from "../types";

interface Props {
  replies: QuickReply[];
  disabled: boolean;
  onPick: (reply: QuickReply) => void;
}

export default function QuickReplies({ replies, disabled, onPick }: Props) {
  if (replies.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Quick replies">
      {replies.map((r) => (
        <button
          key={r.action}
          type="button"
          disabled={disabled}
          onClick={() => onPick(r)}
          className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
