# NASA C-MAPSS - Turbofan Engine Degradation

Simulated run-to-failure data for aircraft turbofan engines. Each engine is tracked
cycle by cycle with 21 sensor readings and 3 operating settings, starting healthy and
running until it fails. It is the classic dataset for predictive maintenance and
Remaining Useful Life (RUL) estimation.

## What is in this folder
`CMAPSSData/` holds four subsets (FD001 to FD004) that differ in operating conditions
and fault modes:
- `train_FD00X.txt` - engines run all the way to failure
- `test_FD00X.txt` - engines cut off before failure
- `RUL_FD00X.txt` - the true remaining cycles for each test engine
- `readme.txt` and the Damage Propagation Modeling PDF - original documentation

Data is plain text, space separated, one row per engine per cycle.

License: U.S. Government work, free to use and redistribute.
