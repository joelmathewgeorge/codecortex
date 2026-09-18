"use client";

type Props = {
  drawArmed: boolean;
  emergencyBusy: boolean;
  onToggleDraw: () => void;
  onEmergency: () => void;
};

export default function MapControls({ drawArmed, emergencyBusy, onToggleDraw, onEmergency }: Props) {
  return (
    <div className="dag-controls">
      <button
        type="button"
        className={drawArmed ? "is-on" : ""}
        aria-pressed={drawArmed}
        onClick={onToggleDraw}
      >
        {drawArmed ? "Cancel zone" : "Draw zone"}
      </button>
      <button
        type="button"
        className="emergency"
        disabled={emergencyBusy}
        onClick={onEmergency}
      >
        Emergency: helicopter inbound
      </button>
    </div>
  );
}
