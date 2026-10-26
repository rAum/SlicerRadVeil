import importlib
import json
import logging
import os
import threading
import time

import numpy as np
import qt
import ctk
import vtk

import slicer
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleTest,
    ScriptedLoadableModuleWidget,
)
from slicer.util import VTKObservationMixin

from RadVeilLib import backend, conversion

# (radveil value, label, tooltip)
REGIONS = (
    ("face", "Face", "Anonymize the face only."),
    ("face+ears", "Face + ears", "Anonymize the face and both ears (the ear shape also identifies people)."),
    ("ears", "Ears only", "Anonymize both ears and leave the face as it is."),
)
METHODS = (
    ("adaptive", "Adaptive smoothing (recommended)",
     "Smooths facial features, most strongly where they are sharpest. The head keeps a natural look."),
    ("blur", "Blur", "Gaussian blur of the face region."),
    ("cut", "Remove", "Replace the region with background (0 on MRI, air on CT)."),
    ("block", "Opaque block", "Fill the region with an opaque slab."),
)
EAR_METHODS = (("", "Same as face", "Use the face method for the ears too."),) + tuple(
    (value, label.replace(" (recommended)", ""), tip) for value, label, tip in METHODS
)
VERIFY_EFFORTS = (
    ("balanced", "Standard", "Re-check the result from the detection views plus 9 views around the face."),
    ("fast", "Fast", "Re-check only from the views where the face was detected."),
    ("thorough", "Thorough", "Re-check from 25 views around the face (slower)."),
)
# (radveil flag, label, tooltip, group)
FLAG_OPTIONS = (
    ("brain_guard", "Never touch the brain",
     "Extract the brain (SynthStrip) and keep the anonymization at least 3 mm away from it. Adds a few seconds.",
     "Safety"),
    ("brain_check", "Report brain contact",
     "Extract the brain and report whether any brain voxel was modified, and how close the region came.",
     "Safety"),
    ("level_face", "Remove more of the lips and chin",
     "Measure the face along the level head axes. Removes much more of the lower lip and chin.",
     "Coverage"),
    ("partial_face", "Face cut by the field of view",
     "Handle scans whose field of view cuts through the face, e.g. an axial slab without the mouth.",
     "Coverage"),
    ("auto_threshold", "Noisy or dim scans",
     "If no face is found, retry at higher surface thresholds (e.g. infant T1).",
     "Coverage"),
    ("spare_air", "Leave background air unchanged",
     "Do not rewrite background air in the region; roughly halves the number of changed voxels.",
     "Coverage"),
)
FLAG_NAMES = tuple(f[0] for f in FLAG_OPTIONS)
REPORT_ATTRIBUTE = "RadVeil.Report"
LEVEL_COLORS = {
    conversion.OK: (46, 125, 50),
    conversion.NOTE: (21, 101, 192),
    conversion.WARNING: (239, 108, 0),
    conversion.ERROR: (198, 40, 40),
}


def developerMode():
    return slicer.util.settingsValue("Developer/DeveloperMode", False, converter=slicer.util.toBool)


#
# RadVeil
#


