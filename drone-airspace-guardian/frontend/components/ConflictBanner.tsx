"use client";

export default function ConflictBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="dag-banner" role="alert">
      {message}
    </div>
  );
}
