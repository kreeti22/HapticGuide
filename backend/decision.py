def get_direction(bbox, image_width):
    """
    Divide the image into Left / Center / Right.
    """

    x1, _, x2, _ = bbox

    center_x = (x1 + x2) / 2

    if center_x < image_width / 3:
        return "left"

    elif center_x < 2 * image_width / 3:
        return "center"

    else:
        return "right"


def prioritize_objects(objects, image_width):
    """
    Adds direction and priority to each detected object.
    Larger depth = closer (Depth Anything relative depth).
    """

    enriched = []

    for obj in objects:

        direction = get_direction(obj["bbox"], image_width)

        enriched.append({
            **obj,
            "direction": direction
        })

    # Closest object first
    enriched.sort(
        key=lambda x: x["depth"] if x["depth"] is not None else float("-inf"),
        reverse=True
    )

    for i, obj in enumerate(enriched):
        obj["priority"] = i + 1

    return enriched

def generate_haptic_command(objects):
    command = {
        "left": 0,
        "center": 0,
        "right": 0
    }

    if not objects:
        return command

    closest = objects[0]  # Highest-priority object

    intensity = 255

    if closest["direction"] == "left":
        command["left"] = intensity

    elif closest["direction"] == "center":
        command["center"] = intensity

    elif closest["direction"] == "right":
        command["right"] = intensity

    return command