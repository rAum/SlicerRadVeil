"""Tests for the Slicer-independent parts of the extension (no Slicer needed).

    pip install numpy pytest
    pytest tests/
"""

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "RadVeil"))

from RadVeilLib import backend, conversion, mock_radveil  # noqa: E402


def phantom(shape=(40, 48, 56), dtype=np.int16):
    nk, nj, ni = shape
    k, j, i = np.meshgrid(np.arange(nk), np.arange(nj), np.arange(ni), indexing="ij")
    head = ((i - ni / 2) / (ni * 0.35)) ** 2 + ((j - nj / 2) / (nj * 0.38)) ** 2 + (
        (k - nk / 2) / (nk * 0.4)
    ) ** 2 <= 1
    rng = np.random.default_rng(1)
    return (np.where(head, 900, 15) + rng.integers(0, 50, size=shape)).astype(dtype)


def test_axis_order_roundtrip():
    arr = np.arange(2 * 3 * 4).reshape(2, 3, 4)  # [k, j, i]
    rv = conversion.to_radveil_array(arr)
    assert rv.shape == (4, 3, 2) and rv.dtype == np.float32
    assert rv.flags["C_CONTIGUOUS"]
    # voxel (i=3, j=1, k=0) is arr[0, 1, 3]
    assert rv[3, 1, 0] == arr[0, 1, 3]


@pytest.mark.parametrize("dtype", [np.uint8, np.int16, np.uint16, np.int32, np.float32, np.float64])
def test_merge_back_bit_exact_outside_mask(dtype):
    original = phantom(dtype=np.int16).astype(dtype)
    if np.issubdtype(dtype, np.floating):
        original = original + np.asarray(0.123, dtype)
    data = conversion.to_radveil_array(original)
    mask = np.zeros(data.shape, np.uint8)
    mask[10:20, 30:40, 5:15] = 1
    defaced = data.copy()
    defaced[mask.astype(bool)] = 7.6
    defaced[~mask.astype(bool)] += 0.25  # simulate float noise outside the mask
    merged, n = conversion.merge_back(original, defaced, mask)
    assert merged.dtype == original.dtype
    m_kji = mask.transpose(2, 1, 0).astype(bool)
    np.testing.assert_array_equal(merged[~m_kji], original[~m_kji])
    # RadVeil computes in float32, so a float64 volume gets float32(7.6) widened
    expected = 8 if np.issubdtype(dtype, np.integer) else np.float32(7.6).astype(dtype)
    assert np.all(merged[m_kji] == expected)
    assert n == np.count_nonzero(original[m_kji] != expected)


def test_merge_back_clips_integer_range():
    original = np.full((2, 2, 2), 10, np.uint8)
    defaced = np.full((2, 2, 2), -50.0, np.float32)
    defaced[0, 0, 0] = 999.0
    merged, _ = conversion.merge_back(original, defaced, np.ones((2, 2, 2), np.uint8))
    assert merged.min() == 0 and merged.max() == 255


def test_merge_back_shape_mismatch():
    with pytest.raises(ValueError):
        conversion.merge_back(np.zeros((2, 3, 4)), np.zeros((2, 3, 4)), np.zeros((4, 3, 2)))


def test_rejects_non_3d_and_huge_ints():
    with pytest.raises(ValueError):
        conversion.to_radveil_array(np.zeros((2, 3, 4, 3)))
    with pytest.raises(ValueError):
        conversion.to_radveil_array(np.array([[[2 ** 25]]], dtype=np.int32))
    conversion.to_radveil_array(np.array([[[2 ** 24]]], dtype=np.int32))  # still exact


def test_affine_composition_and_validation():
    ijk = np.diag([1.0, 1.0, 1.2, 1.0])
    ijk[:3, 3] = (-30, -40, -35)
    parent = np.eye(4)
    parent[0, 3] = 10
    a = conversion.ijk_to_world_affine(ijk, parent)
    assert a[0, 3] == -20 and a[2, 2] == 1.2
    with pytest.raises(ValueError):
        conversion.ijk_to_world_affine(np.diag([1, 0, 1, 1]))


def test_mask_to_kji():
    m = np.zeros((4, 3, 2), np.uint8)
    m[3, 2, 1] = 5
    out = conversion.mask_to_kji(m)
    assert out.shape == (2, 3, 4) and out.dtype == np.uint8 and out[1, 2, 3] == 1


