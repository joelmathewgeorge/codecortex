# AU-AIR - Multimodal UAV Dataset

Drone footage recorded in low-altitude traffic scenes, with each frame annotated for
objects (cars, trucks, people, and so on) and paired with the drone's own flight sensors
at that moment: GPS, altitude, IMU, and velocity. The multimodal part is the point,
vision and flight state are synced together, which makes it useful for sensor fusion.

## What is in this folder
- `images/` - 32,823 extracted video frames
- `annotations.json` - object bounding boxes plus the flight sensor values per frame

License: non-commercial research use. Link to it rather than rebundling broadly.
