# Changelog

## Unreleased

- The chosen method is applied exactly: RadVeil no longer switches to an
  opaque block by itself when the face detector still finds a face. The
  result is marked red instead and suggests what to try
  (`process(..., blockFallback=True)` restores RadVeil's behaviour).
- If a block fallback does happen, the Result box is amber, says so in its
  headline and names the chosen method (it always said "Smoothing alone").
- Skin threshold slider in the before/after review works in Slicer 5.8.

## 0.1.0

First release.

- Face, ears or face + ears anonymization with RadVeil (adaptive smoothing,
  blur, remove, opaque block; separate ear method), verified by re-running the
  face detector; refusal with hints when no face is found.
- Before/after review: linked 3D skin-surface views with a threshold slider,
  changed region outlined in the slice views, previous layout restored.
- Preview region (nothing changed), detected face landmarks, SynthStrip brain
  segment, brain guard / brain contact report, skin depth control.
- Other series of the same session anonymized with the input's landmarks and
  re-checked with the face detector.
- Plain-language verdict and JSON report; outputs never reuse the input name.
- One-click install of the radveil package (Slicer's installer where
  available, or a wheel file for offline computers).
- CI in real Slicer Stable and Preview on Linux, macOS and Windows; tag-based
  releases to the Extensions Manager.
