# Dubai Aerial Semantic Segmentation

Aerial imagery of Dubai captured by MBRSC satellites and annotated pixel by pixel into
6 land-use classes. Published as open access by Humans in the Loop with the Mohammed Bin
Rashid Space Center. It is a small, clean dataset for semantic segmentation of aerial
scenes.

## What is in this folder
- `images/` - 72 aerial tiles as PNG (tile_000 to tile_071)
- `masks/` - the matching segmentation masks, same filenames
- `data/` - the original Hugging Face parquet the PNGs were unpacked from
- `classes.json` - the 6 classes and their colors: Water, Land (unpaved), Road,
  Building, Vegetation, Unlabeled

72 images total, roughly 800x650 px each.

License: CC0 (public domain), free to use and redistribute.
