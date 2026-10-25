cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(RadVeil)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/rAum/radveil-slicer")
set(EXTENSION_CATEGORY "Utilities")
set(EXTENSION_CONTRIBUTORS "Piotr Gródek")
set(EXTENSION_DESCRIPTION "Face and ear anonymization (defacing) of MRI and CT head volumes with RadVeil, verified by re-running a face detector on the result. Before/after review in linked 3D views, region preview, brain segment, and anonymization of other series of the same session. Voxels outside the anonymized region are preserved bit-exact. A de-identification aid, not a medical device; provided as is, without warranty.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/rAum/radveil-slicer/main/RadVeil.png")
# Real Slicer screenshot from CI (Real radveil on MRHead + screenshots job, `screenshots` artifact).
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/rAum/radveil-slicer/main/Screenshots/RadVeil.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies
set(EXTENSION_BUILD_SUBDIRECTORY ".")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(RadVeil)

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
