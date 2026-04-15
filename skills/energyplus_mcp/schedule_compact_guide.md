# ScheduleCompact Tool Usage Guide

## Overview

The ScheduleCompact tool is used to create and update compact schedules (Schedule:Compact) in EnergyPlus. Schedules define time-varying values used to control building systems such as thermostats, people, lighting, and more.

## Data Structure

The `times` parameter for ScheduleCompact must follow a specific nested structure:

```
times = [
    {
        "Through": "date",           // Date range end point, format: MM/DD or YYYY-MM-DD
        "Days": [                    // Day definitions within this date range
            {
                "For": "day_type",    // See valid values below
                "Times": [            // Time point definitions
                    {
                        "Until": {
                            "Time": "time",    // Format: HH:MM
                            "Value": number    // Corresponding value
                        }
                    }
                ]
            }
        ]
    }
]
```

## Valid Parameter Values

### Date (Through)
- Format: `MM/DD` (e.g., `12/31`) or `YYYY-MM-DD` (e.g., `2024-12-31`)
- **Important**: The last date range MUST be `12/31` (end of year)

### Day Type (For)
Valid values (case-insensitive):
- `AllDays` - All days
- `Weekdays` - Weekdays (Monday to Friday)
- `Weekends` - Weekends (Saturday, Sunday)
- `Holidays` - Holidays
- `Sunday`, `Monday`, `Tuesday`, `Wednesday`, `Thursday`, `Friday`, `Saturday` - Specific day
- `SummerDesignDay` - Summer design day
- `WinterDesignDay` - Winter design day
- `CustomDay1`, `CustomDay2` - Custom days
- `AllOtherDays` - All other days

### Time (Time)
- Format: `HH:MM` (24-hour format)
- **Important**: The time sequence for each day type MUST end with `24:00`

## Usage Examples

### Example 1: Constant Value All Day

```python
# Create a schedule with constant value 1.0 all year round
times = [
    {
        "Through": "12/31",
        "Days": [
            {
                "For": "AllDays",
                "Times": [
                    {
                        "Until": {
                            "Time": "24:00",
                            "Value": 1.0
                        }
                    }
                ]
            }
        ]
    }
]
```

### Example 2: Working Hours Schedule

```python
# Working days 8:00-18:00 is 1.0, other times is 0.0
times = [
    {
        "Through": "12/31",
        "Days": [
            {
                "For": "Weekdays",
                "Times": [
                    {
                        "Until": {"Time": "08:00", "Value": 0.0}
                    },
                    {
                        "Until": {"Time": "18:00", "Value": 1.0}
                    },
                    {
                        "Until": {"Time": "24:00", "Value": 0.0}
                    }
                ]
            },
            {
                "For": "Weekends",
                "Times": [
                    {
                        "Until": {"Time": "24:00", "Value": 0.0}
                    }
                ]
            }
        ]
    }
]
```

### Example 3: Multi-Period Variation

```python
# Full day divided into multiple periods with different values
times = [
    {
        "Through": "12/31",
        "Days": [
            {
                "For": "AllDays",
                "Times": [
                    {
                        "Until": {"Time": "06:00", "Value": 0.2}
                    },
                    {
                        "Until": {"Time": "09:00", "Value": 0.8}
                    },
                    {
                        "Until": {"Time": "12:00", "Value": 1.0}
                    },
                    {
                        "Until": {"Time": "14:00", "Value": 0.9}
                    },
                    {
                        "Until": {"Time": "18:00", "Value": 1.0}
                    },
                    {
                        "Until": {"Time": "22:00", "Value": 0.6}
                    },
                    {
                        "Until": {"Time": "24:00", "Value": 0.2}
                    }
                ]
            }
        ]
    }
]
```

### Example 4: Seasonal Variation

```python
# Different schedules for different seasons
times = [
    {
        "Through": "03/31",  # First quarter
        "Days": [
            {
                "For": "AllDays",
                "Times": [
                    {"Until": {"Time": "24:00", "Value": 0.8}}
                ]
            }
        ]
    },
    {
        "Through": "06/30",  # Second quarter
        "Days": [
            {
                "For": "AllDays",
                "Times": [
                    {"Until": {"Time": "24:00", "Value": 1.0}}
                ]
            }
        ]
    },
    {
        "Through": "09/30",  # Third quarter
        "Days": [
            {
                "For": "AllDays",
                "Times": [
                    {"Until": {"Time": "24:00", "Value": 1.0}}
                ]
            }
        ]
    },
    {
        "Through": "12/31",  # Fourth quarter (must end with 12/31)
        "Days": [
            {
                "For": "AllDays",
                "Times": [
                    {"Until": {"Time": "24:00", "Value": 0.7}}
                ]
            }
        ]
    }
]
```

## Tool Call Examples

### Create ScheduleCompact

```python
create_schedule_compact(
    name="AlwaysOnSchedule",
    schedule_type_limits_name="FractionLimits",
    times=[
        {
            "Through": "12/31",
            "Days": [
                {
                    "For": "AllDays",
                    "Times": [
                        {"Until": {"Time": "24:00", "Value": 1.0}}
                    ]
                }
            ]
        }
    ]
)
```

### Update ScheduleCompact

```python
update_schedule_compact(
    name="AlwaysOnSchedule",
    schedule_type_limits_name="FractionLimits",
    times=[
        {
            "Through": "12/31",
            "Days": [
                {
                    "For": "AllDays",
                    "Times": [
                        {"Until": {"Time": "24:00", "Value": 0.5}}
                    ]
                }
            ]
        }
    ]
)
```

## Common Errors

### Error 1: Incorrect Date Format
```python
# Wrong
"Through": "31/12"  # Should be MM/DD

# Correct
"Through": "12/31"
```

### Error 2: Last Date is Not 12/31
```python
# Wrong - will throw exception
times = [
    {"Through": "06/30", ...},
    {"Through": "12/30", ...}  # Must be 12/31
]
```

### Error 3: Time Sequence Doesn't End with 24:00
```python
# Wrong - will throw exception
"Times": [
    {"Until": {"Time": "18:00", "Value": 1.0}}
    # Missing 24:00 end point
]
```

### Error 4: Invalid Day Type
```python
# Wrong
"For": "EveryDay"  # Not a valid day type

# Correct
"For": "AllDays"
```

## Important Notes

1. **ScheduleTypeLimits Must Exist First**: ScheduleCompact needs to reference an existing ScheduleTypeLimits
2. **Times Must Be Continuous**: Time points must be in chronological order and cannot overlap
3. **Values Must Be Within Range**: Values must be within the range defined by ScheduleTypeLimits
4. **Dates Must Be Continuous**: Multiple date ranges must be continuous and cover the entire year
5. **Last Date Must Be 12/31**: This is an EnergyPlus requirement

## Related Tools

- `create_schedule_type_limits` - Create schedule type limits
- `list_schedule_type_limits` - List existing schedule type limits
- `list_schedule_compacts` - List existing schedules
