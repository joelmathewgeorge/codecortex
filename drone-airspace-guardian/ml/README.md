# ML - Drone Health Prediction

**Owner:** Rohit ([@vrrroro](https://github.com/vrrroro))

## What This Does

Predicts drone health (0-100%) from sensor readings using a machine learning model.

**Simple Explanation:**  
Imagine your drone has a fitness tracker. This ML system looks at the sensor data (like temperature, vibration) and says "Your drone is 85% healthy" or "Only 35% healthy - fix it soon!"

---

## Files

### Core Files (Ready for Integration)

- **`rul_model.joblib`** - Trained Random Forest model (the "brain")
- **`predict.py`** - Health prediction function and sensor generator
- **`trajectories.json`** - 7 realistic flight paths for mission planning

### Training/Setup Files

- **`train_model.py`** - Trains the RUL prediction model
- **`generate_training_data.py`** - Creates synthetic training data
- **`generate_trajectories.py`** - Creates flight path waypoints
- **`train_FD001.txt`** - Training dataset (10,105 samples)

---

## Quick Start

### 1. Setup (One-time)

```bash
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux

# Install packages
pip install pandas scikit-learn joblib numpy
```

### 2. Predict Drone Health

```python
from predict import predict_health

# Example sensor readings
sensors = {
    'cycle': 50,
    'setting1': 0.05,
    'setting2': 0.65,
    'setting3': 105.0,
    'sensor1': 520.0,
    'sensor2': 540.0,
    # ... sensor3 through sensor21
    'sensor21': 510.0
}

health = predict_health(sensors)
print(f"Drone health: {health}%")  # e.g., "Drone health: 82.5%"
```

### 3. Generate Test Data

```python
from predict import generate_degrading_sensors

# Generate 100 time steps of degrading sensors
sensor_trace = generate_degrading_sensors(num_ticks=100)

# Test the model
for tick in range(0, 100, 20):
    health = predict_health(sensor_trace[tick])
    print(f"Tick {tick}: {health}% healthy")
```

---

## How It Works

### Training Process

1. **Generate Data** (`generate_training_data.py`)
   - Creates 10,105 samples from 50 simulated drones
   - Each drone runs 150-250 cycles before failure
   - 21 sensors show degradation over time
   - RUL = (max_cycle - current_cycle)

2. **Train Model** (`train_model.py`)
   - Random Forest with 100 trees
   - Features: cycle + 3 settings + 21 sensors
   - Target: Remaining Useful Life (RUL) in cycles
   - Performance: **R² = 0.867** (87% accuracy)

3. **Convert RUL → Health** (`predict.py`)
   - Assumes max lifespan = 200 cycles
   - Health = (RUL / 200) × 100
   - Capped at 0-100 range

### Model Performance

```
Test Set Results:
  - Mean Absolute Error: 18.2 cycles
  - R² Score: 0.867
  
Translation: On average, predictions are off by 18 cycles.
If true RUL is 100 cycles, model might predict 82-118.
```

---

## Integration with Backend (Pranav)

### Use the Model

```python
import joblib
model = joblib.load('ml/rul_model.joblib')
```

### Use Trajectories

```python
import json

with open('ml/trajectories.json', 'r') as f:
    trajectories = json.load(f)

# Get a specific route
patrol_route = trajectories['patrol_north']
waypoints = patrol_route['waypoints']

# Each waypoint is [latitude, longitude, altitude_meters]
for wp in waypoints:
    lat, lon, alt = wp
    # Send to drone...
```

### Example API Integration

```python
# Hypothetical backend endpoint
@app.post("/api/drone/health")
def check_drone_health(drone_id: str, sensor_data: dict):
    # sensor_data contains cycle, settings, sensors 1-21
    health_score = predict_health(sensor_data)
    
    if health_score < 20:
        return {"status": "critical", "health": health_score, "action": "ground_immediately"}
    elif health_score < 40:
        return {"status": "poor", "health": health_score, "action": "schedule_maintenance"}
    elif health_score < 70:
        return {"status": "fair", "health": health_score, "action": "monitor_closely"}
    else:
        return {"status": "good", "health": health_score, "action": "continue_operations"}
```

---

## Retraining the Model

If you get real drone sensor data:

1. Format it as: `unit, cycle, setting1-3, sensor1-21, RUL`
2. Save as `train_FD001.txt` (space-separated, no header)
3. Run: `python train_model.py`
4. New model saved as `rul_model.joblib`

---

## Testing

Run the demo to verify everything works:

```bash
python predict.py
```

Expected output:
```
Tick 0:   100.0% - Excellent
Tick 10:  98.6%  - Excellent  
Tick 20:  94.7%  - Excellent
Tick 30:  91.8%  - Excellent
Tick 40:  83.0%  - Excellent
Tick 49:  75.8%  - Good
```

Health score should decrease as sensors degrade!

---

## Next Steps

- [ ] Wire `predict_health()` into backend health check endpoint
- [ ] Use `trajectories.json` for mission planning
- [ ] Replace synthetic sensor generator with real drone telemetry
- [ ] Add alerting when health drops below thresholds
- [ ] Log predictions for model monitoring

---

## Questions?

Ask Rohit (@vrrroro) or check the inline code comments!