def test_mock_pipeline_end_to_end():
    original = phantom()
    affine = np.diag([1.0, 1.0, 1.0, 1.0])
    vol = mock_radveil.Volume.from_array(conversion.to_radveil_array(original), affine)
    rep = mock_radveil.deface_volume(vol, mode="cut", region="face+ears", return_mask=True,
                                     verify_effort="balanced", brain_guard=True)
    mask = rep.pop("mask")
    assert mask.shape == vol.shape and mask.any()
    merged, n = conversion.merge_back(original, vol.data(), mask)
    assert n > 0
    m_kji = conversion.mask_to_kji(mask).astype(bool)
    np.testing.assert_array_equal(merged[~m_kji], original[~m_kji])
    # face region is anterior (+A = +j here, identity affine)
    jj = np.nonzero(m_kji)[1]
    assert jj.mean() > original.shape[1] / 2 or rep["region"] == "face+ears"
    level, headline, details = conversion.assess(rep)
    assert level == conversion.ERROR and "mock" in headline
    assert any("Left ear" in t for _, t in details)
    json.loads(conversion.report_to_json(rep, parameters={"mode": "cut"}))


def test_mock_refuses_empty_volume():
    vol = mock_radveil.Volume.from_array(np.zeros((8, 8, 8), np.float32), np.eye(4))
    with pytest.raises(RuntimeError):
        mock_radveil.deface_volume(vol)


def test_json_safe_drops_arrays_and_nans():
    rep = {"mask": np.ones((3, 3, 3)), "x": np.float32(1.5), "y": float("nan"),
           "views": [{"landmarks": np.zeros((68, 2)), "score": np.float64(0.9)}],
           "small": np.array([1, 2])}
    out = conversion.json_safe(rep)
    assert out == {"x": 1.5, "y": None, "views": [{"score": 0.9}], "small": [1, 2]}


def test_backend_mock_switch(monkeypatch):
    monkeypatch.setenv("RADVEIL_SLICER_MOCK", "1")
    assert backend.is_mock(backend.load())
    monkeypatch.delenv("RADVEIL_SLICER_MOCK")
    assert backend.is_mock(backend.load(use_mock=True))
    if not backend.is_installed():
        with pytest.raises(ImportError):
            backend.load()


def test_real_package_accepts_module_kwargs():
    """With the real wheel installed: every keyword the module sends is
    accepted. A faceless phantom must be *refused* (RuntimeError), not
    rejected for a bad argument (TypeError/ValueError)."""
    if not backend.is_installed():
        return  # skipped until radveil is published / installed
    rv = backend.load()
    vol = rv.Volume.from_array(conversion.to_radveil_array(phantom()), np.eye(4))
    with pytest.raises(RuntimeError):
        rv.deface_volume(
            vol, mode="adaptive", region="face+ears", ear_mode="cut",
            verify_effort="fast", return_mask=True, brain_guard=False, brain_check=False,
            level_face=True, spare_air=True, auto_threshold=False, partial_face=False,
        )


def test_mock_matches_real_api_surface():
    """The mock must accept every keyword the module passes to radveil."""
    import inspect

    src = open(os.path.join(os.path.dirname(__file__), "..", "RadVeil", "RadVeil.py")).read()
    for kw in ("mode", "region", "verify_effort", "return_mask"):
        assert f"{kw}=" in src
    sig = inspect.signature(mock_radveil.deface_volume)
    assert any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())


# ---------------------------------------------------------------------------
# Verdicts shown to the user


def test_assess_clean_face():
    level, headline, details = conversion.assess(
        {"region": "face", "mode": "adaptive", "residual_detections": 0, "verify_rounds": 1}
    )
    assert level == conversion.OK and "no longer finds a face" in headline and details == []


def test_assess_residual_face_is_error():
    level, headline, _ = conversion.assess({"region": "face", "residual_detections": 2})
    assert level == conversion.ERROR and "may still be recognizable" in headline


def test_assess_missing_ear_is_warning():
    rep = {"region": "face+ears", "residual_detections": 0,
           "ears": [{"label": "ear_left", "detected": True, "protrusion_mm": 14.2},
                    {"label": "ear_right", "detected": False}]}
    level, headline, details = conversion.assess(rep)
    assert level == conversion.WARNING and "findings" in headline
    assert (conversion.OK, "Left ear found and anonymized (protrudes 14 mm).") in details
    assert any(lvl == conversion.WARNING and "Right ear" in t for lvl, t in details)


def test_assess_rois_fallback_and_brain():
    rep = {"region": "ears", "rois": [{"label": "ear_left", "detected": True}],
           "brain": {"voxels_modified": 0, "margin_mm": 6.6}}
    level, headline, details = conversion.assess(rep)
    assert level == conversion.OK and headline == "Ears anonymized."
    assert (conversion.OK, "Brain untouched, closest 6.6 mm.") in details
    rep["brain"]["voxels_modified"] = 12
    assert conversion.assess(rep)[0] == conversion.WARNING


def test_assess_mock_and_block():
    level, headline, details = conversion.assess(
        {"mock": True, "region": "face", "residual_detections": 0, "escalated_to_block": True})
    assert level == conversion.ERROR and headline.startswith("Test run with the mock")
    assert any("opaquely" in t for _, t in details)


