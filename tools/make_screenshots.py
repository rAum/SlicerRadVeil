"""Capture real screenshots of the RadVeil module in 3D Slicer.

Run inside Slicer with the real radveil package installed:

    Slicer --no-splash --additional-module-paths <radveil-slicer>/RadVeil \
           --python-script tools/make_screenshots.py

Loads the public MRHead sample, runs RadVeil (face + ears, brain segment,
landmarks), opens the before/after comparison and writes into
RADVEIL_SCREENSHOT_DIR (default: ./Screenshots):

  layout.png    the comparison layout (3D views + slice views)
  panel.png     the module panel with the verdict
  preview.png   the "Preview region" layout

tools/compose_screenshot.py combines layout.png and panel.png into the
Extensions Manager screenshot. CI runs both and uploads the result.
"""

import os
import traceback

import slicer

OUT = os.path.abspath(os.environ.get("RADVEIL_SCREENSHOT_DIR", "Screenshots"))
status = 1
try:
    import SampleData
    import ScreenCapture


    os.makedirs(OUT, exist_ok=True)
    main = slicer.util.mainWindow()
    main.resize(1680, 1000)
    main.show()
    slicer.app.processEvents()

    volume = SampleData.downloadSample("MRHead")
    slicer.util.selectModule("RadVeil")
    widget = slicer.modules.radveil.widgetRepresentation().self()
    widget.inputSelector.setCurrentNode(volume)
    widget.regionButtons["face+ears"].click()
    widget._setComboValue(widget.earMethodCombo, "cut")
    widget.brainSegmentCheck.checked = True
    widget.landmarksCheck.checked = True
    widget.reviewAfterRunCheck.checked = True
    capture = ScreenCapture.ScreenCaptureLogic()

    def settle():
        for _ in range(20):
            slicer.app.processEvents()

    # Preview first (nothing changes), then the real run.
    widget.onPreview()
    settle()
    capture.captureImageFromView(None, os.path.join(OUT, "preview.png"))
    widget.compareButton.checked = False

    widget.onApply()
    if widget.lastResult is None:
        raise RuntimeError("RadVeil did not produce a result: " + widget.verdictLabel.text)
    settle()
    capture.captureImageFromView(None, os.path.join(OUT, "layout.png"))
    panel = (slicer.util.findChildren(main, name="PanelDockWidget") or [widget.parent])[0]
    panel.grab().save(os.path.join(OUT, "panel.png"))
    print(f"Screenshots written to {OUT}")
    status = 0
except Exception:
    traceback.print_exc()
finally:
    slicer.util.exit(status)
