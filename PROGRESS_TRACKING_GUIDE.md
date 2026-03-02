# Student Progress Tracking System

## Overview
The progress tracking system allows you to monitor student progress across different subjects using standardized resource records. Progress is displayed on the dashboard with interactive charts showing historical trends and current status.

## Setup Instructions

### 1. Create Progress Resources

For each subject you want to track, create a resource record in `aps.resources` with:
- **Name format**: `[Subject Name] Progress` (e.g., "Mathematics Progress", "Science Progress")
  - The word " Progress" (with space) must be in the name
  - This is how the system identifies progress tracking resources

### 2. Configure PACE Tracking (Optional)

To show PACE lines on the progress graphs, add the following to the resource's **Notes** field:

```
start_date: 1/Aug/2025
end_date: 31/Dec/2027
```

**Important:** Since a resource can be assigned to multiple subjects (via the `subjects` Many2many field), the PACE dates you enter in the resource's notes will apply to **ALL subjects** associated with that resource.

**Format Requirements:**
- Use format: `day/month/year`
- Month can be abbreviated (Aug, Jan, Dec) or full name (August, January, December)
- Each entry should be on its own line
- Both dates are optional, but at least one is needed for PACE calculation

**Example Notes:**
```html
<p>This tracks student progress throughout the academic year.</p>
<p>start_date: 1/August/2025</p>
<p>end_date: 31/December/2027</p>
<p>Students should aim to complete 100% by the end date.</p>
<p>Note: These dates apply to all subjects linked to this resource.</p>
```

**Multi-Subject Resources:**
If you assign multiple subjects to one progress resource (e.g., "Combined Sciences Progress" linked to Biology, Chemistry, and Physics), the same PACE dates will be used for all three subjects. This is useful when subjects share the same timeline.

### 3. Assign Progress Resources to Students

Assign the progress resources to students as you would with any other resource:
1. Use the standard assignment workflow
2. Set appropriate due dates
3. Students submit their work or teachers record progress

### 4. Record Progress Results

When marking submissions:
1. Enter the **Score** (points earned)
2. Enter the **Out of Marks** (total possible points)
3. The system automatically calculates **Result %**
4. This percentage is used for progress tracking on the dashboard

## Dashboard Features

### Progress Charts Location
The progress tracking charts appear in a new row above the existing dashboard graphs, only visible when a student is selected.

### Chart 1: Progress Over Time (Line Graph)
**Features:**
- Shows progress trends for each subject over the selected period
- Each subject has its own colored line (color from subject category)
- PACE line (gray, dashed) shows expected progress based on start/end dates
- **Interactive:** Click on a subject in the legend to isolate it; click again to show all

**Data Points:**
- Starts from the period start date OR from the first prior entry if available
- Updates each time a progress submission is recorded
- Only shows subjects with progress records in the period

### Chart 2: Current Progress (Bar Graph)
**Features:**
- Horizontal bar chart showing latest progress for each subject
- One bar per subject
- Colors match the subject categories (consistent across both charts)
- Shows current progress percentage (0-100%)

**Display:**
- Shows the most recent progress result for each subject
- Useful for quick overview of where student stands across all subjects

## Color Coding

Subject colors are determined by the **Subject Category** (`aps.subject.category`):
- Each category has a color index (0-11)
- Colors are consistent across all charts
- If no category is assigned, uses default color

To set subject colors:
1. Navigate to the Subject Category settings
2. Set the color index for each category
3. Assign subjects to appropriate categories

## PACE Line Calculation

The PACE line shows expected progress on a pro-rata basis:

**Formula:**
```
Expected Progress % = (Days Elapsed / Total Days) × 100
```

**Example:**
- Start Date: January 1, 2025
- End Date: December 31, 2025 (365 days total)
- Current Date: July 1, 2025 (181 days elapsed)
- Expected Progress: (181/365) × 100 = 49.6%

**Display Rules:**
- Only shown if both start_date and end_date are found in notes
- Appears as a gray dashed line
- Updates dynamically based on current date
- Helps identify if student is ahead or behind schedule

## Usage Tips

### For Teachers
1. **Regular Updates:** Record progress submissions regularly for accurate tracking
2. **Consistent Naming:** Always include " Progress" in resource names
3. **Set PACE Dates:** Add start/end dates to help students understand expectations
4. **Use Categories:** Assign subjects to categories for consistent color coding

### For Students
1. **Monitor Progress:** Check dashboard regularly to see trends
2. **Compare to PACE:** Use PACE line to know if you're on track
3. **Focus Areas:** Use bar chart to identify subjects needing attention
4. **Click to Isolate:** Click subject names to focus on specific subjects

## Troubleshooting

### No Progress Data Shows
- Verify resource names contain " Progress" (with space before)
- Ensure submissions have non-zero result_percent values
- Check that student is selected in dropdown
- Verify date range includes submission dates

### PACE Line Not Showing
- Check that notes field contains start_date and end_date
- Verify date format: day/month/year (e.g., 15/Jan/2025)
- Ensure dates are valid and start_date is before end_date

### Colors Not Consistent
- Verify subjects are assigned to categories
- Check that categories have color indices set
- Refresh dashboard after category changes

## Technical Details

### Database Structure
- **Resources:** `aps.resources` with " Progress" in name
- **Submissions:** `aps.resource.submission` with result_percent field
- **Subjects:** Linked via Many2many relationship
- **Categories:** `aps.subject.category` with color field

### API Methods
- `get_pace_dates()`: Parse PACE dates from resource notes
- `get_progress_data_for_dashboard()`: Fetch progress data for charts
- `get_subject_colors_map()`: Get color mapping for subjects

### Chart Libraries
- Uses Chart.js for rendering
- Line chart with time scale for progress over time
- Horizontal bar chart for current progress
- Interactive legend with click-to-filter functionality

## Future Enhancements

Potential improvements to consider:
- Export progress reports to PDF
- Email notifications when falling behind PACE
- Progress milestones and celebrations
- Comparative analytics across students
- Predictive completion date based on current pace

---

**Last Updated:** March 2, 2026
**Module:** aps_sis
**Version:** 1.0
