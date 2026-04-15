# Export IDF File Skill

## Overview

This skill provides instructions for exporting an EnergyPlus IDF file from the YAML configuration created through the MCP tools. The IDF file is required for running EnergyPlus simulations.

## Prerequisites

Before exporting the IDF file, ensure that:

1. The YAML configuration file has been created with all necessary components:
   - Building and Location objects
   - Zones with proper geometry
   - Materials and Constructions
   - Surfaces with correct boundary conditions
   - Schedules (if needed)
   - HVAC systems (if needed)
   - People and Lights (if needed)

2. The configuration has been validated using `validate_config` tool.

## Export Process

### Step 1: Export YAML Configuration

First, export the current MCP state to a YAML file:

```python
# Using MCP tool
mcp--EnergyPlus-Agent--export_yaml(output_path="path/to/output.yaml")
```

### Step 2: Convert YAML to IDF

Use the ConverterManager to convert the YAML file to IDF format:

```python
from pathlib import Path
from src.validator.data_model import BaseSchema
from src.converter_manager import ConverterManager

# Initialize IDF with IDD file
idd_file = Path('data/dependencies/Energy+.idd')
BaseSchema.set_idf(idd_file)

# Load YAML and convert
yaml_path = Path('path/to/output.yaml')
output_dir = Path('path/to/output')
output_dir.mkdir(parents=True, exist_ok=True)

manager = ConverterManager(yaml_path)
manager.convert_all()

# Save IDF file
idf_path = output_dir / 'output.idf'
manager.save_idf(idf_path)
```

### Step 3: Fix Common Issues

After conversion, some IDF objects may need manual fixes:

#### Fix RunPeriod None Values

```python
# Fix RunPeriod None values that cause conversion errors
rp = manager._idf.idfobjects['RUNPERIOD'][0]
rp.Day_of_Week_for_Start_Day = 'Sunday'
rp.Use_Weather_File_Holidays_and_Special_Days = 'Yes'
rp.Use_Weather_File_Daylight_Saving_Period = 'Yes'
rp.Apply_Weekend_Holiday_Rule = 'No'
rp.Use_Weather_File_Rain_Indicators = 'Yes'
rp.Use_Weather_File_Snow_Indicators = 'Yes'
rp.Begin_Year = 2024
rp.End_Year = 2024
```

#### Fix Building Minimum Warmup Days

```python
# Fix Building minimum_number_of_warmup_days (must be > 0)
bldg = manager._idf.idfobjects['BUILDING'][0]
bldg.Minimum_Number_of_Warmup_Days = 1
```

#### Fix Interzone Surfaces

For internal walls between zones, use Adiabatic boundary condition to avoid surface matching issues:

```python
for surf in manager._idf.idfobjects['BUILDINGSURFACE:DETAILED']:
    if surf.Outside_Boundary_Condition == 'Surface':
        surf.Outside_Boundary_Condition = 'Adiabatic'
        surf.Outside_Boundary_Condition_Object = ''
        surf.Sun_Exposure = 'NoSun'
        surf.Wind_Exposure = 'NoWind'
        surf.Construction_Name = 'Int_Wall'
```

#### Fix Schedule:Compact None Values

Schedule:Compact objects may have None values in unused fields that cause save errors:

```python
# Fix Schedule:Compact objects with None values
for sch in manager._idf.idfobjects['SCHEDULE:COMPACT']:
    for i in range(1, 100):
        field_name = f'Field_{i}'
        if hasattr(sch, field_name):
            val = getattr(sch, field_name)
            if val is None:
                try:
                    delattr(sch, field_name)
                except:
                    pass
```

### Step 4: Save the Fixed IDF

```python
manager.save_idf(idf_path)
print(f'IDF saved to: {idf_path}')
```

## Complete Export Script

Here's a complete script that handles all the fixes:

```python
from pathlib import Path
from src.validator.data_model import BaseSchema
from src.converter_manager import ConverterManager

def export_idf(yaml_path: str, output_dir: str, idf_name: str = 'output.idf') -> Path:
    """
    Export YAML configuration to IDF file with automatic fixes.
    
    Args:
        yaml_path: Path to the YAML configuration file
        output_dir: Directory for output files
        idf_name: Name of the output IDF file
        
    Returns:
        Path to the saved IDF file
    """
    # Initialize IDF with IDD file
    idd_file = Path('data/dependencies/Energy+.idd')
    BaseSchema.set_idf(idd_file)
    
    # Setup paths
    yaml_path = Path(yaml_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Convert YAML to IDF
    manager = ConverterManager(yaml_path)
    manager.convert_all()
    
    # Fix RunPeriod None values
    rp = manager._idf.idfobjects['RUNPERIOD'][0]
    rp.Day_of_Week_for_Start_Day = 'Sunday'
    rp.Use_Weather_File_Holidays_and_Special_Days = 'Yes'
    rp.Use_Weather_File_Daylight_Saving_Period = 'Yes'
    rp.Apply_Weekend_Holiday_Rule = 'No'
    rp.Use_Weather_File_Rain_Indicators = 'Yes'
    rp.Use_Weather_File_Snow_Indicators = 'Yes'
    rp.Begin_Year = 2024
    rp.End_Year = 2024
    
    # Fix Building minimum_number_of_warmup_days
    bldg = manager._idf.idfobjects['BUILDING'][0]
    bldg.Minimum_Number_of_Warmup_Days = 1
    
    # Fix interzone surfaces
    for surf in manager._idf.idfobjects['BUILDINGSURFACE:DETAILED']:
        if surf.Outside_Boundary_Condition == 'Surface':
            surf.Outside_Boundary_Condition = 'Adiabatic'
            surf.Outside_Boundary_Condition_Object = ''
            surf.Sun_Exposure = 'NoSun'
            surf.Wind_Exposure = 'NoWind'
            surf.Construction_Name = 'Int_Wall'
    
    # Fix Schedule:Compact objects with None values
    for sch in manager._idf.idfobjects['SCHEDULE:COMPACT']:
        for i in range(1, 100):
            field_name = f'Field_{i}'
            if hasattr(sch, field_name):
                val = getattr(sch, field_name)
                if val is None:
                    try:
                        delattr(sch, field_name)
                    except:
                        pass
    
    # Save IDF
    idf_path = output_dir / idf_name
    manager.save_idf(idf_path)
    
    return idf_path

# Usage example
if __name__ == '__main__':
    idf_path = export_idf(
        yaml_path='test/test_data/SmallOffice/smalloffice_1/smalloffice_1.yaml',
        output_dir='test/test_data/SmallOffice/smalloffice_1/output',
        idf_name='smalloffice_1.idf'
    )
    print(f'IDF saved to: {idf_path}')
```

