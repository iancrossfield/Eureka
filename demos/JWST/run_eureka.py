import sys
sys.path.insert(0, '../../')
import eureka.S1_detector_processing.s1_process as s1
import eureka.S2_calibrations.s2_calibrate as s2
import eureka.S3_data_reduction.s3_reduce as s3
import eureka.S4_generate_lightcurves.s4_genLC as s4
import eureka.S5_lightcurve_fitting.s5_fit as s5
import eureka.S6_planet_spectra.s6_spectra as s6

# eventlabel = 'imaging_template'
# eventlabel = 'miri_lrs_template'
# eventlabel = 'nirspec_fs_template'
eventlabel = 'nircam_wfss_template'
ecf_path = './'

if __name__ == '__main__':
	s1_meta = s1.rampfitJWST(eventlabel, ecf_path=ecf_path)
	
	s2_meta = s2.calibrateJWST(eventlabel, ecf_path=ecf_path)

	s3_meta = s3.reduceJWST(eventlabel, ecf_path=ecf_path, s2_meta=s2_meta)

	s4_meta = s4.lcJWST(eventlabel, ecf_path=ecf_path, s3_meta=s3_meta)

	s5_meta = s5.fitJWST(eventlabel, ecf_path=ecf_path, s4_meta=s4_meta)

	s6_meta = s6.plot_spectra(eventlabel, ecf_path=ecf_path, s5_meta=s5_meta)
