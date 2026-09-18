"""
Drone Health Prediction System

SIMPLE EXPLANATION:
This file has two main things:
1. predict_health() - Takes sensor readings, returns health score (0-100)
2. generate_degrading_sensors() - Fake sensor data that gets worse over time

Think of it like a doctor's thermometer for drones!
"""

import joblib
import numpy as np
import pandas as pd

# Load the trained model (the "brain")
MODEL = joblib.load('rul_model.joblib')
print("Loaded trained RUL prediction model")

def predict_health(sensor_row):
    """
    Predict drone health from sensor readings.
    
    Args:
        sensor_row: Dictionary with keys:
            - 'cycle': Current flight number
            - 'setting1', 'setting2', 'setting3': Operating conditions  
            - 'sensor1' through 'sensor21': Sensor readings
    
    Returns:
        Health score from 0 (broken) to 100 (perfect)
    
    Example:
        sensors = {
            'cycle': 50,
            'setting1': 0.05,
            'setting2': 0.65,
            'setting3': 105,
            'sensor1': 520, 'sensor2': 540, ... 'sensor21': 510
        }
        health = predict_health(sensors)
        print(f"Drone health: {health}%")
    """
    
    # Expected feature order
    feature_names = ['cycle', 'setting1', 'setting2', 'setting3'] + \
                    [f'sensor{i}' for i in range(1, 22)]
    
    # Build feature vector in correct order
    features = [sensor_row[name] for name in feature_names]
    features_array = np.array(features).reshape(1, -1)
    
    # Predict RUL (remaining useful life in cycles)
    predicted_rul = MODEL.predict(features_array)[0]
    
    # Convert RUL to health score (0-100)
    # Assumption: A "new" drone has ~200 cycles of life
    # Health = (RUL / 200) * 100, capped at 100
    MAX_EXPECTED_RUL = 200
    health_score = min(100, (predicted_rul / MAX_EXPECTED_RUL) * 100)
    health_score = max(0, health_score)  # Can't be negative
    
    return round(health_score, 1)


def generate_degrading_sensors(num_ticks=100, degradation_rate=0.02):
    """
    Generate fake sensor data that degrades over time.
    
    This simulates a drone that starts healthy but gets worse.
    Like watching a toy's battery drain!
    
    Args:
        num_ticks: How many time steps to generate
        degradation_rate: How fast sensors degrade (0.02 = 2% per tick)
    
    Returns:
        List of sensor dictionaries, one per tick
    
    Example:
        traces = generate_degrading_sensors(num_ticks=50)
        for tick, sensors in enumerate(traces):
            health = predict_health(sensors)
            print(f"Tick {tick}: Health = {health}%")
    """
    
    print(f"\nGenerating {num_ticks} ticks of degrading sensor data...")
    
    traces = []
    
    for tick in range(num_ticks):
        # Operating settings (relatively stable)
        setting1 = np.random.uniform(0.04, 0.06)
        setting2 = np.random.uniform(0.64, 0.66)
        setting3 = np.random.uniform(104, 106)
        
        # Sensors start at baseline and degrade
        # Degradation increases with time
        degradation_factor = 1 + (tick * degradation_rate)
        
        sensors = {
            'cycle': tick + 1,
            'setting1': setting1,
            'setting2': setting2,
            'setting3': setting3
        }
        
        # Generate 21 sensors with increasing values (simulating wear)
        for s in range(1, 22):
            base_value = np.random.uniform(500, 520)
            degradation = (tick / num_ticks) * np.random.uniform(50, 100)
            noise = np.random.normal(0, 5)
            sensors[f'sensor{s}'] = base_value + degradation + noise
        
        traces.append(sensors)
    
    print(f"Generated {len(traces)} sensor snapshots")
    return traces


# Demo function
if __name__ == "__main__":
    print("="*60)
    print("DRONE HEALTH PREDICTION - DEMO")
    print("="*60)
    
    # Generate degrading sensor trace
    sensor_trace = generate_degrading_sensors(num_ticks=50, degradation_rate=0.03)
    
    print("\nPredicting health at different time points...")
    print(f"{'Tick':<10} {'Health':<10} {'Status'}")
    print("-" * 40)
    
    # Show health at intervals
    for i in [0, 10, 20, 30, 40, 49]:
        health = predict_health(sensor_trace[i])
        
        if health >= 80:
            status = "Excellent"
        elif health >= 60:
            status = "Good"
        elif health >= 40:
            status = "Fair"
        elif health >= 20:
            status = "Poor"
        else:
            status = "Critical"
        
        print(f"{i:<10} {health:<10} {status}")
    
    print("\n" + "="*60)
    print("Demo complete! The health score drops as sensors degrade.")
    print("="*60)
