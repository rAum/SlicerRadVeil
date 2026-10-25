"""Array and geometry conversion between 3D Slicer and RadVeil.

Pure numpy, no Slicer imports, so it can be unit-tested outside Slicer.

Conventions:
  * ``slicer.util.arrayFromVolume`` returns voxels indexed ``[k, j, i]``.
  * ``radveil.Volume.from_array`` expects float32 indexed ``[i, j, k]`` plus
    the 4x4 voxel(IJK)->world affine in RAS+ millimetres, which is exactly
    Slicer's IJKToRAS matrix (combined with any linear parent transform).
  * The anonymization mask comes back on RadVeil's ``[i, j, k]`` grid.
"""

import json
import math

import numpy as np

# float32 has a 24-bit significand: every integer with |v| <= 2**24 survives
# the round trip to float32 and back unchanged.
FLOAT32_EXACT_INT_LIMIT = 2 ** 24


def to_radveil_array(arr_kji):
    """Slicer ``[k, j, i]`` array -> contiguous float32 ``[i, j, k]``.

    Raises ValueError for non-3D data and for integer data that float32
    cannot represent exactly (RadVeil computes in float32)."""
    arr_kji = np.asarray(arr_kji)
    if arr_kji.ndim != 3:
        raise ValueError(
            "RadVeil needs a single-component 3D volume; got an array with shape "
            f"{arr_kji.shape}. Split 4D/multi-component volumes first."
        )
    if arr_kji.size == 0:
        raise ValueError("input volume is empty")
    if np.issubdtype(arr_kji.dtype, np.integer) and arr_kji.dtype.itemsize >= 4:
        lo, hi = int(arr_kji.min()), int(arr_kji.max())
        if max(abs(lo), abs(hi)) > FLOAT32_EXACT_INT_LIMIT:
            raise ValueError(
                f"voxel values span [{lo}, {hi}], beyond the range float32 holds "
                "exactly; rescale the volume first."
            )
    if not np.issubdtype(arr_kji.dtype, np.number) or np.issubdtype(
        arr_kji.dtype, np.complexfloating
    ):
        raise ValueError(f"unsupported voxel type {arr_kji.dtype}")
    return np.ascontiguousarray(arr_kji.transpose(2, 1, 0), dtype=np.float32)


def ijk_to_world_affine(ijk_to_ras, parent_to_world=None):
    """4x4 IJK->world (RAS) affine as float64, optionally composed with a
    linear parent transform (``parent_to_world @ ijk_to_ras``)."""
    a = np.asarray(ijk_to_ras, dtype=np.float64).reshape(4, 4)
    if parent_to_world is not None:
        a = np.asarray(parent_to_world, dtype=np.float64).reshape(4, 4) @ a
    if not np.isfinite(a).all():
        raise ValueError("volume geometry contains non-finite values")
    if abs(np.linalg.det(a[:3, :3])) < 1e-12:
        raise ValueError("volume geometry is degenerate (zero spacing?)")
    return a


def merge_back(original_kji, defaced_ijk, mask_ijk):
    """Write RadVeil's result back into a copy of the original Slicer array.

    Only voxels inside ``mask_ijk`` change; every other voxel is copied from
    ``original_kji`` untouched, keeping the input dtype (bit-exact outside
    the mask, whatever the float32 round trip did). Values for integer
    dtypes are rounded and clipped to the dtype range.

    Returns ``(merged_kji, n_changed)`` where ``n_changed`` counts voxels
    whose stored value actually differs from the input."""
    original_kji = np.asarray(original_kji)
    defaced_kji = np.asarray(defaced_ijk).transpose(2, 1, 0)
    mask_kji = np.asarray(mask_ijk).transpose(2, 1, 0).astype(bool)
    if defaced_kji.shape != original_kji.shape or mask_kji.shape != original_kji.shape:
        raise ValueError(
            f"shape mismatch: input {original_kji.shape}, result {defaced_kji.shape}, "
            f"mask {mask_kji.shape} (all [k, j, i])"
        )
    vals = defaced_kji[mask_kji]
    dtype = original_kji.dtype
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        vals = np.clip(np.rint(vals.astype(np.float64)), info.min, info.max).astype(dtype)
    else:
        vals = vals.astype(dtype)
    merged = original_kji.copy()
    merged[mask_kji] = vals
    n_changed = int(np.count_nonzero(merged[mask_kji] != original_kji[mask_kji]))
    return merged, n_changed