## Quick Command Line Export

For quick export from command line, use the following one-liner:

```bash
cd /root/EPA/EnergyPlus-Agent/EnergyPlus-Agent && uv run python -c "
import sys
sys.path.insert(0, '/root/EPA/EnergyPlus-Agent/EnergyPlus-Agent')

from pathlib import Path
from src.validator.data_model import BaseSchema
from src.converter_manager import ConverterManager

# Initialize IDF with IDD file
idd_file = Path('data/dependencies/Energy+.idd')
BaseSchema.set_idf(idd_file)

# Load YAML and convert
yaml_path = Path('test/test_data/SmallOffice/smalloffice_1/smalloffice_1.yaml')
output_dir = Path('test/test_data/SmallOffice/smalloffice_1/output')
output_dir.mkdir(parents=True, exist_ok=True)

manager = ConverterManager(yaml_path)
manager.convert_all()

# Fix RunPeriod None values
rp = manager._idf.idfobjects['RUNPERIOD'][0]
rp.Day_of_Week_for_Start_Day = 'Sunday'
rp.Use_Weather_File_Holidays_and_Special_Days = 'Yes'
rp.Use_Weather_File_Daylight_Saving_Period = 'Yes'
rp.Apply_Weekend_Holiday_Rule = 'No'
rp.Use_Weather_File_Rain_Indicators = 'Yes'
rp.Use_Weather_File_Snow_Indicators = 'Yes'
rp.Begin_Year = 2024
rp.End_Year = 2024

# Fix Building minimum_number_of_warmup_days
bldg = manager._idf.idfobjects['BUILDING'][0]
bldg.Minimum_Number_of_Warmup_Days = 1

# Fix Interzone Surfaces
for surf in manager._idf.idfobjects['BUILDINGSURFACE:DETAILED']:
    if surf.Outside_Boundary_Condition == 'Surface':
        surf.Outside_Boundary_Condition = 'Adiabatic'
        surf.Outside_Boundary_Condition_Object = ''
        surf.Sun_Exposure = 'NoSun'
        surf.Wind_Exposure = 'NoWind'
        surf.Construction_Name = 'Int_Wall'

# Fix Schedule:Compact objects with None values
for sch in manager._idf.idfobjects['SCHEDULE:COMPACT']:
    for i in range(1, 100):
        field_name = f'Field_{i}'
        if hasattr(sch, field_name):
            val = getattr(sch, field_name)
            if val is None:
                try:
                    delattr(sch, field_name)
                except:
                    pass

# Save IDF file
idf_path = output_dir / 'smalloffice_1.idf'
manager.save_idf(idf_path)
print(f'IDF file saved to: {idf_path}')
"
```

## Running the Simulation

After exporting the IDF file, run the EnergyPlus simulation:

```bash
energyplus -w data/weather/Shenzhen.epw -d output_dir -r output.idf
```

## Common Errors and Solutions

### Error: "minimum_number_of_warmup_days must be greater than 0"

**Solution:** Set `Minimum_Number_of_Warmup_Days` to at least 1.

### Error: "InterZone Surface Areas do not match"

**Solution:** Use Adiabatic boundary condition for internal walls instead of Surface-to-Surface matching.

### Error: "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"

**Solution:** Ensure all required fields in RunPeriod are set to non-None values.

### Error: "No Timestep object found"

**Solution:** The simulation will default to 4 timesteps per hour, but you can add a Timestep object for better control.

## Notes

1. The `BaseSchema.set_idf()` must be called before using ConverterManager to initialize the IDF with the EnergyPlus IDD file.

2. The IDD file path is typically `data/dependencies/Energy+.idd`.

3. Always validate the configuration before exporting to catch reference errors.

4. The interzone surface matching requires exact geometric correspondence between adjacent surfaces. For simplicity, use Adiabatic boundary conditions for internal walls.
