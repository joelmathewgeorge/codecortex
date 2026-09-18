"use client";

type Props = {
  drawArmed: boolean;
  emergencyBusy: boolean;
  resetBusy: boolean;
  onToggleDraw: () => void;
  onEmergency: () => void;
  onReset: () => void;
};

export default function MapControls({
  drawArmed,
  emergencyBusy,
  resetBusy,
  onToggleDraw,
  onEmergency,
  onReset,
}: Props) {
  return (
    <div className="dag-controls" role="group" aria-label="Airspace controls">
      <button
        type="button"
        className={drawArmed ? "is-on" : ""}
        aria-pressed={drawArmed}
        onClick={onToggleDraw}
      >
        {drawArmed ? "Cancel draw" : "Draw no-fly"}
      </button>
      <button type="button" className="ghost" disabled={resetBusy} onClick={onReset}>
        {resetBusy ? "Resetting" : "Reset demo"}
      </button>
      <button type="button" className="emergency" disabled={emergencyBusy} onClick={onEmergency}>
        {emergencyBusy ? "Dispatching" : "Helicopter inbound"}
      </button>
    </div>
  );
}
