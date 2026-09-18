"use client";

export default function ErrorNotice({
  text,
  onDismiss,
}: {
  text: string | null;
  onDismiss: () => void;
}) {
  if (!text) return null;
  return (
    <div className="dag-error" role="status">
      <span>{text}</span>
      <button type="button" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
