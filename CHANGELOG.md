# Changelog

## 0.1.0

First release.

- Face, ears or face + ears anonymization with RadVeil (adaptive smoothing,
  blur, remove, opaque block; separate ear method), verified by re-running the
  face detector; refusal with hints when no face is found.
- The chosen method is applied exactly: if the face detector still finds a
  face, the result is marked red with suggestions instead of being switched
  to an opaque block (`process(..., blockFallback=True)` allows the switch
  for scripted batch runs).
- Before/after review: linked 3D skin-surface views with a threshold slider,
  changed region outlined in the slice views, previous layout restored.
- Preview region (nothing changed), detected face landmarks, SynthStrip brain
  segment, brain guard / brain contact report, skin depth control.
- Other series of the same session anonymized with the input's landmarks and
  re-checked with the face detector.
- Plain-language verdict and JSON report; outputs never reuse the input name.
- Disclaimer (aid, not a medical device, as is, without warranty) in the
  panel, the module help and every saved report.
- One-click install of the radveil package (Slicer's installer where
  available, or a wheel file for offline computers).
- Works in Slicer 5.6 and later; CI runs the self-test in the latest Slicer
  Stable and Preview, and the real radveil package on MRHead; tag-based
  releases to the Extensions Manager.
