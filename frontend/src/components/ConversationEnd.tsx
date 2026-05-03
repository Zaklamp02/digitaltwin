interface Props {
  message: string | null;
  onNew: () => void;
  t?: (key: string, fallback?: string) => string;
}

export function ConversationEnd({ message, onNew, t }: Props) {
  const _t = t ?? ((k: string, fb?: string) => fb ?? k);
  return (
    <div className="border-t border-ink/10 dark:border-white/10 bg-white dark:bg-gray-900 p-4 text-center">
      <p className="text-sm text-ink/70 dark:text-white/60 max-w-md mx-auto leading-relaxed">
        {message ?? _t("ui.session_end_message", "That's the end of this session. Start a new one to keep chatting.")}
      </p>
      <button
        onClick={onNew}
        className="mt-3 inline-flex items-center rounded-full bg-accent text-white px-5 py-2 text-sm font-medium hover:bg-accent-fg"
      >
        {_t("ui.new_conversation", "New conversation")}
      </button>
    </div>
  );
}