class RadVeil(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "RadVeil Defacing"
        self.parent.categories = ["Utilities"]
        self.parent.dependencies = []
        self.parent.contributors = ["Piotr Gródek (independent)"]
        self.parent.helpText = """
Removes the face (and optionally the ears) from MRI and CT head volumes so
the scan cannot be recognized from a 3D rendering, using
<a href="https://github.com/rAum/radveil">RadVeil</a>.
<ol>
<li>Select the input volume, what to anonymize and the method.</li>
<li>Optionally click <b>Preview region</b> to see where it would anonymize,
with the face landmarks it found, without changing anything.</li>
<li>Click <b>Anonymize</b>. Under <i>Other series</i> you can tick more
series of the same session (e.g. FLAIR): they are anonymized with the face
found on the input and re-checked with the face detector.</li>
<li>Check the result: the original and anonymized faces are shown side by
side in linked 3D views. Rotate them, and move <i>Skin threshold</i> to look
for any remaining facial detail. <i>Add brain segment</i> shows the brain
(blue) next to the changed region (amber).</li>
</ol>
A smoothed face can show concentric rings in 3D: they are the level steps of
the heavily smoothed intensities (stored in the input's integer type), not
leftover facial detail. The 3D views are not smoothed for display, so any
detail that remains is visible.
<br><br>
RadVeil finds the face with a built-in face detector on 3D renders and
accepts its result only when the detector no longer finds a face. Voxels
outside the anonymized region are not changed.
<br><br>
<b>Always review the output before sharing data.</b> Only voxels are
changed: names in the scene, file names and DICOM tags are not; use DICOM
anonymization when exporting. The face detector check shows resistance to
that kind of detector, not to every possible re-identification attack.
<br><br>
<b>Disclaimer.</b> Early release with limited validation. RadVeil and this
extension are a de-identification <i>aid</i>, not a medical device and not
a complete de-identification process. They are not intended for diagnosis
or treatment and do not by themselves make data compliant with any privacy
regulation (e.g. HIPAA, GDPR). Provided "as is", without warranty of any
kind; to the maximum extent permitted by law, the authors accept no
liability for damages or losses arising from their use. You are responsible
for validating them for your use case.
<br><br>
<a href="https://rAum.github.io/radveil/docs.html">RadVeil documentation</a>
"""
        self.parent.acknowledgementText = """
RadVeil and this extension are developed by Piotr Gródek as a personal,
open-source project (Apache-2.0), not affiliated with or endorsed by any
employer of the author. RadVeil embeds the MediaPipe BlazeFace and Face Mesh
models (Apache-2.0, Google LLC) and the SynthStrip network weights (MIT;
please cite Hoopes et al., NeuroImage 260 (2022) 119474 when publishing).
These names identify components only and imply no endorsement by their
owners. Provided "as is", without warranty; not a medical device.
"""


#
# Widget
#


class RadVeilWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.review = None
        self._parameterNode = None
        self._updatingGUI = False
        self.lastResult = None

    # -- layout ------------------------------------------------------------

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = RadVeilLogic()
        self.review = RadVeilReview()

        self._setupInstallBanner()
        self._setupInputs()
        self._setupOutputs()
        self._setupOtherSeries()
        self._setupAdvanced()
        self._setupDeveloper()

        buttons = qt.QHBoxLayout()
        self.previewButton = qt.QPushButton("Preview region")
        self.previewButton.setMinimumHeight(32)
        self.previewButton.toolTip = (
            "Find the face and outline the region that would be anonymized, without changing anything."
        )
        self.applyButton = qt.QPushButton("Anonymize")
        self.applyButton.setMinimumHeight(32)
        font = self.applyButton.font
        font.setBold(True)
        self.applyButton.font = font
        buttons.addWidget(self.previewButton, 1)
        buttons.addWidget(self.applyButton, 2)
        self.layout.addLayout(buttons)

        disclaimer = qt.QLabel(
            "De-identification aid, not a medical device; provided as is, without warranty. "
            "Review every output before sharing data."
        )
        disclaimer.wordWrap = True
        disclaimer.setStyleSheet("color: gray; font-size: 10px;")
        disclaimer.toolTip = conversion.DISCLAIMER
        self.layout.addWidget(disclaimer)

        self._setupResults()
        self.layout.addStretch(1)

        self.applyButton.connect("clicked(bool)", self.onApply)
        self.previewButton.connect("clicked(bool)", self.onPreview)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.initializeParameterNode()
        self.updateBackendState()

    def _setupInstallBanner(self):
        self.installBanner = qt.QFrame()
        self.installBanner.objectName = "installBanner"
        self.installBanner.setStyleSheet(
            "QFrame#installBanner { border: 1px solid rgba(21,101,192,160);"
            " background-color: rgba(21,101,192,25); border-radius: 4px; }"
        )
        row = qt.QHBoxLayout(self.installBanner)
        label = qt.QLabel(
            "RadVeil needs a one-time download of its Python package "
            "(prebuilt, no compiler or GPU needed)."
        )
        label.wordWrap = True
        row.addWidget(label, 1)
        self.installButton = qt.QPushButton("Install")
        self.installButton.toolTip = f"pip install {backend.REQUIREMENT} into Slicer's Python"
        self.installFromFileButton = qt.QPushButton("From file...")
        self.installFromFileButton.toolTip = (
            "For computers without internet access: install a radveil .whl file downloaded elsewhere."
        )
        row.addWidget(self.installButton)
        row.addWidget(self.installFromFileButton)
        self.layout.addWidget(self.installBanner)
        self.installButton.connect("clicked(bool)", lambda checked=False: self.installBackend())
        self.installFromFileButton.connect("clicked(bool)", self.onInstallFromFile)

    def _setupInputs(self):
        box = ctk.ctkCollapsibleButton()
        box.text = "Inputs"
        self.layout.addWidget(box)
        form = qt.QFormLayout(box)

        self.inputSelector = slicer.qMRMLNodeComboBox()
        self.inputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.inputSelector.showChildNodeTypes = False  # no labelmaps
        self.inputSelector.addEnabled = False
        self.inputSelector.removeEnabled = False
        self.inputSelector.noneEnabled = False
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.toolTip = "MRI or CT volume of the head."
        form.addRow("Input volume:", self.inputSelector)

        regionRow = qt.QHBoxLayout()
        self.regionGroup = qt.QButtonGroup(box)
        self.regionButtons = {}
        for index, (value, label, tip) in enumerate(REGIONS):
            button = qt.QRadioButton(label)
            button.toolTip = tip
            self.regionGroup.addButton(button, index)
            self.regionButtons[value] = button
            regionRow.addWidget(button)
        regionRow.addStretch(1)
        form.addRow("Anonymize:", regionRow)

        self.methodCombo = self._makeCombo(METHODS)
        form.addRow("Method:", self.methodCombo)

        self.inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.regionGroup.connect("buttonToggled(QAbstractButton*,bool)", self.updateParameterNodeFromGUI)
        self.methodCombo.connect("currentIndexChanged(int)", self.updateParameterNodeFromGUI)

    def _setupOutputs(self):
        box = ctk.ctkCollapsibleButton()
        box.text = "Outputs"
        self.layout.addWidget(box)
        form = qt.QFormLayout(box)

        self.outputSelector = slicer.qMRMLNodeComboBox()
        self.outputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.outputSelector.showChildNodeTypes = False
        self.outputSelector.addEnabled = True
        self.outputSelector.renameEnabled = True
        self.outputSelector.removeEnabled = True
        self.outputSelector.noneEnabled = True
        self.outputSelector.noneDisplay = "Create new volume"
        self.outputSelector.setMRMLScene(slicer.mrmlScene)
        self.outputSelector.toolTip = (
            "Where to store the anonymized volume. Choose the input volume to overwrite it."
        )
        form.addRow("Anonymized volume:", self.outputSelector)

        self.regionSelector = slicer.qMRMLNodeComboBox()
        self.regionSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self.regionSelector.addEnabled = True
        self.regionSelector.renameEnabled = True
        self.regionSelector.removeEnabled = True
        self.regionSelector.noneEnabled = True
        self.regionSelector.noneDisplay = "Create new segmentation"
        self.regionSelector.setMRMLScene(slicer.mrmlScene)
        self.regionSelector.toolTip = (
            "Segmentation that receives the exact region that was changed, for review and audit."
        )
        form.addRow("Changed region:", self.regionSelector)

        self.reviewAfterRunCheck = qt.QCheckBox("Show before/after comparison when done")
        self.reviewAfterRunCheck.toolTip = (
            "Switch to a layout with the original and the anonymized face side by side in linked 3D views."
        )
        form.addRow(self.reviewAfterRunCheck)

        self.brainSegmentCheck = qt.QCheckBox("Add brain segment (SynthStrip, a few seconds)")
        self.brainSegmentCheck.toolTip = (
            "Also extract the brain and add it as a blue segment next to the amber changed region, "
            "so you can see how far the anonymization stays from the brain."
        )
        form.addRow(self.brainSegmentCheck)
        self.landmarksCheck = qt.QCheckBox("Show detected face landmarks")
        self.landmarksCheck.toolTip = (
            "Show the 68 face landmarks RadVeil found (3D points) in the comparison, to confirm it "
            "found the real face."
        )
        form.addRow(self.landmarksCheck)

        for selector in (self.outputSelector, self.regionSelector):
            selector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        for check in (self.reviewAfterRunCheck, self.brainSegmentCheck, self.landmarksCheck):
            check.connect("toggled(bool)", self.updateParameterNodeFromGUI)

    def _setupOtherSeries(self):
        box = ctk.ctkCollapsibleButton()
        box.text = "Other series"
        box.collapsed = True
        self.layout.addWidget(box)
        form = qt.QFormLayout(box)
        note = qt.QLabel(
            "Anonymize more series of the same session with the face found on the input, e.g. "
            "FLAIR or DWI where detection is harder. They must be aligned with the input "
            "(same scanner session, or registered). Each is re-checked with the face detector."
        )
        note.wordWrap = True
        form.addRow(note)
        self.otherSeriesSelector = slicer.qMRMLCheckableNodeComboBox()
        self.otherSeriesSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.otherSeriesSelector.showChildNodeTypes = False
        self.otherSeriesSelector.addEnabled = False
        self.otherSeriesSelector.removeEnabled = False
        self.otherSeriesSelector.setMRMLScene(slicer.mrmlScene)
        self.otherSeriesSelector.toolTip = "Tick the series to anonymize together with the input."
        form.addRow("Also anonymize:", self.otherSeriesSelector)
        self.otherSeriesSelector.connect("checkedNodesChanged()", self.updateApplyButton)

    def checkedOtherSeries(self):
        inputVolume = self.inputSelector.currentNode()
        return [n for n in self.otherSeriesSelector.checkedNodes() if n is not inputVolume]

    def _setupAdvanced(self):
        box = ctk.ctkCollapsibleButton()
        box.text = "Advanced"
        box.collapsed = True
        self.layout.addWidget(box)
        form = qt.QFormLayout(box)

        self.earMethodCombo = self._makeCombo(EAR_METHODS)
        form.addRow("Ear method:", self.earMethodCombo)
        self.verifyCombo = self._makeCombo(VERIFY_EFFORTS)
        form.addRow("Verification:", self.verifyCombo)
        self.skinDepthSpin = qt.QDoubleSpinBox()
        self.skinDepthSpin.setRange(0.0, 12.0)
        self.skinDepthSpin.setSingleStep(0.5)
        self.skinDepthSpin.setDecimals(1)
        self.skinDepthSpin.suffix = " mm"
        self.skinDepthSpin.specialValueText = "Automatic"
        self.skinDepthSpin.toolTip = (
            "How deep below the measured skin the face region reaches. Automatic scales it to the "
            "head (about 4.5 mm), chosen to stay above the skull. Deeper removes more but comes "
            "closer to the brain."
        )
        form.addRow("Skin depth:", self.skinDepthSpin)
        self.skinDepthSpin.connect("valueChanged(double)", self.updateParameterNodeFromGUI)

        self.flagChecks = {}
        groups = {}
        for name, label, tip, group in FLAG_OPTIONS:
            if group not in groups:
                column = qt.QVBoxLayout()
                column.setSpacing(2)
                groups[group] = column
                form.addRow(f"{group}:", column)
            check = qt.QCheckBox(label)
            check.toolTip = tip
            groups[group].addWidget(check)
            self.flagChecks[name] = check
            check.connect("toggled(bool)", self.updateParameterNodeFromGUI)

        self.earMethodCombo.connect("currentIndexChanged(int)", self.updateParameterNodeFromGUI)
        self.verifyCombo.connect("currentIndexChanged(int)", self.updateParameterNodeFromGUI)

    def _setupDeveloper(self):
        self.developerBox = ctk.ctkCollapsibleButton()
        self.developerBox.text = "Developer"
        self.developerBox.collapsed = True
        self.layout.addWidget(self.developerBox)
        form = qt.QFormLayout(self.developerBox)
        self.packageLabel = qt.QLabel()
        form.addRow("Package:", self.packageLabel)
        row = qt.QHBoxLayout()
        reinstall = qt.QPushButton("Install / update")
        fromFile = qt.QPushButton("Install from file...")
        row.addWidget(reinstall)
        row.addWidget(fromFile)
        form.addRow(row)
        self.mockCheck = qt.QCheckBox("Use mock backend (does NOT anonymize)")
        self.mockCheck.toolTip = (
            "Run against a built-in stand-in for the radveil package, for developing and "
            "testing the extension without the real package."
        )
        form.addRow(self.mockCheck)
        reinstall.connect("clicked(bool)", lambda checked=False: self.installBackend())
        fromFile.connect("clicked(bool)", self.onInstallFromFile)
        self.mockCheck.connect("toggled(bool)", self.updateParameterNodeFromGUI)

    def _setupResults(self):
        self.resultsBox = ctk.ctkCollapsibleButton()
        self.resultsBox.text = "Result"
        self.resultsBox.visible = False
        self.layout.addWidget(self.resultsBox)
        layout = qt.QVBoxLayout(self.resultsBox)

        self.verdictFrame = qt.QFrame()
        self.verdictFrame.objectName = "verdict"
        verdictLayout = qt.QVBoxLayout(self.verdictFrame)
        self.verdictLabel = qt.QLabel()
        self.verdictLabel.wordWrap = True
        self.verdictLabel.textInteractionFlags = qt.Qt.TextSelectableByMouse
        verdictLayout.addWidget(self.verdictLabel)
        layout.addWidget(self.verdictFrame)

        reviewForm = qt.QFormLayout()
        self.compareButton = qt.QPushButton("Compare before / after")
        self.compareButton.checkable = True
        self.compareButton.toolTip = (
            "Original and anonymized faces side by side in linked 3D views, with the anonymized "
            "volume and the changed region in the slice views."
        )
        reviewForm.addRow(self.compareButton)
        self.thresholdSlider = ctk.ctkSliderWidget()
        self.thresholdSlider.toolTip = (
            "Intensity of the skin surface in the 3D comparison. Move it to look for facial detail "
            "that a different surface would reveal."
        )
        self.thresholdSlider.enabled = False
        reviewForm.addRow("Skin threshold:", self.thresholdSlider)
        layout.addLayout(reviewForm)

        buttons = qt.QHBoxLayout()
        buttons.addStretch(1)
        self.saveReportButton = qt.QPushButton("Save report...")
        self.saveReportButton.toolTip = "Save RadVeil's full JSON report, e.g. for your study records."
        buttons.addWidget(self.saveReportButton)
        layout.addLayout(buttons)

        self.compareButton.connect("toggled(bool)", self.onCompareToggled)
        self.thresholdSlider.connect("valueChanged(double)", self.review.setThreshold)
        self.saveReportButton.connect("clicked(bool)", self.onSaveReport)

    @staticmethod
    def _makeCombo(items):
        combo = qt.QComboBox()
        for index, (value, label, tip) in enumerate(items):
            combo.addItem(label, value)
            combo.setItemData(index, tip, qt.Qt.ToolTipRole)
        return combo

    @staticmethod
    def _comboValue(combo):
        return combo.itemData(combo.currentIndex) or ""

    @staticmethod
    def _setComboValue(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    # -- module life cycle ---------------------------------------------------

    def cleanup(self):
        self.removeObservers()
        if self.review:
            self.review.end()

    def enter(self):
        self.initializeParameterNode()
        self.updateBackendState()

    def exit(self):
        if self._parameterNode:
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    def onSceneStartClose(self, caller, event):
        self.setParameterNode(None)
        self.review.forget()
        self.lastResult = None
        self.compareButton.checked = False
        self.resultsBox.visible = False

    def onSceneEndClose(self, caller, event):
        if self.parent.isEntered:
            self.initializeParameterNode()

    # -- parameter node ----------------------------------------------------

    def initializeParameterNode(self):
        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, node):
        if node:
            self.logic.setDefaultParameters(node)
        if self._parameterNode is not None:
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self._parameterNode = node
        if self._parameterNode is not None:
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self.updateGUIFromParameterNode()

    def updateGUIFromParameterNode(self, caller=None, event=None):
        if self._parameterNode is None or self._updatingGUI:
            return
        self._updatingGUI = True
        try:
            p = self._parameterNode
            if p.GetNodeReference("InputVolume"):
                self.inputSelector.setCurrentNode(p.GetNodeReference("InputVolume"))
            self.outputSelector.setCurrentNode(p.GetNodeReference("OutputVolume"))
            self.regionSelector.setCurrentNode(p.GetNodeReference("RegionSegmentation"))
            region = p.GetParameter("Region")
            self.regionButtons.get(region, self.regionButtons["face"]).checked = True
            self._setComboValue(self.methodCombo, p.GetParameter("Method"))
            self._setComboValue(self.earMethodCombo, p.GetParameter("EarMethod"))
            self._setComboValue(self.verifyCombo, p.GetParameter("Verify"))
            for name, check in self.flagChecks.items():
                check.checked = p.GetParameter(name) == "true"
            self.reviewAfterRunCheck.checked = p.GetParameter("ReviewAfterRun") == "true"
            self.brainSegmentCheck.checked = p.GetParameter("BrainSegment") == "true"
            self.landmarksCheck.checked = p.GetParameter("ShowLandmarks") != "false"
            skin = p.GetParameter("SkinDepth")
            self.skinDepthSpin.value = float(skin) if skin else 0.0
            self.mockCheck.checked = p.GetParameter("UseMock") == "true"
            self.earMethodCombo.enabled = "ears" in region
            self.methodCombo.toolTip = self.methodCombo.itemData(self.methodCombo.currentIndex, qt.Qt.ToolTipRole)
        finally:
            self._updatingGUI = False
        self.updateApplyButton()

    def updateParameterNodeFromGUI(self, *args):
        if self._parameterNode is None or self._updatingGUI:
            return
        p = self._parameterNode
        wasModifying = p.StartModify()
        try:
            p.SetNodeReferenceID("InputVolume", self.inputSelector.currentNodeID)
            p.SetNodeReferenceID("OutputVolume", self.outputSelector.currentNodeID)
            p.SetNodeReferenceID("RegionSegmentation", self.regionSelector.currentNodeID)
            region = next((v for v, b in self.regionButtons.items() if b.checked), "face")
            p.SetParameter("Region", region)
            p.SetParameter("Method", self._comboValue(self.methodCombo))
            p.SetParameter("EarMethod", self._comboValue(self.earMethodCombo))
            p.SetParameter("Verify", self._comboValue(self.verifyCombo))
            for name, check in self.flagChecks.items():
                p.SetParameter(name, "true" if check.checked else "false")
            p.SetParameter("ReviewAfterRun", "true" if self.reviewAfterRunCheck.checked else "false")
            p.SetParameter("BrainSegment", "true" if self.brainSegmentCheck.checked else "false")
            p.SetParameter("ShowLandmarks", "true" if self.landmarksCheck.checked else "false")
            skin = self.skinDepthSpin.value
            p.SetParameter("SkinDepth", f"{skin:g}" if skin > 0 else "")
            p.SetParameter("UseMock", "true" if self.mockCheck.checked else "false")
        finally:
            p.EndModify(wasModifying)
        self.updateBackendState()

    # -- backend -----------------------------------------------------------

    def useMock(self):
        return backend.mock_requested() or (developerMode() and self.mockCheck.checked)

    def updateBackendState(self):
        dev = developerMode()
        version = backend.installed_version()
        mock = self.useMock()
        self.developerBox.visible = dev or backend.mock_requested()
        self.installBanner.visible = not version and not mock
        if mock:
            self.packageLabel.text = "<b style='color:#c62828'>mock backend active</b>"
        else:
            self.packageLabel.text = f"radveil {version}" if version else "not installed"
        self.updateApplyButton()

    def updateApplyButton(self):
        hasInput = self.inputSelector.currentNode() is not None
        self.applyButton.enabled = hasInput
        self.previewButton.enabled = hasInput
        nOther = len(self.checkedOtherSeries()) if hasattr(self, "otherSeriesSelector") else 0
        text = "Anonymize" if not nOther else f"Anonymize {nOther + 1} series"
        self.applyButton.text = f"{text} (mock backend)" if self.useMock() else text
        if not hasInput:
            self.applyButton.toolTip = "Load or select a head volume first."
        else:
            self.applyButton.toolTip = "Find the face, anonymize it and verify the result."

    @staticmethod
    def _slicerPackaging():
        """``slicer.packaging`` if this Slicer has ``pip_ensure`` (recent versions), else None."""
        try:
            import slicer.packaging as packaging
        except ImportError:
            return None
        return packaging if hasattr(packaging, "pip_ensure") else None

    def installBackend(self, wheelPath=None, prompt=False):
        """Install radveil. Returns True on success.

        Uses Slicer's standard dependency installer (confirmation, progress with
        log, restart prompt) where available; otherwise pip with a busy dialog."""
        packaging = self._slicerPackaging() if wheelPath is None else None
        if packaging is not None:
            try:
                packaging.pip_ensure(
                    backend.REQUIREMENT, requester="RadVeil Defacing", prompt_install=prompt
                )
            except RuntimeError:  # declined by the user
                return False
            except Exception as e:
                slicer.util.errorDisplay(
                    "Installing RadVeil failed. Check the internet connection, or install a "
                    f"downloaded wheel file with 'From file...'.\n\n{e}",
                    windowTitle="RadVeil",
                )
                return False
            finally:
                importlib.invalidate_caches()
                self.updateBackendState()
            return backend.is_installed()
        if prompt and not slicer.util.confirmOkCancelDisplay(
            "RadVeil needs to download its Python package once (prebuilt for Windows, "
            "macOS and Linux).\n\nInstall it now?",
            windowTitle="RadVeil",
        ):
            return False
        progress = slicer.util.createProgressDialog(
            windowTitle="RadVeil",
            labelText="Installing the RadVeil package...\nThis is needed only once.",
            maximum=0,
        )
        progress.setCancelButton(None)
        progress.setWindowModality(qt.Qt.ApplicationModal)
        progress.show()
        slicer.app.processEvents()
        version = None
        try:
            with slicer.util.tryWithErrorDisplay(
                "Installing RadVeil failed. Check the internet connection, or install a "
                "downloaded wheel file with 'From file...'.",
                waitCursor=True,
            ):
                version = backend.install(wheel_path=wheelPath)
        finally:
            progress.close()
        self.updateBackendState()
        if version:
            slicer.util.showStatusMessage(f"RadVeil {version} installed.", 5000)
        return bool(version)

    def onInstallFromFile(self, *args):
        path = qt.QFileDialog.getOpenFileName(
            slicer.util.mainWindow(), "Select a radveil wheel file", "", "Python wheel (*.whl)"
        )
        if path:
            self.installBackend(wheelPath=path)

    def ensureBackend(self):
        if self.useMock() or backend.is_installed():
            return True
        return self.installBackend(prompt=True)

    # -- run ---------------------------------------------------------------

    def onApply(self, *args):
        if not self.ensureBackend():
            return
        inputVolume = self.inputSelector.currentNode()
        outputVolume = self.outputSelector.currentNode()
        if outputVolume is inputVolume and not slicer.util.confirmOkCancelDisplay(
            "The anonymized volume is the input volume: its voxels will be overwritten.\n\n"
            "Continue?",
            windowTitle="RadVeil",
        ):
            return

        # The comparison renders the input; drop a stale one before the input may change.
        self.compareButton.checked = False
        options = self.logic.optionsFromParameterNode(self._parameterNode)
        others = self.checkedOtherSeries()
        steps = ["Finding and anonymizing the face"]
        if options["brainSegment"]:
            steps.append("extracting the brain")
        if others:
            steps.append(f"anonymizing {len(others)} more series")
        self._progressLabel = ", ".join(steps) + "..."
        try:
            result = self.logic.process(
                inputVolume,
                outputVolume,
                regionSegmentation=self.regionSelector.currentNode(),
                otherVolumes=others,
                useMock=self.useMock(),
                runner=self.runWithProgress,
                **options,
            )
        except RadVeilCancelled:
            slicer.util.showStatusMessage("Anonymization cancelled; nothing was changed.", 5000)
            return
        except RadVeilRefusedError as e:
            self.showRefusal(str(e))
            return
        except Exception as e:
            logging.exception("RadVeil failed")
            slicer.util.errorDisplay(f"RadVeil failed:\n{e}", windowTitle="RadVeil")
            return

        # The selectors stay on "Create new", so anonymizing the next scan never
        # overwrites this result.
        self.lastResult = result
        self.showResult(result.report)
        inPlace = result.outputVolume is inputVolume
        slicer.util.setSliceViewerLayers(
            background=result.outputVolume,
            foreground=None if inPlace else inputVolume,
            foregroundOpacity=0.0,
            fit=True,
        )
        if not inPlace:
            slicer.util.showStatusMessage(
                "Tip: drag the slice views' fade slider to compare with the original.", 8000
            )
        if self.reviewAfterRunCheck.checked:
            self.compareButton.checked = True

    def onPreview(self, *args):
        if not self.ensureBackend():
            return
        self.compareButton.checked = False
        options = self.logic.optionsFromParameterNode(self._parameterNode)
        for key in ("verifyEffort", "brainSegment", "auto_threshold"):  # not used by a preview
            options.pop(key, None)
        self._progressLabel = "Finding the face and the region to anonymize..."
        try:
            result = self.logic.previewRegion(
                self.inputSelector.currentNode(),
                regionSegmentation=self.regionSelector.currentNode(),
                useMock=self.useMock(),
                runner=self.runWithProgress,
                **options,
            )
        except RadVeilCancelled:
            slicer.util.showStatusMessage("Preview cancelled.", 5000)
            return
        except RadVeilRefusedError as e:
            self.showRefusal(str(e))
            return
        except Exception as e:
            logging.exception("RadVeil preview failed")
            slicer.util.errorDisplay(f"RadVeil failed:\n{e}", windowTitle="RadVeil")
            return
        self.lastResult = result
        self.showResult(result.report)
        slicer.util.setSliceViewerLayers(background=result.inputVolume, foreground=None, fit=True)
        if self.reviewAfterRunCheck.checked:
            self.compareButton.checked = True

    def runWithProgress(self, func):
        """Run ``func`` in a worker thread while Slicer stays responsive.

        RadVeil releases the GIL, so the UI keeps redrawing. Cancel cannot stop
        the computation midway; it discards the result once the current step ends."""
        state = {}

        def work():
            try:
                state["value"] = func()
            except BaseException as e:  # re-raised in the main thread
                state["error"] = e

        label = getattr(self, "_progressLabel", None) or "Finding and anonymizing the face..."
        progress = slicer.util.createProgressDialog(windowTitle="RadVeil", labelText=label, maximum=0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setWindowModality(qt.Qt.ApplicationModal)
        progress.show()
        thread = threading.Thread(target=work, name="RadVeil", daemon=True)
        start = time.monotonic()
        cancelled = False
        thread.start()
        try:
            while thread.is_alive():
                thread.join(0.05)
                if progress.wasCanceled and not cancelled:
                    cancelled = True
                    progress.setCancelButton(None)
                    progress.show()
                elapsed = int(time.monotonic() - start)
                if cancelled:
                    progress.setLabelText(f"Cancelling... nothing will be changed. ({elapsed} s)")
                else:
                    progress.setLabelText(f"{label} ({elapsed} s)")
                slicer.app.processEvents()
        finally:
            progress.close()
        if cancelled:
            raise RadVeilCancelled()
        if "error" in state:
            raise state["error"]
        return state.get("value")

    # -- results -----------------------------------------------------------

    def _setVerdict(self, level, headline, details):
        r, g, b = LEVEL_COLORS[level]
        self.verdictFrame.setStyleSheet(
            f"QFrame#verdict {{ border-left: 4px solid rgb({r},{g},{b});"
            f" background-color: rgba({r},{g},{b},28); border-radius: 3px; }}"
        )
        rows = [f"<b>{_html(headline)}</b>"]
        for lvl, text in details:
            cr, cg, cb = LEVEL_COLORS[lvl]
            rows.append(f"<span style='color:rgb({cr},{cg},{cb})'>&#9679;</span> {_html(text)}")
        self.verdictLabel.text = "<br>".join(rows)
        self.resultsBox.visible = True
        self.resultsBox.collapsed = False

    def showResult(self, report):
        level, headline, details = conversion.assess(report)
        changed = report.get("voxels_changed_in_slicer")
        if isinstance(changed, int):
            details = details + [(conversion.NOTE, f"{changed:,} voxels changed.")]
        self._setVerdict(level, headline, details)
        preview = bool(report.get("preview"))
        self.compareButton.enabled = True
        self.compareButton.text = "Show region in 3D" if preview else "Compare before / after"
        self.saveReportButton.enabled = not preview

    def showRefusal(self, message):
        self.lastResult = None
        self.compareButton.checked = False
        self._setVerdict(
            conversion.WARNING,
            "Nothing was changed: no face was found.",
            [
                (conversion.NOTE, "Is this a head scan with the face inside the field of view, "
                                  "and not already defaced?"),
                (conversion.NOTE, "If the face is cut by the field of view, enable Advanced > "
                                  "Face cut by the field of view."),
                (conversion.NOTE, "For noisy or dim scans, enable Advanced > Noisy or dim scans."),
                (conversion.NOTE, f"RadVeil: {message}"),
            ],
        )
        self.compareButton.enabled = False
        self.saveReportButton.enabled = False

    def onCompareToggled(self, on):
        if not on:
            self.review.end()
            self.thresholdSlider.enabled = False
            return
        result = self.lastResult
        alive = result is not None and result.inputVolume is not None and result.inputVolume.GetScene()
        if not alive or (not result.preview and not (result.outputVolume and result.outputVolume.GetScene())):
            self.compareButton.checked = False
            return
        with slicer.util.tryWithErrorDisplay("Could not show the comparison.", waitCursor=True):
            if result.preview:
                lo, hi, threshold = self.review.begin(
                    result.inputVolume, None, result.regionSegmentation, result.landmarks, preview=True)
            else:
                lo, hi, threshold = self.review.begin(
                    result.inputVolume if result.inputVolume is not result.outputVolume else None,
                    result.outputVolume,
                    result.regionSegmentation,
                    result.landmarks,
                )
            self.thresholdSlider.blockSignals(True)
            # ctkSliderWidget has no setRange() in Python; minimum first keeps any old range valid.
            self.thresholdSlider.minimum = lo
            self.thresholdSlider.maximum = hi
            self.thresholdSlider.singleStep = max((hi - lo) / 400.0, 1e-6)
            self.thresholdSlider.decimals = 0 if hi - lo > 50 else 3
            self.thresholdSlider.value = threshold
            self.thresholdSlider.blockSignals(False)
            self.thresholdSlider.enabled = True

    def onSaveReport(self, *args):
        result = self.lastResult
        reportJson = result.outputVolume.GetAttribute(REPORT_ATTRIBUTE) if result else None
        if not reportJson:
            return
        path = qt.QFileDialog.getSaveFileName(
            slicer.util.mainWindow(), "Save RadVeil report", "radveil_report.json", "JSON (*.json)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(reportJson)
            slicer.util.showStatusMessage(f"Report saved to {path}", 5000)


def _html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


#
# Before/after review
#


class RadVeilReview:
    """Side-by-side 3D skin-surface renders of the original and the anonymized
    volume (linked cameras, looking at the face), with the anonymized volume
    and the changed region in the slice views. Restores the previous layout
    and rendering settings when ended."""

    LAYOUT_ID = 7781
    BEFORE_TAG, AFTER_TAG = "RadVeilBefore", "RadVeilAfter"
    LAYOUT_XML = """
<layout type="vertical" split="true">
 <item splitSize="600">
  <layout type="horizontal">
   <item><view class="vtkMRMLViewNode" singletontag="RadVeilBefore">
    <property name="viewlabel" action="default">1</property></view></item>
   <item><view class="vtkMRMLViewNode" singletontag="RadVeilAfter">
    <property name="viewlabel" action="default">2</property></view></item>
  </layout>
 </item>
 <item splitSize="400">
  <layout type="horizontal">
   <item><view class="vtkMRMLSliceNode" singletontag="Red">
    <property name="orientation" action="default">Axial</property>
    <property name="viewlabel" action="default">R</property>
    <property name="viewcolor" action="default">#F34A33</property></view></item>
   <item><view class="vtkMRMLSliceNode" singletontag="Yellow">
    <property name="orientation" action="default">Sagittal</property>
    <property name="viewlabel" action="default">Y</property>
    <property name="viewcolor" action="default">#EDD54C</property></view></item>
   <item><view class="vtkMRMLSliceNode" singletontag="Green">
    <property name="orientation" action="default">Coronal</property>
    <property name="viewlabel" action="default">G</property>
    <property name="viewcolor" action="default">#6EB04B</property></view></item>
  </layout>
 </item>
</layout>
"""
    SKIN_RGB = (0.94, 0.80, 0.70)

    def __init__(self):
        self.propertyNode = None
        self.saved = None  # state to restore
        self.lo = self.hi = 0.0

    def forget(self):
        """Drop references without restoring (the scene is being closed)."""
        self.propertyNode = None
        self.saved = None

    def begin(self, inputVolume, outputVolume, regionSegmentation=None, landmarks=None, preview=False):
        """Show the comparison and return ``(lo, hi, threshold)``.

        ``inputVolume`` may be None (in-place run): the 'before' view then
        stays empty. ``landmarks`` (a point list) is shown on the original.
        With ``preview`` there is no output yet: both views show the input,
        the right one with the region that would be anonymized in amber."""
        self.end()
        layoutManager = slicer.app.layoutManager()
        layoutNode = layoutManager.layoutLogic().GetLayoutNode()
        if not layoutNode.IsLayoutDescription(self.LAYOUT_ID):
            layoutNode.AddLayoutDescription(self.LAYOUT_ID, self.LAYOUT_XML)
        self.saved = {"layout": layoutManager.layout, "restore": []}
        layoutManager.setLayout(self.LAYOUT_ID)
        slicer.app.processEvents()

        views = {}
        for tag in (self.BEFORE_TAG, self.AFTER_TAG):
            viewNode = slicer.mrmlScene.GetSingletonNode(tag, "vtkMRMLViewNode")
            if viewNode is None:
                raise RuntimeError("the comparison layout could not be created")
            viewNode.SetBoxVisible(False)
            viewNode.SetAxisLabelsVisible(False)
            viewNode.SetLinkedControl(True)
            views[tag] = viewNode
        before, after = views[self.BEFORE_TAG], views[self.AFTER_TAG]

        reference = inputVolume or outputVolume
        self.lo, self.hi, threshold = conversion.surface_threshold(slicer.util.arrayFromVolume(reference))
        self.propertyNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLVolumePropertyNode", slicer.mrmlScene.GenerateUniqueName("RadVeil skin surface")
        )
        self.propertyNode.SetHideFromEditors(True)
        self.propertyNode.SetSaveWithScene(False)
        self._configureProperty(threshold)

        if preview:
            self._showVolume(inputVolume, [before, after])
            titles = ("Detected face", "Region to anonymize")
        else:
            if inputVolume is not None:
                self._showVolume(inputVolume, [before])
            self._showVolume(outputVolume, [after])
            titles = ("Original" if inputVolume else "Original (overwritten)", "Anonymized")

        sliceViewIDs = [n.GetID() for n in slicer.util.getNodesByClass("vtkMRMLSliceNode")]
        if regionSegmentation is not None and regionSegmentation.GetDisplayNode():
            display = regionSegmentation.GetDisplayNode()
            self._rememberDisplay(display)
            display.SetVisibility2DFill(True)
            display.SetOpacity2DFill(0.2)
            display.SetVisibility2DOutline(True)
            if preview:
                # The region as an amber shell on the right; slices keep the outline.
                display.SetVisibility3D(True)
                display.SetOpacity3D(0.65)
                self._restrictTo(display, [after.GetID()] + sliceViewIDs)
            else:
                display.SetVisibility3D(False)  # it would hide the anonymized surface
        if landmarks is not None and landmarks.GetScene() and landmarks.GetDisplayNode():
            display = landmarks.GetDisplayNode()
            self._rememberDisplay(display)
            display.SetVisibility(True)
            self._restrictTo(display, [(before if inputVolume is not None else after).GetID()])

        slicer.app.processEvents()
        for viewNode, title in zip((before, after), titles):
            widget = layoutManager.viewWidget(viewNode)
            if widget:
                view = widget.threeDView()
                view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperLeft, title)
                view.cornerAnnotation().GetTextProperty().SetColor(1.0, 1.0, 1.0)
                view.resetFocalPoint()
                # lookFromAxis replaces the deprecated lookFromViewAxis (Slicer 5.8); keep 5.6 working.
                lookFrom = view.lookFromAxis if hasattr(view, "lookFromAxis") else view.lookFromViewAxis
                lookFrom(ctk.ctkAxesWidget.Anterior)
                view.forceRender()
        return self.lo, self.hi, threshold

    def _rememberDisplay(self, display):
        """Record a display node's view restriction and visibilities, to restore on end()."""
        viewIDs = [display.GetNthViewNodeID(i) for i in range(display.GetNumberOfViewNodeIDs())]
        visible, visible3D = display.GetVisibility(), display.GetVisibility3D()

        def restore():
            if display.GetScene() is None:
                return
            display.RemoveAllViewNodeIDs()
            for viewID in viewIDs:
                display.AddViewNodeID(viewID)
            display.SetVisibility(visible)
            display.SetVisibility3D(visible3D)

        self.saved["restore"].append(restore)

    @staticmethod
    def _restrictTo(display, viewIDs):
        display.RemoveAllViewNodeIDs()
        for viewID in viewIDs:
            display.AddViewNodeID(viewID)

    def _showVolume(self, volume, viewNodes):
        vrLogic = slicer.modules.volumerendering.logic()
        display = vrLogic.GetFirstVolumeRenderingDisplayNode(volume)
        created = display is None
        if created:
            display = vrLogic.CreateDefaultVolumeRenderingNodes(volume)
            display.SetVisibility(False)
        self._rememberDisplay(display)
        previousProperty = display.GetVolumePropertyNodeID()
        self.saved["restore"].append(
            lambda: display.GetScene() and display.SetAndObserveVolumePropertyNodeID(previousProperty))
        display.SetAndObserveVolumePropertyNodeID(self.propertyNode.GetID())
        self._restrictTo(display, [v.GetID() for v in viewNodes])
        display.SetVisibility(True)

    def _configureProperty(self, threshold):
        span = self.hi - self.lo
        lowest, highest = self.lo - 10.0 * span, self.hi + 10.0 * span
        color = vtk.vtkColorTransferFunction()
        color.AddRGBPoint(lowest, *self.SKIN_RGB)
        color.AddRGBPoint(highest, *self.SKIN_RGB)
        gradient = vtk.vtkPiecewiseFunction()
        gradient.AddPoint(0.0, 1.0)
        gradient.AddPoint(max(span, 1.0) * 100.0, 1.0)
        self.propertyNode.SetColor(color)
        self.propertyNode.SetGradientOpacity(gradient)
        prop = self.propertyNode.GetVolumeProperty()
        prop.SetInterpolationTypeToLinear()
        prop.ShadeOn()
        prop.SetAmbient(0.3)
        prop.SetDiffuse(0.75)
        prop.SetSpecular(0.15)
        prop.SetSpecularPower(12.0)
        self.setThreshold(threshold)

    def setThreshold(self, threshold):
        if self.propertyNode is None:
            return
        span = max(self.hi - self.lo, 1e-6)
        edge = 0.02 * span
        opacity = vtk.vtkPiecewiseFunction()
        opacity.AddPoint(self.lo - 10.0 * span, 0.0)
        opacity.AddPoint(threshold, 0.0)
        opacity.AddPoint(threshold + edge, 1.0)
        opacity.AddPoint(self.hi + 10.0 * span, 1.0)
        self.propertyNode.SetScalarOpacity(opacity)

    def end(self):
        if not self.saved:
            return
        for restore in reversed(self.saved["restore"]):
            restore()
        if self.propertyNode is not None and self.propertyNode.GetScene():
            slicer.mrmlScene.RemoveNode(self.propertyNode)
        self.propertyNode = None
        layoutManager = slicer.app.layoutManager()
        if layoutManager and layoutManager.layout == self.LAYOUT_ID:
            layoutManager.setLayout(self.saved["layout"])
        self.saved = None


#
# Logic
#


class RadVeilRefusedError(RuntimeError):
    """RadVeil found no plausible face and modified nothing."""


class RadVeilCancelled(Exception):
    """The user cancelled; nothing was modified."""


class RadVeilResult:
    """What a run produced. ``otherSeries`` is a list of
    ``(sourceVolume, anonymizedVolume or None, seriesReport)``."""

    def __init__(self, report, inputVolume, outputVolume, regionSegmentation,
                 landmarks=None, otherSeries=(), preview=False):
        self.report = report
        self.inputVolume = inputVolume
        self.outputVolume = outputVolume
        self.regionSegmentation = regionSegmentation
        self.landmarks = landmarks
        self.otherSeries = list(otherSeries)
        self.preview = preview


# RadVeil's palette (its website and figures): mask amber, brain blue, accent mint.
REGION_COLOR = (0xE3 / 255, 0xAA / 255, 0x4B / 255)
BRAIN_COLOR = (0x60 / 255, 0xA5 / 255, 0xFA / 255)
LANDMARK_COLOR = (0x4F / 255, 0xD1 / 255, 0xBD / 255)
RECHECK_YAWS = (-20.0, 0.0, 20.0)


class RadVeilLogic(ScriptedLoadableModuleLogic):
    def setDefaultParameters(self, parameterNode):
        defaults = {
            "Region": "face",
            "Method": "adaptive",
            "EarMethod": "",
            "Verify": "balanced",
            "SkinDepth": "",
            "ReviewAfterRun": "true",
            "BrainSegment": "false",
            "ShowLandmarks": "true",
            "UseMock": "false",
        }
        defaults.update({name: "false" for name in FLAG_NAMES})
        existing = set(parameterNode.GetParameterNames())
        for key, value in defaults.items():
            if key not in existing:
                parameterNode.SetParameter(key, value)

    @staticmethod
    def optionsFromParameterNode(p):
        skin = p.GetParameter("SkinDepth")
        options = {
            "region": p.GetParameter("Region") or "face",
            "mode": p.GetParameter("Method") or "adaptive",
            "earMode": p.GetParameter("EarMethod") or None,
            "verifyEffort": p.GetParameter("Verify") or "balanced",
            "skinDepthMm": float(skin) if skin else None,
            "brainSegment": p.GetParameter("BrainSegment") == "true",
            "showLandmarks": p.GetParameter("ShowLandmarks") != "false",
        }
        for name in FLAG_NAMES:
            options[name] = p.GetParameter(name) == "true"
        return options

    @staticmethod
    def ijkToWorldMatrix(volumeNode):
        m = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASMatrix(m)
        ijkToRas = slicer.util.arrayFromVTKMatrix(m)
        parentToWorld = None
        transformNode = volumeNode.GetParentTransformNode()
        if transformNode is not None:
            if not transformNode.IsTransformToWorldLinear():
                raise ValueError(
                    f"'{volumeNode.GetName()}' is under a non-linear transform. Harden the "
                    "transform (Data module) before anonymizing."
                )
            t = vtk.vtkMatrix4x4()
            transformNode.GetMatrixTransformToWorld(t)
            parentToWorld = slicer.util.arrayFromVTKMatrix(t)
        return conversion.ijk_to_world_affine(ijkToRas, parentToWorld)

    @staticmethod
    def _checkVolume(volume, what="input"):
        if volume is None:
            raise ValueError(f"an {what} volume is required")
        if volume.IsA("vtkMRMLLabelMapVolumeNode"):
            raise ValueError(f"'{volume.GetName()}' is a labelmap; select an image volume.")
        image = volume.GetImageData()
        if image is None or image.GetNumberOfScalarComponents() != 1:
            raise ValueError(f"'{volume.GetName()}' must be a single-component (grayscale) volume.")

    def _snapshot(self, rv, volume):
        """(original Slicer array, radveil Volume) for a volume node."""
        original = np.array(slicer.util.arrayFromVolume(volume))
        vol = rv.Volume.from_array(conversion.to_radveil_array(original), self.ijkToWorldMatrix(volume))
        return original, vol

    @staticmethod
    def _defaceOptions(region, mode, earMode, skinDepthMm, flags):
        """Anonymization keywords shared by every radveil entry point."""
        options = {"mode": mode, "region": region}
        if earMode and "ears" in region:
            options["ear_mode"] = earMode
        if skinDepthMm:
            options["skin_depth_mm"] = float(skinDepthMm)
        for key in ("level_face", "spare_air"):
            if flags.get(key):
                options[key] = True
        return options

    def process(
        self,
        inputVolume,
        outputVolume=None,
        region="face",
        mode="adaptive",
        earMode=None,
        verifyEffort="balanced",
        skinDepthMm=None,
        regionSegmentation=None,
        createRegionSegmentation=True,
        brainSegment=False,
        blockFallback=False,
        showLandmarks=True,
        otherVolumes=(),
        useMock=False,
        runner=None,
        **flags,
    ):
        """Anonymize ``inputVolume``.

        ``outputVolume`` may be None (a new volume is created) or the input
        itself (overwritten). ``regionSegmentation`` receives the changed
        region (created if None and ``createRegionSegmentation``); with
        ``brainSegment`` it also gets a SynthStrip brain segment.
        ``otherVolumes`` are series aligned with the input (same session or
        registered): they are anonymized with the face found on the input,
        then re-checked with the face detector. ``flags`` are RadVeil booleans
        (brain_guard, brain_check, level_face, partial_face, auto_threshold,
        spare_air). The chosen method is applied exactly as asked, also when the
        face detector still finds a face (the verdict is then red);
        ``blockFallback=True`` lets RadVeil switch to an opaque block instead
        (its escalate_to_block, meant for unattended batch runs). ``runner(func)`` executes the computation (the widget runs
        it in a thread with a progress dialog).

        Returns a :class:`RadVeilResult`. Raises RadVeilRefusedError when no
        plausible face is found; nothing is modified in that case."""
        self._checkVolume(inputVolume)
        unknown = set(flags) - set(FLAG_NAMES)
        if unknown:
            raise TypeError(f"unknown option(s): {', '.join(sorted(unknown))}")
        others = [v for v in otherVolumes if v is not None and v is not inputVolume and v is not outputVolume]
        for other in others:
            self._checkVolume(other, "other")

        rv = backend.load(use_mock=useMock)
        original, vol = self._snapshot(rv, inputVolume)
        otherInputs = [(node,) + self._snapshot(rv, node) for node in others]
        brainVol = rv.Volume.from_array(conversion.to_radveil_array(original), self.ijkToWorldMatrix(inputVolume)) \
            if brainSegment else None

        deface = self._defaceOptions(region, mode, earMode, skinDepthMm, flags)
        kwargs = dict(
            deface,
            verify_effort=verifyEffort,
            return_mask=True,
            **{k: bool(v) for k, v in flags.items() if k not in ("level_face", "spare_air")},
        )
        if not blockFallback:
            kwargs["escalate_to_block"] = False

        def compute():
            report = rv.deface_volume(vol, **kwargs)
            brain = brainVol.deskull(strip=False) if brainVol is not None else None
            series = [self._propagate(rv, node, svol, report.get("landmarks_3d"), deface)
                      for node, _, svol in otherInputs]
            return report, brain, series

        logging.info(f"RadVeil: anonymizing with {kwargs}")
        try:
            report, brain, series = runner(compute) if runner else compute()
        except RuntimeError as e:
            # deface_volume raises RuntimeError when no validated face is
            # found; the volume is untouched in that case.
            raise RadVeilRefusedError(str(e)) from e

        mask = report.pop("mask")
        report.setdefault("mode", mode)  # the verdict explains an escalation by the chosen method
        if not blockFallback:
            report["block_fallback"] = False
        merged, nChanged = conversion.merge_back(original, vol.data(), mask)
        report["voxels_changed_in_slicer"] = nChanged

        if outputVolume is None:
            outputVolume = self._newNextTo("vtkMRMLScalarVolumeNode", "Anonymized volume", inputVolume)
        self._writeOutputVolume(inputVolume, outputVolume, merged)

        segments = [("Changed region", mask, REGION_COLOR)]
        if brain is not None:
            segments.append(("Brain", brain["mask"], BRAIN_COLOR))
            report["brain_segment_ml"] = brain.get("brain_volume_ml")
        if regionSegmentation is None and createRegionSegmentation:
            regionSegmentation = self._newNextTo("vtkMRMLSegmentationNode", "Anonymized region", inputVolume)
        if regionSegmentation is not None:
            self._writeSegments(inputVolume, regionSegmentation, segments)

        otherResults = []
        for (node, sourceArray, svol), seriesReport in zip(otherInputs, series):
            out = None
            seriesMask = seriesReport.pop("mask", None)
            if seriesMask is not None:
                merged, n = conversion.merge_back(sourceArray, svol.data(), seriesMask)
                seriesReport["voxels_changed_in_slicer"] = n
                out = self._newNextTo("vtkMRMLScalarVolumeNode", "Anonymized volume", node)
                self._writeOutputVolume(node, out, merged)
                out.SetAttribute(REPORT_ATTRIBUTE, conversion.report_to_json(
                    seriesReport, slicer_extension="SlicerRadVeil", propagated_from_landmarks=True,
                    disclaimer=conversion.DISCLAIMER,
                    radveil_version=getattr(rv, "__version__", "unknown"), parameters=deface))
            seriesReport["series_name"] = node.GetName()
            otherResults.append((node, out, seriesReport))
        report["other_series"] = [r for _, _, r in otherResults]

        landmarks = self._writeLandmarks(report.get("landmarks_3d")) if showLandmarks else None

        # The report deliberately carries no node or file names: they often
        # contain patient names (series_name is dropped by report_to_json).
        reportJson = conversion.report_to_json(
            report,
            slicer_extension="SlicerRadVeil",
            disclaimer=conversion.DISCLAIMER,
            radveil_version=getattr(rv, "__version__", "unknown"),
            backend="mock" if backend.is_mock(rv) else "radveil",
            parameters=kwargs,
        )
        outputVolume.SetAttribute(REPORT_ATTRIBUTE, reportJson)
        return RadVeilResult(report, inputVolume, outputVolume, regionSegmentation, landmarks, otherResults)

    @staticmethod
    def _propagate(rv, node, svol, landmarks3d, deface):
        """Anonymize another series with the input's landmarks (world mm) and
        re-run the face detector on it. Runs in the worker thread."""
        result = {"views_checked": 0, "faces_found": 0}
        if not landmarks3d or sum(p is not None for p in landmarks3d) < 3:
            result["error"] = "no face landmarks available from the input"
            return result
        try:
            rep = svol.deface(landmarks3d, return_mask=True, **deface)
        except (ValueError, RuntimeError) as e:
            result["error"] = str(e)
            return result
        if not np.asarray(rep.get("mask", 0)).any():
            # Nothing to write: no output volume is created for this series.
            result["error"] = "the face region does not overlap this series (not aligned with the input?)"
            return result
        result.update({k: v for k, v in rep.items() if k in ("mask", "voxels_changed", "mock")})
        for yaw in RECHECK_YAWS:
            try:
                view = svol.render(yaw_deg=yaw)
                found = rv.detect_landmarks(view["rgb"], try_rotations=True)
            except Exception as e:  # a render failure is a finding, not a crash
                result["recheck_error"] = str(e)
                break
            result["views_checked"] += 1
            result["faces_found"] += int(found is not None)
        return result

    def previewRegion(
        self,
        inputVolume,
        region="face",
        mode="adaptive",
        earMode=None,
        skinDepthMm=None,
        regionSegmentation=None,
        showLandmarks=True,
        useMock=False,
        runner=None,
        **flags,
    ):
        """Show where :meth:`process` would anonymize, changing nothing.

        Uses radveil's ``anonymization_mask``: detection, validation and the
        safety refusals run as in a real run; nothing is rewritten or
        verified. Returns a :class:`RadVeilResult` with ``preview=True`` and
        no output volume."""
        self._checkVolume(inputVolume)
        rv = backend.load(use_mock=useMock)
        _, vol = self._snapshot(rv, inputVolume)
        options = self._defaceOptions(region, mode, earMode, skinDepthMm, flags)
        for key in ("brain_guard", "brain_check", "partial_face"):
            if flags.get(key):
                options[key] = True

        def compute():
            return rv.anonymization_mask(vol, **options)

        try:
            report = runner(compute) if runner else compute()
        except RuntimeError as e:
            raise RadVeilRefusedError(str(e)) from e
        mask = report.pop("mask")
        report["preview"] = True
        report["voxels_in_region"] = int(np.count_nonzero(mask))
        if regionSegmentation is None:
            regionSegmentation = self._newNextTo("vtkMRMLSegmentationNode", "Anonymized region", inputVolume)
        self._writeSegments(inputVolume, regionSegmentation, [("Region preview", mask, REGION_COLOR)])
        landmarks = self._writeLandmarks(report.get("landmarks_3d")) if showLandmarks else None
        return RadVeilResult(report, inputVolume, None, regionSegmentation, landmarks, preview=True)

    def _newNextTo(self, className, baseName, reference):
        node = slicer.mrmlScene.AddNewNodeByClass(className, slicer.mrmlScene.GenerateUniqueName(baseName))
        self._placeNextTo(node, reference)
        return node

    @staticmethod
    def _placeNextTo(node, reference):
        """Put ``node`` in the same subject hierarchy folder/study as ``reference``."""
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        if sh is None:
            return
        refItem = sh.GetItemByDataNode(reference)
        item = sh.GetItemByDataNode(node)
        if refItem and item:
            sh.SetItemParent(item, sh.GetItemParent(refItem))

    @staticmethod
    def _writeOutputVolume(inputVolume, outputVolume, merged):
        if outputVolume is not inputVolume:
            outputVolume.CopyOrientation(inputVolume)
            outputVolume.SetAndObserveTransformNodeID(inputVolume.GetTransformNodeID())
        slicer.util.updateVolumeFromArray(outputVolume, merged)
        if outputVolume is not inputVolume:
            inDisplay = inputVolume.GetDisplayNode()
            outputVolume.CreateDefaultDisplayNodes()
            outDisplay = outputVolume.GetDisplayNode()
            if inDisplay and outDisplay:
                outDisplay.SetAndObserveColorNodeID(inDisplay.GetColorNodeID())
                outDisplay.SetAutoWindowLevel(False)
                outDisplay.SetWindowLevel(inDisplay.GetWindow(), inDisplay.GetLevel())

    @staticmethod
    def _writeSegments(referenceVolume, segmentationNode, segments):
        """Replace the segments of ``segmentationNode`` with ``(name, mask_ijk, rgb)``."""
        segmentation = segmentationNode.GetSegmentation()
        segmentation.RemoveAllSegments()
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(referenceVolume)
        segmentationNode.SetAndObserveTransformNodeID(referenceVolume.GetTransformNodeID())
        segmentationNode.CreateDefaultDisplayNodes()
        for name, mask, color in segments:
            segmentId = segmentation.AddEmptySegment(name, name, color)
            maskKji = conversion.mask_to_kji(mask)
            if maskKji.any():
                slicer.util.updateSegmentBinaryLabelmapFromArray(
                    maskKji, segmentationNode, segmentId, referenceVolume)
        display = segmentationNode.GetDisplayNode()
        if display:
            display.SetOpacity2DFill(0.2)
            display.SetVisibility2DOutline(True)
            display.SetVisibility3D(False)  # would hide the anonymized surface

    @staticmethod
    def _writeLandmarks(landmarks3d):
        """Detected face landmarks (world RAS mm) as a locked point list, or None."""
        points = [p for p in (landmarks3d or []) if p is not None]
        if not points:
            return None
        node = slicer.mrmlScene.GetFirstNodeByName("Detected face landmarks")
        if node is None or not node.IsA("vtkMRMLMarkupsFiducialNode"):
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Detected face landmarks")
        slicer.util.updateMarkupsControlPointsFromArray(node, np.asarray(points, dtype=float), world=True)
        node.SetLocked(True)
        node.CreateDefaultDisplayNodes()
        display = node.GetDisplayNode()
        display.SetPointLabelsVisibility(False)
        display.SetSelectedColor(*LANDMARK_COLOR)
        display.SetColor(*LANDMARK_COLOR)
        display.SetUseGlyphScale(False)
        display.SetGlyphSize(2.5)  # mm: small dots that do not hide the face
        display.SetVisibility2D(False)
        return node


#
# Test
#


def makePhantom(shape=(64, 72, 80), dtype=np.int16):
    """Synthetic head-like phantom in [k, j, i] order: an ellipsoid 'head'
    with a bump in front (+A) as a 'nose'. Values are integers."""
    nk, nj, ni = shape
    k, j, i = np.meshgrid(np.arange(nk), np.arange(nj), np.arange(ni), indexing="ij")
    ck, cj, ci = nk / 2, nj / 2, ni / 2
    head = ((i - ci) / (ni * 0.35)) ** 2 + ((j - cj) / (nj * 0.38)) ** 2 + ((k - ck) / (nk * 0.4)) ** 2 <= 1
    nose = ((i - ci) / 4.0) ** 2 + ((j - (cj + nj * 0.40)) / 5.0) ** 2 + ((k - ck) / 6.0) ** 2 <= 1
    rng = np.random.default_rng(0)
    arr = np.where(head | nose, 800, 20) + rng.integers(0, 40, size=shape)
    return arr.astype(dtype)


class RadVeilTest(ScriptedLoadableModuleTest):
    """Self-tests. They use the mock backend, so no network or real package is needed.
    Set RADVEIL_SLICER_TEST_REAL=1 to also run the real package on MRHead."""

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        for test in (
            self.test_MockNewOutput,
            self.test_MockInPlaceWithTransform,
            self.test_RejectsLabelmap,
            self.test_Review,
            self.test_WidgetEndToEnd,
            self.test_PreviewBrainSeriesLandmarks,
        ):
            self.setUp()
            test()
        if os.environ.get("RADVEIL_SLICER_TEST_REAL") == "1":
            self.setUp()
            self.test_RealMRHead()

    def _phantomNode(self, name="phantom"):
        arr = makePhantom()
        node = slicer.util.addVolumeFromArray(arr, name=name)
        node.SetSpacing(1.0, 1.0, 1.2)
        node.SetOrigin(-30.0, -40.0, -35.0)
        return node, arr

    def test_MockNewOutput(self):
        self.delayDisplay("Mock run into a new volume")
        inputVolume, original = self._phantomNode()
        result = RadVeilLogic().process(
            inputVolume, None, region="face+ears", mode="cut", useMock=True, brain_check=True,
        )
        self.assertTrue(result.report["mock"])
        outputVolume, seg = result.outputVolume, result.regionSegmentation
        self.assertIsNotNone(outputVolume)
        self.assertNotIn("phantom", outputVolume.GetName())
        processed = slicer.util.arrayFromVolume(outputVolume)
        self.assertEqual(processed.dtype, original.dtype)
        self.assertEqual(processed.shape, original.shape)
        np.testing.assert_array_equal(slicer.util.arrayFromVolume(inputVolume), original)
        self.assertEqual(outputVolume.GetSpacing(), inputVolume.GetSpacing())
        self.assertEqual(seg.GetSegmentation().GetNumberOfSegments(), 1)
        segArr = slicer.util.arrayFromSegmentBinaryLabelmap(
            seg, seg.GetSegmentation().GetNthSegmentID(0), inputVolume)
        changed = processed != original
        self.assertTrue(changed.any())
        self.assertFalse((changed & (segArr == 0)).any(), "voxel changed outside the region")
        stored = json.loads(outputVolume.GetAttribute(REPORT_ATTRIBUTE))
        self.assertEqual(stored["backend"], "mock")
        self.assertNotIn("phantom", json.dumps(stored))
        self.delayDisplay("Mock run into a new volume passed")

    def test_MockInPlaceWithTransform(self):
        self.delayDisplay("Mock in-place run under a linear transform")
        inputVolume, original = self._phantomNode()
        transform = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode")
        m = vtk.vtkMatrix4x4()
        m.SetElement(0, 3, 10.0)
        transform.SetMatrixTransformToParent(m)
        inputVolume.SetAndObserveTransformNodeID(transform.GetID())
        result = RadVeilLogic().process(inputVolume, inputVolume, mode="blur", useMock=True)
        self.assertIs(result.outputVolume, inputVolume)
        self.assertTrue((slicer.util.arrayFromVolume(inputVolume) != original).any())
        self.delayDisplay("Mock in-place run passed")

    def test_RejectsLabelmap(self):
        labelmap = slicer.util.addVolumeFromArray(
            np.zeros((8, 8, 8), np.uint8), nodeClassName="vtkMRMLLabelMapVolumeNode")
        with self.assertRaises(ValueError):
            RadVeilLogic().process(labelmap, None, useMock=True)

    def test_Review(self):
        self.delayDisplay("Before/after comparison")
        inputVolume, _ = self._phantomNode()
        result = RadVeilLogic().process(inputVolume, None, useMock=True)
        layoutManager = slicer.app.layoutManager()
        previousLayout = layoutManager.layout
        review = RadVeilReview()
        lo, hi, threshold = review.begin(inputVolume, result.outputVolume, result.regionSegmentation)
        self.assertTrue(lo < threshold < hi)
        self.assertEqual(layoutManager.layout, RadVeilReview.LAYOUT_ID)
        review.setThreshold(hi * 0.5)
        self.delayDisplay("Comparison shown")
        review.end()
        self.assertEqual(layoutManager.layout, previousLayout)
        self.assertIsNone(review.propertyNode)
        self.delayDisplay("Comparison passed")

    def test_WidgetEndToEnd(self):
        """Drive the real panel: run, result box, comparison layout, restore."""
        self.delayDisplay("Module panel end to end (mock backend)")
        previousMock = os.environ.get("RADVEIL_SLICER_MOCK")
        os.environ["RADVEIL_SLICER_MOCK"] = "1"
        try:
            inputVolume, original = self._phantomNode()
            layoutManager = slicer.app.layoutManager()
            previousLayout = layoutManager.layout
            slicer.util.selectModule("RadVeil")
            widget = slicer.modules.radveil.widgetRepresentation().self()
            widget.updateBackendState()
            self.assertTrue(widget.installBanner.isHidden())
            self.assertIn("mock", widget.applyButton.text)
            widget.inputSelector.setCurrentNode(inputVolume)
            widget.outputSelector.setCurrentNode(None)
            widget.regionSelector.setCurrentNode(None)
            widget.reviewAfterRunCheck.checked = True
            widget.onApply()

            result = widget.lastResult
            self.assertIsNotNone(result)
            self.assertIsNot(result.outputVolume, inputVolume)
            np.testing.assert_array_equal(slicer.util.arrayFromVolume(inputVolume), original)
            self.assertFalse(widget.resultsBox.isHidden())
            self.assertIn("mock", widget.verdictLabel.text)
            self.assertTrue(widget.compareButton.checked)
            self.assertEqual(layoutManager.layout, RadVeilReview.LAYOUT_ID)
            self.assertTrue(widget.thresholdSlider.enabled)
            widget.thresholdSlider.value = widget.thresholdSlider.maximum * 0.5
            self.delayDisplay("Comparison layout shown")

            widget.compareButton.checked = False
            self.assertEqual(layoutManager.layout, previousLayout)
            # Selectors stay on "create new": a second run must not overwrite the first.
            self.assertIsNone(widget.outputSelector.currentNode())
            widget.reviewAfterRunCheck.checked = False
            widget.onApply()
            self.assertIsNot(widget.lastResult.outputVolume, result.outputVolume)

            # A faceless volume is refused and nothing is created.
            empty = slicer.util.addVolumeFromArray(np.zeros((16, 16, 16), np.int16), name="empty")
            nVolumes = len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"))
            widget.inputSelector.setCurrentNode(empty)
            widget.onApply()
            self.assertIn("Nothing was changed", widget.verdictLabel.text)
            self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")), nVolumes)
        finally:
            if previousMock is None:
                os.environ.pop("RADVEIL_SLICER_MOCK", None)
            else:
                os.environ["RADVEIL_SLICER_MOCK"] = previousMock
        self.delayDisplay("Module panel end to end passed")

    def test_PreviewBrainSeriesLandmarks(self):
        self.delayDisplay("Preview, brain segment, other series, landmarks")
        logic = RadVeilLogic()
        inputVolume, original = self._phantomNode("t1")
        nVolumes = len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"))

        preview = logic.previewRegion(inputVolume, useMock=True, region="face+ears", skinDepthMm=5.0)
        self.assertTrue(preview.preview)
        self.assertIsNone(preview.outputVolume)
        self.assertEqual(len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")), nVolumes)
        np.testing.assert_array_equal(slicer.util.arrayFromVolume(inputVolume), original)
        segmentation = preview.regionSegmentation.GetSegmentation()
        self.assertEqual(segmentation.GetNthSegment(0).GetName(), "Region preview")
        self.assertEqual(preview.landmarks.GetNumberOfControlPoints(), 68)

        # An aligned second series and one that is far away (not aligned).
        flair, _ = self._phantomNode("flair")
        far, _ = self._phantomNode("far")
        far.SetOrigin(500.0, 0.0, 0.0)
        result = logic.process(
            inputVolume, None, useMock=True, brainSegment=True, otherVolumes=[flair, far, inputVolume])
        names = [result.regionSegmentation.GetSegmentation().GetNthSegment(i).GetName()
                 for i in range(result.regionSegmentation.GetSegmentation().GetNumberOfSegments())]
        self.assertEqual(names, ["Changed region", "Brain"])
        series = {source.GetName(): (out, rep) for source, out, rep in result.otherSeries}
        self.assertEqual(set(series), {"flair", "far"})
        self.assertIsNotNone(series["flair"][0])
        self.assertTrue(series["flair"][1]["voxels_changed_in_slicer"] > 0)
        self.assertIsNone(series["far"][0])
        self.assertIn("error", series["far"][1])
        self.assertNotIn("flair", result.outputVolume.GetAttribute(REPORT_ATTRIBUTE))

        review = RadVeilReview()
        review.begin(inputVolume, result.outputVolume, result.regionSegmentation, result.landmarks)
        self.delayDisplay("Comparison with landmarks")
        review.end()
        review.begin(inputVolume, None, preview.regionSegmentation, preview.landmarks, preview=True)
        self.delayDisplay("Preview comparison")
        review.end()
        self.delayDisplay("Preview, brain segment, other series, landmarks passed")

    def test_RealMRHead(self):
        import SampleData

        self.delayDisplay("Real radveil on MRHead")
        inputVolume = SampleData.downloadSample("MRHead")
        logic = RadVeilLogic()
        preview = logic.previewRegion(inputVolume, region="face+ears")
        self.assertTrue(preview.report["voxels_in_region"] > 0)
        self.assertTrue(preview.landmarks.GetNumberOfControlPoints() >= 5)
        result = logic.process(
            inputVolume, None, region="face+ears", mode="adaptive", earMode="cut",
            brainSegment=True, brain_check=True)
        self.assertEqual(result.report.get("residual_detections"), 0)
        self.assertEqual(result.report["brain"]["voxels_modified"], 0)
        self.assertTrue(900 < result.report["brain_segment_ml"] < 2000)
        level, headline, details = conversion.assess(result.report)
        logging.info(f"RadVeil verdict: {level}: {headline} {details}")
        self.assertIn(level, (conversion.OK, conversion.NOTE, conversion.WARNING))
        self.delayDisplay("Real radveil on MRHead passed")
