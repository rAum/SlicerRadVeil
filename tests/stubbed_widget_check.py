"""Drives the RadVeil widget (setup, run, cancel, refusal, install paths)
against stubbed Qt/Slicer modules. Run by test_widget_stubbed.py in a
separate process; argv[1] is the RadVeil module folder."""
import sys, json
import numpy as np
from unittest import mock
M = mock.MagicMock
for name in ["qt", "ctk", "vtk", "slicer", "slicer.ScriptedLoadableModule", "slicer.util"]:
    sys.modules[name] = M(name=name)

class FakeCombo:
    def __init__(s, *a): s.items, s.currentIndex, s.enabled, s.toolTip = [], 0, True, ""
    def addItem(s, label, data): s.items.append([label, data, ""])
    def setItemData(s, i, v, role): s.items[i][2] = v
    def itemData(s, i, role=None): return s.items[i][2] if role is not None else s.items[i][1]
    def findData(s, v): return next((i for i, it in enumerate(s.items) if it[1] == v), -1)
    def setCurrentIndex(s, i): s.currentIndex = i
    def connect(s, *a): pass
class FakeCheck:
    def __init__(s, *a): s.checked, s.toolTip, s.enabled, s.visible = False, "", True, True
    def connect(s, *a): pass
qt = sys.modules["qt"]
qt.QComboBox = FakeCombo
qt.QCheckBox = FakeCheck
qt.QRadioButton = FakeCheck

class Base:
    def setup(self): pass
    def getParameterNode(self): return None
    def __init__(self, *a, **k): pass
slm = sys.modules["slicer.ScriptedLoadableModule"]
slm.ScriptedLoadableModule = slm.ScriptedLoadableModuleWidget = slm.ScriptedLoadableModuleLogic = slm.ScriptedLoadableModuleTest = Base
sys.modules["slicer.util"].VTKObservationMixin = type("Mix", (), {"__init__": lambda s: None, "addObserver": lambda *a: None, "removeObserver": lambda *a: None, "removeObservers": lambda *a: None})

class Node:
    def __init__(s, name, arr=None, mat=None, cls="vtkMRMLScalarVolumeNode"):
        s.name, s.arr, s.mat, s.cls, s.attrs = name, arr, mat, cls, {}
    def IsA(s, c): return c == s.cls
    def GetImageData(s):
        im = M(); im.GetNumberOfScalarComponents.return_value = 1; return im
    def GetName(s): return s.name
    def GetParentTransformNode(s): return None
    def GetTransformNodeID(s): return None
    def SetAttribute(s, k, v): s.attrs[k] = v
    def GetAttribute(s, k): return s.attrs.get(k)
    def CopyOrientation(s, o): s.mat = o.mat
    def GetScene(s): return True
    def GetSegmentation(s):
        seg = M(); seg.GetNumberOfSegments.return_value = 1; return seg
    def __getattr__(s, k): return M()
created = []
slicer = sys.modules["slicer"]
def addNew(cls, name):
    n = Node(name, cls=cls); created.append(n); return n
slicer.mrmlScene.AddNewNodeByClass.side_effect = addNew
slicer.qMRMLNodeComboBox.side_effect = lambda *a: M()
for _n in ("QPushButton","QLabel","QFrame","QHBoxLayout","QVBoxLayout","QFormLayout","QButtonGroup"): setattr(sys.modules["qt"], _n, mock.Mock(side_effect=lambda *a, **k: M()))
sys.modules["ctk"].ctkCollapsibleButton.side_effect = lambda *a: M()
def _slider(*a):
    s = M()
    del s.setRange  # not wrapped for Python on ctkSliderWidget (Slicer 5.8)
    return s
sys.modules["ctk"].ctkSliderWidget.side_effect = _slider
slicer.mrmlScene.GenerateUniqueName.side_effect = lambda n: n + "_1"
slicer.util.arrayFromVolume.side_effect = lambda v: v.arr
def upd(v, a): v.arr = a
slicer.util.updateVolumeFromArray.side_effect = upd
slicer.util.arrayFromVTKMatrix.side_effect = lambda m: m.mat
slicer.util.settingsValue.return_value = False
slicer.util.confirmOkCancelDisplay.return_value = True
dialogs = []
def mkprog(**kw):
    p = M(); p.wasCanceled = False; dialogs.append(p); return p
