"""
CRITICAL SANITY CHECK

This test MUST pass before integration!

Test: Do degrading sensors produce decreasing health scores?
Expected: Health should drop from ~100% to <50% over time
"""

from predict import predict_health, generate_degrading_sensors
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

print("="*70)
print("SANITY CHECK: Degrading Sensors -> Dropping Health")
print("="*70)

# Generate strongly degrading sensor trace
print("\n[1/3] Generating degrading sensor trace (100 ticks)...")
sensor_trace = generate_degrading_sensors(num_ticks=100, degradation_rate=0.04)
print("      Generated!")

# Predict health at each tick
print("\n[2/3] Predicting health scores...")
health_scores = []
for tick, sensors in enumerate(sensor_trace):
    health = predict_health(sensors)
    health_scores.append(health)
    
    # Show progress every 20 ticks
    if tick % 20 == 0 or tick == 99:
        print(f"      Tick {tick:3d}: Health = {health:5.1f}%")

print("\n[3/3] Analyzing results...")

# Calculate health drop
initial_health = health_scores[0]
final_health = health_scores[-1]
health_drop = initial_health - final_health
drop_percentage = (health_drop / initial_health) * 100

print(f"\n{'='*70}")
print("RESULTS:")
print(f"{'='*70}")
print(f"  Initial Health (Tick 0):   {initial_health:.1f}%")
print(f"  Final Health (Tick 99):    {final_health:.1f}%")
print(f"  Total Drop:                {health_drop:.1f} points")
print(f"  Drop Percentage:           {drop_percentage:.1f}%")

# Determine if test passed
print(f"\n{'='*70}")
if health_drop > 20 and drop_percentage > 15:
    print("RESULT: PASS")
    print(f"{'='*70}")
    print("\nThe model correctly detects degradation!")
    print(f"Health dropped by {drop_percentage:.1f}%, which is significant.")
    print("\nYou can confidently integrate this into the backend.")
    test_passed = True
else:
    print("RESULT: FAIL")
    print(f"{'='*70}")
    print("\nThe model did NOT detect significant degradation.")
    print(f"Health only dropped by {drop_percentage:.1f}%.")
    print("The model might need retraining with better features.")
    test_passed = False

# Create visualization
print("\n[Bonus] Creating health trend chart...")
plt.figure(figsize=(10, 6))
plt.plot(range(len(health_scores)), health_scores, linewidth=2, color='#2E86AB')
plt.axhline(y=80, color='green', linestyle='--', alpha=0.5, label='Excellent (80%+)')
plt.axhline(y=60, color='yellow', linestyle='--', alpha=0.5, label='Good (60-80%)')
plt.axhline(y=40, color='orange', linestyle='--', alpha=0.5, label='Fair (40-60%)')
plt.axhline(y=20, color='red', linestyle='--', alpha=0.5, label='Critical (<20%)')
plt.xlabel('Flight Cycle (Tick)', fontsize=12)
plt.ylabel('Health Score (%)', fontsize=12)
plt.title('Drone Health Degradation Over Time', fontsize=14, fontweight='bold')
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('health_degradation.png', dpi=150)
print("      Saved as: health_degradation.png")

print(f"\n{'='*70}")
if test_passed:
    print("Ready for integration with backend!")
else:
    print("Needs improvement before integration")
print(f"{'='*70}\n")