def mask_to_kji(mask_ijk):
    """RadVeil mask ``[i, j, k]`` -> uint8 ``[k, j, i]`` for a Slicer labelmap."""
    return np.ascontiguousarray(np.asarray(mask_ijk).transpose(2, 1, 0) != 0, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Report helpers

# Bulky arrays, and series names (often patient names), never go into saved reports.
_DROP_KEYS = {"mask", "landmarks", "landmarks_3d", "rgb", "pos", "hit", "boundary", "series_name"}


def json_safe(obj):
    """Recursively turn a RadVeil report into JSON-serializable data, dropping
    bulky arrays (mask, landmarks, renders)."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items() if k not in _DROP_KEYS}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return None if obj.size > 64 else json_safe(obj.tolist())
    if isinstance(obj, np.generic):
        return json_safe(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)


DISCLAIMER = (
    "RadVeil is a de-identification aid, not a medical device and not a complete de-identification "
    "process; it does not by itself make data compliant with any privacy regulation. Only voxels in "
    "the anonymized region were changed: metadata, file names and DICOM tags were not. The face "
    "detector check shows resistance to that detector, not to every re-identification attack. "
    "Provided as is, without warranty of any kind and without liability, to the extent permitted by "
    "law. Review every output before sharing data."
)


def report_to_json(report, **extra):
    data = json_safe(report)
    data.update(json_safe(extra))
    return json.dumps(data, indent=2, sort_keys=True)


def surface_threshold(arr, frac=0.14):
    """Intensity range and skin-surface threshold for a 3D surface render.

    Mirrors RadVeil's default surface threshold (``threshold_frac=0.14``
    between the 1st and 99th intensity percentiles), so the review render
    shows roughly the surface the face detector sees.
    Returns ``(low, high, threshold)`` as floats."""
    a = np.asarray(arr)
    step = max(1, int(round((a.size / 2_000_000) ** (1 / 3))))  # subsample big volumes
    sample = a[::step, ::step, ::step].astype(np.float64).ravel()
    sample = sample[np.isfinite(sample)]
    if sample.size == 0:
        return 0.0, 1.0, 0.14
    lo, hi = np.percentile(sample, [1.0, 99.0])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi), float(lo + frac * (hi - lo))


# Verdict levels, worst last.
OK, NOTE, WARNING, ERROR = "ok", "note", "warning", "error"
_LEVEL_ORDER = (OK, NOTE, WARNING, ERROR)


# Why the region ended up as an opaque block, by the method the user chose.
_ESCALATION_NOTES = {
    "adaptive": "Smoothing alone was not enough; the face region was filled opaquely.",
    "blur": "Blurring alone was not enough; the face region was filled opaquely.",
    "cut": "Removing the face was not enough: the face detector still found a face in the exposed "
           "bone, so the face region was filled opaquely instead.",
    None: "The chosen method was not enough; the face region was filled opaquely.",
}


def assess(report):
    """Turn a RadVeil report into what the user needs to know.

    Returns ``(level, headline, details)``: ``level`` is one of ``ok``,
    ``note``, ``warning``, ``error``; ``headline`` one sentence; ``details``
    a list of ``(level, text)`` for individual findings."""
    r = report or {}
    preview = bool(r.get("preview"))
    details = []

    if r.get("mock"):
        details.append((ERROR, "Mock backend: this is not RadVeil's real result."))

    residual = r.get("residual_detections")
    if residual is not None and residual > 0:
        details.append((ERROR, f"The face detector still found a face in {residual} view(s)."))
        if r.get("block_fallback") is False:
            details.append((NOTE, "The method you chose was applied as is. Try Opaque block, a stronger "
                                  "method, or Remove more of the lips and chin (Advanced)."))
    elif residual is None and not preview and r.get("region") != "ears":
        details.append((NOTE, "Verification was not run."))
    if r.get("escalated_to_block"):
        details.append((WARNING, _ESCALATION_NOTES.get(r.get("mode"), _ESCALATION_NOTES[None])))

    ears = r.get("ears") or [
        roi for roi in (r.get("rois") or []) if isinstance(roi, dict) and "ear" in str(roi.get("label", ""))
    ]
    for ear in ears if isinstance(ears, list) else []:
        if not isinstance(ear, dict):
            continue
        side = str(ear.get("label", "ear")).replace("ear_", "").replace("_", " ").capitalize()
        if ear.get("detected"):
            mm = ear.get("protrusion_mm")
            extra = f" (protrudes {float(mm):.0f} mm)" if isinstance(mm, (int, float)) else ""
            verb = "found" if preview else "found and anonymized"
            details.append((OK, f"{side} ear {verb}{extra}."))
        elif "detected" in ear:
            details.append((WARNING, f"{side} ear not found - outside the field of view? Check it."))

    brain = r.get("brain")
    if isinstance(brain, dict):
        n = brain.get("voxels_modified")
        margin = brain.get("margin_mm")
        margin_txt = f", closest {float(margin):.1f} mm" if isinstance(margin, (int, float)) else ""
        if n:
            details.append((WARNING, f"{n} brain voxels {'would be' if preview else 'were'} modified{margin_txt}."))
        elif n == 0:
            details.append((OK, f"Brain untouched{margin_txt}."))

    if isinstance(r.get("brain_segment_ml"), (int, float)):
        details.append((NOTE, f"Brain segment added ({float(r['brain_segment_ml']):.0f} ml)."))

    for i, series in enumerate(r.get("other_series") or [], start=2):
        name = series.get("series_name") or f"Series {i}"
        if series.get("error"):
            details.append((WARNING, f"{name}: not anonymized - {series['error']}."))
        elif series.get("faces_found"):
            details.append((ERROR, f"{name}: the face detector still finds a face in "
                                   f"{series['faces_found']} of {series.get('views_checked', '?')} views."))
        elif series.get("recheck_error"):
            details.append((WARNING, f"{name}: anonymized, but the re-check failed ({series['recheck_error']})."))
        else:
            details.append((OK, f"{name}: anonymized with the same landmarks; no face found in "
                                f"{series.get('views_checked', 0)} re-check views."))

    level = max((lvl for lvl, _ in details), key=_LEVEL_ORDER.index, default=OK)
    if preview:
        n = r.get("voxels_in_region")
        size = f" ({n:,} voxels)" if isinstance(n, int) else ""
        headline = f"Preview: the outlined region{size} would be anonymized. Nothing was changed."
        level = max(level, NOTE, key=_LEVEL_ORDER.index)
    elif r.get("mock"):
        headline = "Test run with the mock backend - output is not anonymized."
    elif level == ERROR:
        headline = "A face may still be recognizable. Review it, or try Remove or Opaque block."
    elif r.get("escalated_to_block"):
        headline = "Anonymized with an opaque block, not the chosen method. The face detector no longer finds a face."
    elif level == WARNING:
        headline = "Anonymized, with findings to check."
    elif r.get("region") == "ears":
        headline = "Ears anonymized."
    else:
        headline = "Anonymized. The face detector no longer finds a face."
    return level, headline, details