slicer.util.createProgressDialog.side_effect = mkprog
errors = []
slicer.util.errorDisplay.side_effect = lambda *a, **k: errors.append(a)

sys.path.insert(0, sys.argv[1])
import RadVeil
import vtk
vtk.vtkMatrix4x4.return_value = M()
RadVeil.RadVeilLogic.ijkToWorldMatrix = staticmethod(lambda v: np.diag([1, 1, 1.2, 1.0]))

class Param:
    def __init__(s): s.p, s.refs = {}, {}
    def GetParameterNames(s): return tuple(s.p)
    def SetParameter(s, k, v): s.p[k] = v
    def GetParameter(s, k): return s.p.get(k, "")
    def SetNodeReferenceID(s, k, v): s.refs[k] = v
    def GetNodeReference(s, k): return None
    def StartModify(s): return 0
    def EndModify(s, x): pass
param = Param()
RadVeil.RadVeilLogic.getParameterNode = lambda self: param

w = RadVeil.RadVeilWidget()
w.layout = M(); w.parent = M()
w.setup()
print("defaults:", {k: v for k, v in param.p.items()})
assert param.p["Region"] == "face" and param.p["Method"] == "adaptive" and param.p["ReviewAfterRun"] == "true"

# Simulate GUI state: input selected, mock on via env var
import os; os.environ["RADVEIL_SLICER_MOCK"] = "1"
inp = Node("John_Doe_T1", RadVeil.makePhantom(), np.diag([1, 1, 1.2, 1.0]))
w.inputSelector.currentNode.return_value = inp
w.outputSelector.currentNode.return_value = None
w.regionSelector.currentNode.return_value = None
param.p.update(Region="face+ears", Method="adaptive", EarMethod="cut", brain_check="true")
w.reviewAfterRunCheck.checked = False
w.onApply()
assert not errors, errors
r = w.lastResult
print("output:", r.outputVolume.name, "| region seg:", r.regionSegmentation.name)
assert "John" not in r.outputVolume.name and "John" not in r.outputVolume.attrs["RadVeil.Report"]
rep = json.loads(r.outputVolume.attrs["RadVeil.Report"])
print("report params:", rep["parameters"])
assert rep["parameters"]["ear_mode"] == "cut" and rep["parameters"]["brain_check"] is True
assert rep["parameters"]["escalate_to_block"] is False  # Slicer applies the chosen method exactly
print("verdict:", w.verdictLabel.text.replace("<br>", "\n  ")[:600])
assert dialogs and dialogs[-1].close.called, "progress dialog not closed"

# Cancel path: wasCanceled becomes true during run
def slow_mkprog(**kw):
    p = M(); p.wasCanceled = True; dialogs.append(p); return p
slicer.util.createProgressDialog.side_effect = slow_mkprog
n_before = len(created)
w.onApply()
assert len(created) == n_before, "cancel must not create nodes"
print("cancel: nothing created, status:", slicer.util.showStatusMessage.call_args[0][0])
slicer.util.createProgressDialog.side_effect = mkprog

# Refusal path
w.inputSelector.currentNode.return_value = Node("empty", np.zeros((8, 8, 8), np.int16), np.eye(4))
w.onApply()
print("refusal verdict:", w.verdictLabel.text.split("<br>")[0])
assert "Nothing was changed" in w.verdictLabel.text and not errors

# Compare toggling uses lastResult (None after refusal) -> stays unchecked
w.onCompareToggled(True)
print("compare after refusal -> checked =", w.compareButton.checked)
print("ALL WIDGET CHECKS PASSED")

# --- brain segment, other series (aligned + misaligned), landmarks ---
def affine_for(v):
    m = np.diag([1, 1, 1.2, 1.0])
    if v.name == "far":
        m[0, 3] = 500.0  # not aligned with the input
    return m
