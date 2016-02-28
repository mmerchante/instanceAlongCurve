Changelog
====================

### Current Version: 1.1.0

### 1.1.0

#### New Features
* Added rotation manipulators, with options to reset both positions and angles
* Added translate, rotate and scale offsets, both local and global
* Instantiates objects based on their pivots
* Added curve start and end values
* Added a ramp repeat value
* Added UI annotations

#### Changes
* Reworked core logic, orientation axis easier to handle/understand
* Objects now preserve their initial rotation and pivots

#### Fixes
* Copy input transform now updating correctly
* Distance mode now respects distance
* Various other performance issues, edge cases, etc.

### 1.0.3

- Added distance offset, contributed by MirageYM
- Fixed normalization of ramps axes

Compatibility issues: ramp amplitudes may need to be adjusted.

### 1.0.2

- Fixed plugin not working with curves created with the EP curve tool

### 1.0.1

- Rotation ramp now uses degrees, not radians
- Fixed random being dependent on the ramp amplitude; now it is not
- Fixed scale and position ramp incorrectly normalizing axis vector
