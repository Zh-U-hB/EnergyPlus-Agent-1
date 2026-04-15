# Zone Class Tool Usage Guide

## create_zone Tool Usage Guide

This tool has the following required parameters:
1. **name**: The name of the zone
2. **floor_vertices**: A list of floor vertices for the zone. The points in this list must be arranged in counterclockwise order on the xy-plane.
3. **x_origin**: The x-coordinate of the zone's base point
4. **y_origin**: The y-coordinate of the zone's base point
5. **z_origin**: The z-coordinate of the zone's base point
6. **ceiling_height**: The ceiling height of the zone

### floor_vertices Parameter Specification

**CRITICAL: floor_vertices must be ABSOLUTE WORLD COORDINATES, not relative coordinates!**

The `floor_vertices` parameter defines the actual position of each zone's floor in the building's world coordinate system. Each zone must have its own unique floor_vertices based on its actual location in the building.

**Example: Creating multiple zones in a building**

Consider a building with two adjacent zones on the same floor (z=0):
- Zone1: located at x=0 to x=5, y=0 to y=4
- Zone2: located at x=5 to x=10, y=0 to y=4

```json
// Zone1 floor_vertices (absolute world coordinates)
[
  {"X": 0.0, "Y": 0.0, "Z": 0.0},
  {"X": 5.0, "Y": 0.0, "Z": 0.0},
  {"X": 5.0, "Y": 4.0, "Z": 0.0},
  {"X": 0.0, "Y": 4.0, "Z": 0.0}
]

// Zone2 floor_vertices (absolute world coordinates) - NOTE: starts at x=5, not x=0!
[
  {"X": 5.0, "Y": 0.0, "Z": 0.0},
  {"X": 10.0, "Y": 0.0, "Z": 0.0},
  {"X": 10.0, "Y": 4.0, "Z": 0.0},
  {"X": 5.0, "Y": 4.0, "Z": 0.0}
]
```

**For zones on different floors:**
- Floor1 zones: Z coordinate = 0
- Floor2 zones: Z coordinate = floor_height (e.g., 3.0)
- Floor3 zones: Z coordinate = 2 * floor_height (e.g., 6.0)

```json
// Zone1 on Floor2 (z_origin = 3.0)
[
  {"X": 0.0, "Y": 0.0, "Z": 3.0},
  {"X": 5.0, "Y": 0.0, "Z": 3.0},
  {"X": 5.0, "Y": 4.0, "Z": 3.0},
  {"X": 0.0, "Y": 4.0, "Z": 3.0}
]
```

### Relationship between floor_vertices and x_origin/y_origin/z_origin

**IMPORTANT:** The `floor_vertices` and `x_origin/y_origin/z_origin` are INDEPENDENT parameters:

1. **floor_vertices**: Used to create the actual surface geometry (walls, floor, ceiling). These must be absolute world coordinates.

2. **x_origin/y_origin/z_origin**: Metadata for the Zone object in EnergyPlus. Typically set to a reference point of the zone (e.g., the centroid or one corner).

**Example:** For a zone spanning from (5, 10, 0) to (10, 14, 0):
- floor_vertices: `[{"X": 5, "Y": 10, "Z": 0}, {"X": 10, "Y": 10, "Z": 0}, {"X": 10, "Y": 14, "Z": 0}, {"X": 5, "Y": 14, "Z": 0}]`
- x_origin: 7.5 (centroid x)
- y_origin: 12 (centroid y)
- z_origin: 0

**DO NOT** add x_origin/y_origin/z_origin to floor_vertices - the vertices should already be in absolute coordinates!

### How to determine floor_vertices

You must determine each zone's bottom surface vertices based on:
1. The building floor plan diagrams in your generated claude_ep.md file
2. The zone coordinates table in claude_ep.md that shows each zone's position

For example, if claude_ep.md shows:
```
| Zone | x (m) | y (m) | Floor Vertices (CCW) |
|------|-------|-------|---------------------|
| Z1   | 1.25  | 2     | [(0,0), (2.5,0), (2.5,4), (0,4)] |
| Z2   | 3.75  | 2     | [(2.5,0), (5,0), (5,4), (2.5,4)] |
```

Then for Zone1 (on Floor1, z=0):
```json
[
  {"X": 0.0, "Y": 0.0, "Z": 0.0},
  {"X": 2.5, "Y": 0.0, "Z": 0.0},
  {"X": 2.5, "Y": 4.0, "Z": 0.0},
  {"X": 0.0, "Y": 4.0, "Z": 0.0}
]
```

And for Zone2 (on Floor1, z=0):
```json
[
  {"X": 2.5, "Y": 0.0, "Z": 0.0},
  {"X": 5.0, "Y": 0.0, "Z": 0.0},
  {"X": 5.0, "Y": 4.0, "Z": 0.0},
  {"X": 2.5, "Y": 4.0, "Z": 0.0}
]
```

Notice that Zone2's vertices start at (2.5, 0, 0), NOT (0, 0, 0)!

### ceiling_height Parameter

This parameter represents the height of the zone. It serves as a supplement to the floor_vertices parameter to generate all surface instances corresponding to the zone.

### Instances Generated After Using create_zone Tool

Using the create_zone tool will generate a zone instance along with all surface instances associated with that zone (including floor and ceiling). Therefore, as long as this zone tool is used correctly, there is no need to separately use create_surface class tools later. However, you still need to use the create_fenestration_surface tool separately to generate corresponding building window instances based on the building images provided by the user.
