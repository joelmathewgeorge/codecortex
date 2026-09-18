"""
Train a Random Forest model to predict Remaining Useful Life (RUL).

SIMPLE EXPLANATION:
- Load the training data (drones getting old)
- Separate features (sensor readings) from target (RUL)
- Train a Random Forest to learn patterns
- Save the trained model for later use
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import joblib

print("="*60)
print("DRONE HEALTH PREDICTION MODEL - TRAINING")
print("="*60)

# Step 1: Load the data
print("\n[1/5] Loading training data...")
df = pd.read_csv('train_FD001.txt', sep=' ', header=None)

# Assign column names (no unit column - it was dropped during groupby)
# Columns: cycle, setting1-3, sensor1-21, RUL
columns = ['cycle', 'setting1', 'setting2', 'setting3'] + \
          [f'sensor{i}' for i in range(1, 22)] + ['RUL']
df.columns = columns

print(f"      Loaded {len(df)} samples")
print(f"      RUL range: {df['RUL'].min():.0f} to {df['RUL'].max():.0f} cycles")

# Step 2: Prepare features and target
print("\n[2/5] Preparing features (X) and target (y)...")
# Features: cycle + settings + all sensors
feature_cols = ['cycle', 'setting1', 'setting2', 'setting3'] + \
               [f'sensor{i}' for i in range(1, 22)]
X = df[feature_cols]
y = df['RUL']

print(f"      Features shape: {X.shape}")
print(f"      Target shape: {y.shape}")

# Split into train and test sets (80/20)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

print(f"      Training samples: {len(X_train)}")
print(f"      Test samples: {len(X_test)}")

# Step 3: Train the model
print("\n[3/5] Training Random Forest model...")
print("      (This might take 30-60 seconds...)")

model = RandomForestRegressor(
    n_estimators=100,  # 100 decision trees
    max_depth=20,      # How deep each tree can grow
    random_state=42,
    n_jobs=-1          # Use all CPU cores
)

model.fit(X_train, y_train)
print("      Training complete!")

# Step 4: Evaluate the model
print("\n[4/5] Evaluating model performance...")
y_pred_train = model.predict(X_train)
y_pred_test = model.predict(X_test)

train_mae = mean_absolute_error(y_train, y_pred_train)
test_mae = mean_absolute_error(y_test, y_pred_test)
train_r2 = r2_score(y_train, y_pred_train)
test_r2 = r2_score(y_test, y_pred_test)

print(f"\n      Training Set:")
print(f"         - Mean Absolute Error: {train_mae:.2f} cycles")
print(f"         - R² Score: {train_r2:.3f}")
print(f"\n      Test Set:")
print(f"         - Mean Absolute Error: {test_mae:.2f} cycles")
print(f"         - R² Score: {test_r2:.3f}")

# Step 5: Save the model
print("\n[5/5] Saving model to disk...")
joblib.dump(model, 'rul_model.joblib')
print("      Saved as: rul_model.joblib")

print("\n" + "="*60)
print("SUCCESS! Model trained and saved.")
print("="*60)
print("\nWhat this means:")
print(f"  - On average, predictions are off by {test_mae:.1f} cycles")
print(f"  - R² = {test_r2:.3f} means the model explains ~{test_r2*100:.0f}% of variance")
print("  - Higher R² (closer to 1.0) = better predictions")
print("\nNext: Use this model in predict.py to get health scores!")
