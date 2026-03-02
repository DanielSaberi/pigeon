"""SSD MobileDet inference on CPU using tflite-runtime.

Replaces PyCoral's run_inference() + detect.get_objects() for CPU benchmarking.
The CPU model (ssdlite_mobiledet_coco_qat_postprocess.tflite) includes
TFLite_Detection_PostProcess, so outputs are already post-processed:
  output[0]: boxes [1, N, 4] as (ymin, xmin, ymax, xmax) normalized [0,1]
  output[1]: class IDs [1, N]
  output[2]: scores [1, N]
  output[3]: detection count [1]
"""
import numpy as np
from pycoral.adapters.detect import BBox, Object


def ssd_detect(img_rgb, interpreter, threshold):
    """Run SSD detection on a resized RGB image.

    Args:
        img_rgb: RGB image already resized to model input size.
        interpreter: tflite Interpreter instance.
        threshold: minimum confidence score.

    Returns:
        List[Object] with id (0-indexed COCO 91-class), score, and bbox
        in pixel coordinates of the model input resolution.
    """
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_shape = input_details[0]['shape']  # [1, H, W, 3]
    height, width = input_shape[1], input_shape[2]

    img = np.expand_dims(img_rgb, axis=0)
    input_dtype = input_details[0]['dtype']
    if input_dtype == np.uint8:
        img = img.astype(np.uint8)
    else:
        img = img.astype(np.float32)

    interpreter.set_tensor(input_details[0]['index'], img)
    interpreter.invoke()

    boxes = interpreter.get_tensor(output_details[0]['index'])[0]     # [N, 4]
    classes = interpreter.get_tensor(output_details[1]['index'])[0]   # [N]
    scores = interpreter.get_tensor(output_details[2]['index'])[0]    # [N]
    count = int(interpreter.get_tensor(output_details[3]['index'])[0])

    objs = []
    for i in range(count):
        if scores[i] < threshold:
            continue
        ymin, xmin, ymax, xmax = boxes[i]
        bbox = BBox(
            xmin=xmin * width,
            ymin=ymin * height,
            xmax=xmax * width,
            ymax=ymax * height,
        )
        objs.append(Object(id=int(classes[i]), score=float(scores[i]), bbox=bbox))

    return objs
