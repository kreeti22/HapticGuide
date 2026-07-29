def get_direction(bbox, image_width):
    x1, _, x2, _ = bbox

    center_x = (x1 + x2) / 2

    if center_x < image_width / 3:
        return "left"

    elif center_x < 2 * image_width / 3:
        return "center"

    else:
        return "right"