"""Reference-only subject contours and dynamic exclusion regions on fixed grids."""
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon


def raster_polygons(size, polygons):
    width, height = size
    if type(width) is not int or type(height) is not int or min(size) < 2:
        raise ValueError('Original integer image dimensions required')
    image = Image.new('1', (width, height), 0); draw = ImageDraw.Draw(image)
    for row in polygons:
        if not row.get('label'): raise ValueError('Reviewed semantic label required')
        points = np.asarray(row['points_px'], float)
        if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
                or not np.isfinite(points).all() or np.any(points < 0)
                or np.any(points > np.array(size)-1)):
            raise ValueError('Reviewed contour must use original pixel coordinates inside the image')
        shape = Polygon(points)
        if not shape.is_valid or shape.area <= 0:
            raise ValueError('Reviewed contour is self-intersecting or degenerate')
        draw.polygon([tuple(p) for p in points], fill=1)
    return np.asarray(image, dtype=bool)


def reference_masks(rgb, review):
    pixels = np.asarray(rgb)
    if pixels.ndim != 3 or pixels.shape[2] != 3 or pixels.dtype != np.uint8:
        raise ValueError('Original RGB8 reference required')
    size = [pixels.shape[1], pixels.shape[0]]
    if size != review['size'] or review['coordinate_space'] != 'original_pixels':
        raise ValueError('Reviewed image grid differs; resizing is prohibited')
    subjects = review['subjects']; ids = [s['id'] for s in subjects]
    if not ids or len(ids) != len(set(ids)): raise ValueError('Distinct fixed subject population required')
    foreground = np.zeros(pixels.shape[:2], bool)
    for subject in subjects:
        own = raster_polygons(size, subject['contours']) & ~raster_polygons(size, subject.get('holes', []))
        if not own.any(): raise ValueError('Annotated reference subject has no visible pixels')
        foreground |= own
    # Exclusions are removed from both sides of the comparison. They do not
    # turn occluded reference objects into candidate false positives.
    evaluation = ~raster_polygons(size, review.get('dynamic_exclusions', []))
    if not (foreground & evaluation).any() or np.all(foreground[evaluation]):
        raise ValueError('Visible subjects and surrounding negative area are both required')
    return foreground, evaluation
