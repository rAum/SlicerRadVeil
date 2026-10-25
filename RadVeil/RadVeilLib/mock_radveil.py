"""Stand-in for the ``radveil`` package, for development and self-tests.

Mirrors the slice of the public API the Slicer module uses, with the same
argument checking (unknown options raise ValueError, as in radveil):
``Volume.from_array`` / ``data`` / ``deface`` / ``deskull`` / ``render``,
``deface_volume``, ``anonymization_mask``, ``detect_landmarks`` and
``__version__``. The panel can then be developed and self-tested offline
(CI, Reload and Test) without installing radveil.

It does NOT detect faces and does NOT anonymize anything meaningfully: it
masks the anterior-most shell of the head (in RAS) and smooths/fills it.
Never use its output for real de-identification.
"""

import numpy as np

__version__ = "0.0.0+mock"
IS_MOCK = True

_MODES = ("adaptive", "blur", "cut", "block")
_REGIONS = ("face", "ears", "face+ears")
# Keys radveil's anonymization parameters accept (deface_params in radveil-py).
_DEFACE_KEYS = {
    "mode", "region", "ear_mode", "eye_surface_anchor", "spare_air", "level_face",
    "eye_bias_mm", "blur_sigma_mm", "adaptive_factor", "depth_behind_mm", "skin_depth_mm",
    "depth_front_mm", "width_factor", "above_eyes_mm", "below_chin_mm", "ear_inner_mm",
    "ear_outer_mm", "ear_guard_mm", "ear_down_mm", "ear_back_mm", "ear_height_mm",
    "ear_depth_mm",
}
_DEFACE_VOLUME_KEYS = {
    "yaws", "pitch", "size", "detector", "predictor_path", "fallback_detector",
    "fallback_brain_guard", "verify", "max_verify_rounds", "verify_pitches", "verify_effort",
    "escalate_to_block", "brain_check", "brain_guard", "brain_guard_mm", "partial_face",
    "auto_threshold", "threshold_frac", "threshold", "detector_upsample", "return_mask",
}
_MASK_KEYS = {
    "mask_path", "yaws", "pitch", "size", "detector", "predictor_path", "brain_check",
    "brain_guard", "brain_guard_mm", "partial_face", "threshold_frac", "threshold",
    "detector_upsample",
}


def _check(kwargs, allowed):
    unknown = set(kwargs) - allowed - _DEFACE_KEYS
    if unknown:
        raise ValueError(f"unknown anonymization parameter '{sorted(unknown)[0]}'")
    if kwargs.get("mode", "blur") not in _MODES:
        raise ValueError(f"unknown mode {kwargs['mode']!r}")
    if kwargs.get("ear_mode") not in (None,) + _MODES:
        raise ValueError(f"unknown mode {kwargs['ear_mode']!r}")
    if kwargs.get("region", "face") not in _REGIONS:
        raise ValueError(f"unknown region {kwargs['region']!r}")


class Volume:
    def __init__(self, path):
        raise NotImplementedError("mock radveil only supports Volume.from_array")

    @classmethod
    def from_array(cls, data, affine):
        self = cls.__new__(cls)
        data = np.asarray(data)
        if data.ndim != 3:
            raise ValueError("expected a 3D array")
        affine = np.asarray(affine, dtype=np.float64)
        if affine.shape != (4, 4):
            raise ValueError("affine must be 4x4")
        self._data = np.array(data, dtype=np.float32, order="C")
        self.affine = affine
        return self

    @property
    def shape(self):
        return self._data.shape

    def data(self):
        return self._data.copy()

    def render(self, yaw_deg=0.0, pitch_deg=0.0, size=512, **kwargs):
        return {"rgb": np.zeros((size, size, 3), np.uint8), "yaw_deg": yaw_deg, "pitch_deg": pitch_deg}

    def deface(self, points, mode="blur", region="face", return_mask=False, **kwargs):
        _check(dict(kwargs, mode=mode, region=region), set())
        pts = np.array([p for p in points if p is not None], dtype=np.float64)
        if len(pts) < 3:
            raise ValueError("not enough landmarks to build a face frame")
        head, world = _head(self)
        dist = np.linalg.norm(world - pts.mean(axis=0)[:, None, None, None], axis=0)
        mask = head & (dist < 30.0)
        _apply(self, mask, mode)
        rep = {"mock": True, "mode": mode, "region": region,
               "voxels_changed": int(mask.sum()), "voxels_total": int(mask.size)}
        if return_mask:
            rep["mask"] = mask.astype(np.uint8)
        return rep

    def deskull(self, method="synthstrip", modality="auto", strip=True, **kwargs):
        head, world = _head(self)
        center = np.array([w[head].mean() for w in world])
        spread = np.array([w[head].std() for w in world])
        rel = (world - center[:, None, None, None]) / (1.3 * spread[:, None, None, None])
        mask = head & ((rel ** 2).sum(axis=0) <= 1.0)
        if strip:
            self._data[~mask] = float(np.percentile(self._data, 1.0))
        voxel_ml = abs(np.linalg.det(self.affine[:3, :3])) / 1000.0
        return {"mask": mask.astype(np.uint8), "method": method, "modality": "mri",
                "brain_voxels": int(mask.sum()), "brain_volume_ml": float(mask.sum() * voxel_ml)}

    def __repr__(self):
        return f"<mock radveil.Volume shape={self.shape}>"


