# Progress Tracking - Quick Test Guide

## Pre-Testing Setup

### 1. Create Test Resources
Create at least 2-3 resources with progress tracking:
```
Resource 1: "Mathematics Progress"
Resource 2: "Science Progress"  
Resource 3: "English Progress"
```

### 2. Set PACE Dates
For each resource, add to the Notes field:
```html
<p>start_date: 1/Jan/2025</p>
<p>end_date: 31/Dec/2025</p>
```

### 3. Assign Subjects
Link each progress resource to the appropriate subject:
- Mathematics Progress → Mathematics subject
- Science Progress → Science subject
- English Progress → English subject

### 4. Verify Subject Categories
Ensure subjects have categories with colors set:
1. Go to Subject Categories
2. Verify each category has a color index (0-11)
3. Ensure subjects are assigned to categories

### 5. Create Test Data
For a test student:
- Assign all 3 progress resources
- Create submissions with varying scores:
  - Week 1: Math 60%, Science 70%, English 55%
  - Week 2: Math 65%, Science 75%, English 60%
  - Week 3: Math 70%, Science 80%, English 65%

## Testing Steps

### Test 1: Basic Display
1. Navigate to Dashboard
2. Select period: "Last 30 Days"
3. Select the test student from dropdown
4. **Verify:** Progress row appears above existing graphs
5. **Verify:** Two charts are visible (line and bar)
6. **Verify:** Loading spinners appear briefly then disappear

### Test 2: Line Chart
1. **Verify:** Line chart shows 3 colored lines (one per subject)
2. **Verify:** Each line has multiple data points
3. **Verify:** Gray dashed PACE lines are visible for each subject
4. **Verify:** Colors are different for each subject
5. **Verify:** Legend at bottom shows subject names
6. **Verify:** Y-axis shows 0-100%
7. **Verify:** X-axis shows date labels

### Test 3: Bar Chart
1. **Verify:** Bar chart shows 3 horizontal bars
2. **Verify:** Each bar represents a subject
3. **Verify:** Bar colors match line chart colors
4. **Verify:** Percentages are visible
5. **Verify:** X-axis shows 0-100%
6. **Verify:** Bars extend to correct percentage

### Test 4: Interactive Features
1. Click on "Mathematics" in line chart legend
2. **Verify:** Only Mathematics line remains visible
3. **Verify:** Other lines disappear
4. Click on "Mathematics" again
5. **Verify:** All lines reappear
6. Try clicking on PACE line legend entry
7. **Verify:** Nothing happens (PACE lines stay visible)

### Test 5: PACE Calculation
1. **Verify:** PACE line starts above 0% (unless today is start date)
2. **Verify:** PACE line ends at current date
3. Mouse over PACE line
4. **Verify:** Tooltip shows "Subject PACE: XX.X%"
5. Calculate expected PACE manually:
   - Days elapsed / Total days × 100
6. **Verify:** PACE value matches calculation

### Test 6: Data Updates
1. Create new submission for Math with 80% result
2. Refresh dashboard
3. **Verify:** Line chart shows new data point
4. **Verify:** Bar chart updates to 80%
5. **Verify:** Colors remain consistent

### Test 7: No Data Scenarios
1. Select student with no progress submissions
2. **Verify:** "No progress data available" message appears
3. Select "All Students" (if multiple students)
4. **Verify:** "Select a student to view progress" message appears
5. Select student, then period with no data
6. **Verify:** Appropriate message appears

### Test 8: Period Changes
1. Select "Last 7 Days"
2. **Verify:** Charts update with only recent data
3. Select "Last 90 Days"
4. **Verify:** Charts show more historical data
5. **Verify:** PACE lines adjust to period

### Test 9: Multiple Subjects
1. For one submission, assign multiple subjects
2. Refresh dashboard
3. **Verify:** Progress appears for all assigned subjects
4. **Verify:** Same submission counted for each subject

### Test 9b: Multi-Subject PACE
1. Create or edit a progress resource
2. Assign multiple subjects to it (e.g., Biology, Chemistry, Physics for "Combined Sciences Progress")
3. Add PACE dates to the resource notes
4. Assign to student and record progress
5. View dashboard
6. **Verify:** PACE line appears for all subjects linked to that resource
7. **Verify:** PACE dates are identical for all subjects from that resource
8. **Verify:** Each subject can have different actual progress despite sharing the same PACE timeline

### Test 10: Edge Cases
1. Create submission with 0% result
2. **Verify:** Not displayed on chart (or shown as 0)
3. Create submission with 100% result
4. **Verify:** Displayed correctly at top of chart
5. Create resource without " Progress" in name
6. **Verify:** Not included in progress tracking

## Common Issues and Solutions

### Issue: No Charts Appear
**Check:**
- Is a student selected?
- Does student have progress submissions?
- Are resource names correct (contain " Progress")?
- Are submissions in date range?

### Issue: PACE Lines Missing
**Check:**
- Are dates in notes field?
- Is format correct: day/month/year?
- Are both start_date and end_date present?
- Are dates valid?

### Issue: Wrong Colors
**Check:**
- Do subjects have categories?
- Do categories have colors set?
- Clear browser cache

### Issue: Charts Not Updating
**Check:**
- Refresh dashboard
- Check browser console for errors
- Verify submissions have result_percent calculated

## Performance Testing

### Test with Volume
1. Create 10+ progress resources
2. Add 50+ submissions for a student
3. Navigate to dashboard
4. **Verify:** Page loads within 3 seconds
5. **Verify:** Charts render smoothly
6. **Verify:** Interactions remain responsive

### Test with Multiple Students
1. Create progress data for 20+ students
2. Switch between students rapidly
3. **Verify:** No lag or freezing
4. **Verify:** Data updates correctly each time

## Browser Compatibility

Test in each browser:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Edge (latest)
- [ ] Safari (if available)

For each browser, verify:
- Charts render correctly
- Colors display properly
- Interactions work
- Tooltips appear
- No console errors

## Sign-Off

- [ ] All tests passed
- [ ] No console errors
- [ ] Performance acceptable
- [ ] Documentation reviewed
- [ ] Ready for production

**Tested By:** _______________
**Date:** _______________
**Notes:** _______________