def test_assess_block_escalation_is_amber_with_its_own_headline():
    level, headline, _ = conversion.assess(
        {"region": "face", "mode": "cut", "residual_detections": 0, "escalated_to_block": True})
    assert level == conversion.WARNING and headline.startswith("Anonymized with an opaque block")


def test_assess_block_escalation_names_the_chosen_method():
    def notes(mode):
        rep = {"region": "face", "residual_detections": 0, "escalated_to_block": True, "mode": mode}
        return [t for _, t in conversion.assess(rep)[2] if "opaquely" in t]

    assert notes("cut")[0].startswith("Removing the face was not enough")
    assert notes("blur")[0].startswith("Blurring alone")
    assert notes("adaptive")[0].startswith("Smoothing alone")
    assert not any("Smoothing" in t for t in notes(None))


def test_assess_residual_face_with_block_fallback_off():
    rep = {"region": "face", "mode": "cut", "residual_detections": 2, "block_fallback": False}
    level, _, details = conversion.assess(rep)
    assert level == conversion.ERROR
    assert any("applied as is" in t for _, t in details)
    rep.pop("block_fallback")
    assert not any("applied as is" in t for _, t in conversion.assess(rep)[2])


def test_surface_threshold_mri_and_ct():
    mri = phantom().astype(np.float32)
    lo, hi, thr = conversion.surface_threshold(mri)
    assert 15 <= lo < thr < hi <= 950
    assert abs(thr - (lo + 0.14 * (hi - lo))) < 1e-6
    ct = np.full((40, 40, 40), -1000.0)
    ct[10:30, 10:30, 10:30] = 40.0  # soft tissue
    ct[18:22, 18:22, 18:22] = 1200.0  # bone
    lo, hi, thr = conversion.surface_threshold(ct)
    assert lo == -1000.0 and -1000 < thr < 40  # skin surface sits between air and tissue
    assert conversion.surface_threshold(np.zeros((4, 4, 4)))[1] == 1.0  # flat volume


# ---------------------------------------------------------------------------
# Preview, other series, brain segment


def test_assess_preview():
    level, headline, details = conversion.assess(
        {"preview": True, "region": "face", "voxels_in_region": 12345,
         "rois": [{"label": "face"}]})
    assert level == conversion.NOTE and headline.startswith("Preview:") and "12,345" in headline
    assert not any("Verification" in t for _, t in details)


def test_assess_other_series_and_brain_segment():
    rep = {"region": "face", "residual_detections": 0, "brain_segment_ml": 1180.4,
           "other_series": [
               {"series_name": "FLAIR", "views_checked": 3, "faces_found": 0},
               {"series_name": "DWI", "error": "the face region does not overlap this series"},
           ]}
    level, headline, details = conversion.assess(rep)
    assert level == conversion.WARNING
    assert (conversion.NOTE, "Brain segment added (1180 ml).") in details
    assert any(t.startswith("FLAIR: anonymized") for _, t in details)
    assert any(lvl == conversion.WARNING and t.startswith("DWI: not anonymized") for lvl, t in details)
    rep["other_series"][0]["faces_found"] = 1
    assert conversion.assess(rep)[0] == conversion.ERROR


def test_series_names_never_reach_saved_report():
    rep = {"other_series": [{"series_name": "Doe^John FLAIR", "faces_found": 0}]}
    assert "Doe" not in conversion.report_to_json(rep)


def test_mock_rejects_options_like_radveil():
    vol = mock_radveil.Volume.from_array(conversion.to_radveil_array(phantom()), np.eye(4))
    with pytest.raises(ValueError):
        mock_radveil.deface_volume(vol, bogus_option=1)
    with pytest.raises(ValueError):  # anonymization_mask has no verification
        mock_radveil.anonymization_mask(vol, verify_effort="fast")
    rep = mock_radveil.anonymization_mask(vol, mode="adaptive", region="face+ears", ear_mode="cut",
                                          skin_depth_mm=5.0, level_face=True, brain_guard=True)
    assert rep["mask"].any() and len([p for p in rep["landmarks_3d"] if p]) == 68


def test_mock_propagation_and_deskull():
    original = phantom()
    vol = mock_radveil.Volume.from_array(conversion.to_radveil_array(original), np.eye(4))
    pts = mock_radveil.deface_volume(vol, mode="adaptive")["landmarks_3d"]
    other = mock_radveil.Volume.from_array(conversion.to_radveil_array(original), np.eye(4))
    rep = other.deface(pts, mode="cut", region="face", return_mask=True, skin_depth_mm=4.0)
    assert rep["mask"].any()
    far = [(x + 500.0, y, z) for x, y, z in pts]
    assert not other.deface(far, return_mask=True)["mask"].any()
    brain = mock_radveil.Volume.from_array(conversion.to_radveil_array(original), np.eye(4)).deskull(strip=False)
    assert brain["mask"].any() and brain["brain_volume_ml"] > 0
