"""Image checks for the fixed equipment fixture, never candidate quality scores."""
from pathlib import Path
import numpy as np
from PIL import Image

def inspect_equipment(outdoor: Path, interior: Path):
    outside=np.asarray(Image.open(outdoor).convert('RGB'),dtype=float)/255
    inside=np.asarray(Image.open(interior).convert('RGB'),dtype=float)/255
    if min(outside.shape[:2])<360 or min(inside.shape[:2])<360:
        raise ValueError('Equipment evidence is too small')
    # The fixed fixture places no geometry in this top border. It must show daylight sky.
    sky=outside[:max(1,outside.shape[0]//20),:,:]
    sky_luma=sky @ np.array([.2126,.7152,.0722])
    indoor_luma=inside @ np.array([.2126,.7152,.0722])
    values={'sky_median_luminance':float(np.median(sky_luma)),
            'sky_near_black_fraction':float(np.mean(sky_luma<.02)),
            'interior_median_luminance':float(np.median(indoor_luma)),
            'interior_contrast_std':float(np.std(indoor_luma)),
            'interior_clipped_white_fraction':float(np.mean(np.min(inside,axis=2)>.98))}
    checks={'sky_visible':values['sky_median_luminance']>.08 and values['sky_near_black_fraction']<.01,
            'interior_readable':values['interior_median_luminance']>.035 and values['interior_contrast_std']>.02,
            'interior_not_clipped':values['interior_clipped_white_fraction']<.1}
    return {'passed':all(checks.values()),'checks':checks,'measurements':values,
            'scope':'Only the fixed daylight/material equipment fixture. Not a metric or threshold for generated scenes.'}
