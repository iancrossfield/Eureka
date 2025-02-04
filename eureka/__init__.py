# !/usr/bin/python
import os

PACAKGEDIR = os.path.abspath(os.path.dirname(__file__))

__all__ = ["lib", "S1_detector_processing", "S2_calibrations", "S3_data_reduction", "S4_generate_lightcurves", "S5_lightcurve_fitting", "S6_planet_spectra"]

from .version import __version__

from . import lib
from . import S1_detector_processing
from . import S2_calibrations
from . import S3_data_reduction
from . import S4_generate_lightcurves
from . import S5_lightcurve_fitting    
from . import S6_planet_spectra
