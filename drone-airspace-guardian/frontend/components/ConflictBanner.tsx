"use client";

export default function ConflictBanner({ message }: { message: string | null }) {
  return (
    <div className={`dag-banner ${message ? "is-on" : ""}`} role="alert" aria-live="assertive">
      <span className="pip" aria-hidden="true" />
      <span className="text">{message}</span>
    </div>
  );
}