def _head(vol):
    d = vol._data
    hi, lo = float(np.percentile(d, 99.0)), float(np.percentile(d, 1.0))
    head = d > lo + 0.14 * (hi - lo)
    if head.sum() < 100:
        raise RuntimeError("no plausible face found (mock: no foreground)")
    idx = np.indices(d.shape).reshape(3, -1).astype(np.float64)
    world = (vol.affine[:3, :3] @ idx + vol.affine[:3, 3:4]).reshape((3,) + d.shape)
    return head, world


def _region_mask(vol, region):
    head, (r, a, s) = _head(vol)
    hr, ha, hs = r[head], a[head], s[head]
    mask = np.zeros(head.shape, dtype=bool)
    if region in ("face", "face+ears"):
        front = ha > np.percentile(ha, 85)
        mid_s = (hs > np.percentile(hs, 20)) & (hs < np.percentile(hs, 75))
        sel = np.zeros(head.shape, dtype=bool)
        sel[head] = front & mid_s
        mask |= sel
    if region in ("ears", "face+ears"):
        side = (hr < np.percentile(hr, 4)) | (hr > np.percentile(hr, 96))
        sel = np.zeros(head.shape, dtype=bool)
        sel[head] = side
        mask |= sel
    if not mask.any():
        raise RuntimeError("no plausible face found (mock)")
    return mask


def _landmarks(vol, mask):
    """68 pseudo-landmarks spread over the anterior face region (world mm)."""
    _, world = _head(vol)
    pts = np.stack([w[mask] for w in world], axis=1)
    front = pts[pts[:, 1] >= np.percentile(pts[:, 1], 70)]
    rng = np.random.default_rng(0)
    pick = front[rng.choice(len(front), size=68, replace=len(front) < 68)]
    return [tuple(float(c) for c in p) for p in pick]


def _apply(vol, mask, mode):
    d = vol._data
    if mode == "cut":
        d[mask] = float(np.percentile(d, 1.0))
    elif mode == "block":
        d[mask] = float(np.percentile(d, 99.0))
    elif mask.any():  # blur / adaptive: replace with the region mean
        d[mask] = float(d[mask].mean())


def _report(vol, mode, region, mask):
    rep = {
        "mock": True,
        "mode": mode,
        "region": region,
        "views_detected": 3,
        "eye_dist_mm": 63.0,
        "voxels_changed": int(mask.sum()),
        "voxels_total": int(mask.size),
        "views": [],
        "landmarks_3d": _landmarks(vol, _region_mask(vol, "face")),
        "rois": [],
    }
    if region in ("face", "face+ears"):
        rep["rois"].append({"label": "face", "voxels": int(mask.sum())})
    if region in ("ears", "face+ears"):
        rep["rois"] += [
            {"label": "ear_left", "detected": True, "protrusion_mm": 14.0},
            {"label": "ear_right", "detected": True, "protrusion_mm": 14.0},
        ]
    return rep


def deface_volume(vol, mode="blur", region="face", return_mask=False, brain_check=False, **kwargs):
    _check(dict(kwargs, mode=mode, region=region), _DEFACE_VOLUME_KEYS)
    mask = _region_mask(vol, region)
    rep = _report(vol, mode, region, mask)
    _apply(vol, mask, mode)
    rep.update(residual_detections=0, verify_rounds=1, escalated_to_block=False)
    if brain_check:
        rep["brain"] = {"voxels_modified": 0, "margin_mm": 6.6, "brain_volume_ml": 1150.0}
    if return_mask:
        rep["mask"] = mask.astype(np.uint8)
    return rep


def anonymization_mask(vol, mode="blur", region="face", **kwargs):
    _check(dict(kwargs, mode=mode, region=region), _MASK_KEYS)
    mask = _region_mask(vol, region)
    rep = _report(vol, mode, region, mask)
    rep["mask"] = mask.astype(np.uint8)
    return rep


def detect_landmarks(rgb, **kwargs):
    """The mock never sees a face."""
    return None
