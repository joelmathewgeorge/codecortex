# VisDrone2019-DET - Aerial Object Detection

Drone-captured images from many cities in China, annotated with bounding boxes across 10
classes: pedestrian, people, bicycle, car, van, truck, tricycle, awning-tricycle, bus,
and motor. This is the DET (detection) image subset, the standard benchmark for object
detection in aerial imagery. Objects are often small and dense, which makes it a real
test for detectors.

## What is in this folder
Three splits, each with an `images/` folder and an `annotations/` folder:
- `VisDrone2019-DET-train/` - 6,471 images
- `VisDrone2019-DET-val/` - 548 images
- `VisDrone2019-DET-test-dev/` - 1,610 images

Annotations are one txt file per image, each line a box:
`x,y,width,height,score,category,truncation,occlusion`.

License: research use. Check the terms before rebundling.
