cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(RadVeil)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/rAum/SlicerRadVeil")
set(EXTENSION_CATEGORY "Utilities")
set(EXTENSION_CONTRIBUTORS "Piotr Gródek (independent)")
set(EXTENSION_DESCRIPTION "Face and ear anonymization (defacing) of MRI and CT head volumes with RadVeil, verified by re-running a face detector. Voxels outside the anonymized region are preserved bit-exact.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/rAum/SlicerRadVeil/main/RadVeil.png")
# Real Slicer screenshot from CI (Real radveil on MRHead + screenshots job, `screenshots` artifact).
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/rAum/SlicerRadVeil/main/Screenshots/RadVeil.png")
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