RadVeil.RadVeilLogic.ijkToWorldMatrix = staticmethod(affine_for)
segments_written = []
slicer.util.updateSegmentBinaryLabelmapFromArray.side_effect = lambda arr, seg, sid, ref: segments_written.append((sid, int(arr.sum())))
markups = []
slicer.util.updateMarkupsControlPointsFromArray.side_effect = lambda node, arr, world=False: markups.append((arr.shape, world))
slicer.mrmlScene.GetFirstNodeByName.return_value = None
inp = Node("T1", RadVeil.makePhantom(), np.diag([1, 1, 1.2, 1.0]))
flair = Node("FLAIR", RadVeil.makePhantom(), None)
far = Node("far", RadVeil.makePhantom(), None)
w.inputSelector.currentNode.return_value = inp
w.otherSeriesSelector.checkedNodes.return_value = [flair, far, inp]  # the input itself must be ignored
param.p.update(Region="face", BrainSegment="true", ShowLandmarks="true", SkinDepth="5")
class SegNode(Node):
    def GetSegmentation(s):
        seg = M(); seg.AddEmptySegment.side_effect = lambda sid, name, color: sid; return seg
slicer.mrmlScene.AddNewNodeByClass.side_effect = lambda cls, name: created.append(
    (SegNode if "Segmentation" in cls else Node)(name, cls=cls)) or created[-1]
w.onApply()
assert not errors, errors
r = w.lastResult
names = [sid for sid, n in segments_written]
print("segments:", segments_written)
assert names == ["Changed region", "Brain"] and all(n > 0 for _, n in segments_written)
print("landmark arrays:", markups)
assert markups and markups[-1] == ((68, 3), True)
series = {s.name: (out, rep) for s, out, rep in r.otherSeries}
print("other series:", {k: (o.name if o else None, {kk: v for kk, v in rep.items() if kk != "mask"}) for k, (o, rep) in series.items()})
assert set(series) == {"FLAIR", "far"}
assert series["FLAIR"][0] is not None and series["FLAIR"][1]["views_checked"] == 3 and series["FLAIR"][1]["faces_found"] == 0
assert series["far"][0] is None and "overlap" in series["far"][1]["error"]
saved = json.loads(r.outputVolume.attrs["RadVeil.Report"])
assert saved["parameters"]["skin_depth_mm"] == 5.0 and "FLAIR" not in json.dumps(saved)
print("verdict:", w.verdictLabel.text.replace("<br>", "\n  "))
assert "FLAIR: anonymized" in w.verdictLabel.text and "far: not anonymized" in w.verdictLabel.text
print("apply button:", w.applyButton.text)

# --- preview: nothing written to any volume, region segment named as preview ---
n_volumes = sum(1 for n in created if n.cls == "vtkMRMLScalarVolumeNode")
segments_written.clear()
before = inp.arr.copy()
w.onPreview()
assert not errors, errors
assert sum(1 for n in created if n.cls == "vtkMRMLScalarVolumeNode") == n_volumes, "preview created a volume"
assert np.array_equal(inp.arr, before), "preview changed the input"
assert [sid for sid, _ in segments_written] == ["Region preview"]
assert w.lastResult.preview and w.lastResult.outputVolume is None
print("preview verdict:", w.verdictLabel.text.split("<br>")[0])
assert "Preview:" in w.verdictLabel.text
print("FEATURE CHECKS PASSED")


# --- install paths (real package absent here) ---
del os.environ["RADVEIL_SLICER_MOCK"]
from RadVeilLib import backend as B
pk = M(); pk.pip_ensure.side_effect = RuntimeError("declined")
sys.modules["slicer.packaging"] = pk; slicer.packaging = pk
assert w.ensureBackend() is False and pk.pip_ensure.call_args.kwargs["prompt_install"] is True
print("pip_ensure path: declined -> False; args", pk.pip_ensure.call_args)
pk.pip_ensure.side_effect = None
B.is_installed = lambda: True
assert w.installBackend() is True and pk.pip_ensure.call_args.kwargs["prompt_install"] is False
B.is_installed = lambda: False
del sys.modules["slicer.packaging"]; slicer.packaging = None
calls = []
B.install = lambda wheel_path=None: calls.append(wheel_path) or "0.1.0"
slicer.util.confirmOkCancelDisplay.return_value = True
assert w.ensureBackend() is True and calls == [None]
print("fallback path: confirmed -> installed via pip;", "wheel install ->", w.installBackend(wheelPath="/x/radveil.whl"), calls)
print("INSTALL CHECKS PASSED")
