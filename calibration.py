def calibrate_value(measured_points, actual_points, current_measured):
    if not (measured_points and actual_points and len(measured_points) == len(actual_points)):
        return None  # Handle invalid input

    # Find the closest calibration points
    lower_index = -1
    upper_index = -1

    for i in range(len(measured_points)):
        if measured_points[i] <= current_measured:
            if lower_index == -1 or measured_points[i] > measured_points[lower_index]:
                lower_index = i
        if measured_points[i] >= current_measured:
            if upper_index == -1 or measured_points[i] < measured_points[upper_index]:
                upper_index = i

    if lower_index == -1 and upper_index == -1:  # current_measured is outside the calibration range.
        return None

    # Handle edge cases: current_measured is equal to a calibration point
    if lower_index != -1 and measured_points[lower_index] == current_measured:
        return actual_points[lower_index]
    if upper_index != -1 and measured_points[upper_index] == current_measured:
        return actual_points[upper_index]

    # Linear interpolation
    if lower_index != -1 and upper_index != -1:  # Regular interpolation
        x1 = measured_points[lower_index]
        y1 = actual_points[lower_index]
        x2 = measured_points[upper_index]
        y2 = actual_points[upper_index]
        x = current_measured

        calibrated_value = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        return calibrated_value

    elif lower_index != -1: # current_measured is above highest measured calibration point
        x1 = measured_points[lower_index]
        y1 = actual_points[lower_index]
        x = current_measured
        # extrapolate beyond the calibration points
        calibrated_value = y1 + (x - x1)
        return calibrated_value
    elif upper_index != -1: # current_measured is below lowest measured calibration point
        x2 = measured_points[upper_index]
        y2 = actual_points[upper_index]
        x = current_measured
        # extrapolate beyond the calibration points
        calibrated_value = y2 - (x2 - x)
        return calibrated_value