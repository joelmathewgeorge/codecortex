"""
Generate synthetic turbofan-like training data for RUL prediction.

This simulates the NASA C-MAPSS dataset format:
- Multiple units (engines/drones) that degrade over time
- Each row is one operational cycle
- Sensors show degradation patterns as cycles increase
"""

import numpy as np
import pandas as pd

np.random.seed(42)

# Configuration
NUM_UNITS = 50  # Number of drones/engines
MIN_CYCLES = 150
MAX_CYCLES = 250
NUM_SENSORS = 21  # Standard C-MAPSS has 21 sensors
NUM_SETTINGS = 3  # Operating conditions

print("Generating synthetic training data...")
print(f"   - {NUM_UNITS} units (drones)")
print(f"   - {MIN_CYCLES}-{MAX_CYCLES} cycles per unit")
print(f"   - {NUM_SENSORS} sensors + {NUM_SETTINGS} settings\n")

data_rows = []

for unit in range(1, NUM_UNITS + 1):
    # Each unit has a random lifespan
    max_cycles = np.random.randint(MIN_CYCLES, MAX_CYCLES)
    
    for cycle in range(1, max_cycles + 1):
        # Operating settings (altitude, throttle, temperature)
        setting1 = np.random.uniform(0.0, 0.1)
        setting2 = np.random.uniform(0.6, 0.7)
        setting3 = np.random.uniform(100, 110)
        
        # Sensor readings degrade as cycles increase
        # Early cycles: low values, Late cycles: high values (wear)
        degradation_factor = cycle / max_cycles  # 0 to 1
        
        sensors = []
        for s in range(NUM_SENSORS):
            # Base value + degradation noise
            base = np.random.uniform(500, 600)
            degradation = degradation_factor * np.random.uniform(50, 150)
            noise = np.random.normal(0, 10)
            sensor_value = base + degradation + noise
            sensors.append(sensor_value)
        
        # Build row: [unit, cycle, setting1-3, sensor1-21]
        row = [unit, cycle, setting1, setting2, setting3] + sensors
        data_rows.append(row)
    
    if unit % 10 == 0:
        print(f"   Generated unit {unit}/{NUM_UNITS}")

# Create DataFrame
columns = ['unit', 'cycle', 'setting1', 'setting2', 'setting3'] + \
          [f'sensor{i}' for i in range(1, NUM_SENSORS + 1)]

df = pd.DataFrame(data_rows, columns=columns)

# Calculate RUL for each row
def calculate_rul(group):
    max_cycle = group['cycle'].max()
    group['RUL'] = max_cycle - group['cycle']
    return group

df = df.groupby('unit', group_keys=False).apply(calculate_rul)

# Save as space-separated txt (NASA format)
output_path = 'train_FD001.txt'
df.to_csv(output_path, sep=' ', index=False, header=False)

print(f"\nCreated {output_path}")
print(f"   Total samples: {len(df)}")
print(f"   Columns: {len(columns)} + RUL")
print(f"\nSample data (first 3 rows):")
print(df.head(3))
print(f"\nRUL statistics:")
print(df['RUL'].describe())
