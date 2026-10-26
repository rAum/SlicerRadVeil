"""Register this checkout's RadVeil module in 3D Slicer for development.

Run once from Slicer's Python console (View -> Python Console):

    p = "/path/to/SlicerRadVeil/tools/slicer_dev_setup.py"; exec(open(p).read(), {"__file__": p})

It adds <checkout>/RadVeil to Modules -> Additional module paths (kept across
restarts), turns on Developer mode (Reload / Reload and Test buttons) and loads
the module right away, so no restart is needed.
"""

import os

import qt
import slicer


def setup(module_dir):
    module_dir = os.path.abspath(module_dir)
    module_file = os.path.join(module_dir, "RadVeil.py")
    if not os.path.isfile(module_file):
        raise RuntimeError(f"RadVeil.py not found in {module_dir}")

    settings = slicer.app.revisionUserSettings()
    paths = settings.value("Modules/AdditionalPaths") or []
    if isinstance(paths, str):
        paths = [paths]
    known = {os.path.normcase(os.path.abspath(p)) for p in paths}
    if os.path.normcase(module_dir) not in known:
        settings.setValue("Modules/AdditionalPaths", list(paths) + [module_dir])
        print(f"Added {module_dir} to additional module paths.")

    slicer.app.userSettings().setValue("Developer/DeveloperMode", True)

    if not hasattr(slicer.modules, "radveil"):
        factory = slicer.app.moduleManager().factoryManager()
        factory.registerModule(qt.QFileInfo(module_file))
        factory.loadModules(["RadVeil"])
    slicer.util.selectModule("RadVeil")
    print("RadVeil loaded. Use 'Reload and Test' in the module panel to run the self-test.")


setup(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "RadVeil"))
