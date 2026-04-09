from pathlib import Path
from src.core.io.load_file import read_file_generic

example_txt_map = Path(r"C:/Users/apinilla/OneDrive - ICFO/Documents/Raman/251016 PH/Time resolved data good/XY mapping/Data to plot/Mount from anode side_insitu_test_50%laser_785nm_acc15s_exps_1s_-1mA_repeat.txt")
example_wdf_map = Path(r"C:\Users\apinilla\OneDrive - ICFO\Documents\Raman\240508 pH2 SO4 CA alt\CuAq_785nm_0d05p_2s_25aqq_-0d05VRHE_map_back_z2-3.wdf")
example_wdf_tr = Path(r"C:\Users\apinilla\OneDrive - ICFO\Documents\Raman\230623 pH 2\Cu_Aq_0d01p_2s_25aqq_1800g_-0d8V_s.wdf")

result = read_file_generic(example_wdf_tr)
print(len(result))

from renishawWiRE import WDFReader
import matplotlib.pyplot as plt
import numpy as np
import io
from PIL import Image

def _try_getattr(obj: object, name: str):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def plot_wdf_preview(filename: Path) -> None:
    reader = WDFReader(filename)

    wn = reader.xdata
    spectra = reader.spectra
    print(f"{filename.name}: wn={np.asarray(wn).shape}, spectra={np.asarray(spectra).shape}")

    # Plot embedded image if present (typical for mapping files, not always for TR/single spectra)
    img = _try_getattr(reader, "img")
    img_origins = _try_getattr(reader, "img_origins")
    img_dimensions = _try_getattr(reader, "img_dimensions")

    if img is not None and img_origins is not None and img_dimensions is not None:
        img_x0, img_y0 = img_origins
        img_w, img_h = img_dimensions
        img_arr = _coerce_imshow_image(img)
        plt.figure()
        plt.title(f"Embedded image: {filename.name}")
        plt.imshow(
            img_arr,
            extent=(img_x0, img_x0 + img_w, img_y0 + img_h, img_y0),
        )
        plt.tight_layout()
        plt.show()
    else:
        print(f"{filename.name}: no embedded image found (reader.img/img_origins/img_dimensions missing)")

def _coerce_imshow_image(img: object) -> np.ndarray:
    """
    renishawWiRE's `reader.img` may come back as an `object` array (e.g. RGB tuples).
    Matplotlib requires a numeric array or a PIL image.
    """
    # `reader.img` can be an in-memory image file (BytesIO).
    if isinstance(img, io.BytesIO):
        img.seek(0)
        return np.asarray(Image.open(img))

    arr = np.asarray(img)
    if arr.dtype != object:
        return arr

    lst = arr.tolist()

    # Common case: 2D array where each element is an RGB(A) tuple/list
    if arr.ndim == 2 and arr.size > 0 and isinstance(arr.flat[0], (tuple, list, np.ndarray)):
        # Build (H, W, C) explicitly; dtype forced numeric for Matplotlib.
        try:
            out = np.array([[list(px) for px in row] for row in lst], dtype=np.uint8)
            if out.dtype != object:
                return out
        except Exception:
            pass

    # Fallback: try forcing a numeric dtype.
    for dtype in (np.uint8, np.float32):
        try:
            out = np.array(lst, dtype=dtype)
            if out.dtype != object:
                return out
        except Exception:
            continue

    # Last resort: coerce each element and stack.
    try:
        if arr.ndim == 2:
            rows: list[np.ndarray] = []
            for row in lst:
                rows.append(np.stack([np.asarray(px, dtype=np.uint8) for px in row], axis=0))
            out = np.stack(rows, axis=0)
            if out.dtype != object:
                return out
    except Exception:
        pass

    raise TypeError(
        "Could not coerce `reader.img` into a numeric image array for Matplotlib. "
        f"Got shape={arr.shape}, dtype={arr.dtype}, sample_type={type(arr.flat[0]) if arr.size else None}."
    )

# Preview both example files
plot_wdf_preview(example_wdf_map)
plot_wdf_preview(example_wdf_tr)

# Note: The snippet below from the docs assumes `reader.img` is an image *path*.
# In your case it appears to be the image *data*, so `PIL.Image.open(reader.img)`
# will not work without additional handling.