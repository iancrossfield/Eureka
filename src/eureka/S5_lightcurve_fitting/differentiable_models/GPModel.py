import numpy as np

import theano
theano.config.gcc__cxxflags += " -fexceptions"
import theano.tensor as tt
import celerite2.pymc3 as celerite2

# Avoid tonnes of "Cannot construct a scalar test value" messages
import logging
logger = logging.getLogger("theano.tensor.opt")
logger.setLevel(logging.ERROR)

from . import PyMC3Model
from ...lib.split_channels import split


class GPModel(PyMC3Model):
    """Model for Gaussian Process (GP)"""
    def __init__(self, kernel_classes, kernel_inputs, lc, gp_code='celerite',
                 normalize=False, **kwargs):
        """Initialize the GP model.

        Parameters
        ----------
        kernel_classes : list
            The types of GP kernels to use.
        kernel_inputs : list
            The names of the GP kernel inputs.
        lc : eureka.S5_lightcurve_fitting.lightcurve
            The current lightcurve object.
        gp_code : str; optional
            Type GP package to use from ('celerite'),
            by default 'celerite'.
        normalize : bool; optional
            If True, normalize the covariate by mean subtracting it and
            dividing by the standard deviation. By default, False.
        **kwargs : dict
            Additional parameters to pass to
            eureka.S5_lightcurve_fitting.differentiable_models.PyMC3Model.__init__().
        """
        # Inherit from PyMC3Model class
        super().__init__(**kwargs)

        # Define model type (physical, systematic, other)
        self.modeltype = 'GP'

        # Get GP parameters
        self.gp_code_name = gp_code
        self.normalize = normalize
        self.kernel_types = kernel_classes
        self.kernel_input_names = kernel_inputs
        self.kernel_inputs = None
        self.nkernels = len(kernel_classes)
        self.flux = lc.flux
        self.unc = lc.unc
        self.unc_fit = lc.unc_fit
        self.time = lc.time

        if self.gp_code_name != 'celerite':
            raise AssertionError('Currently celerite2 is the only GP package '
                                 'that can be used with the exoplanet and '
                                 'nuts fitting methods.')
        elif self.nkernels > 1:
            raise AssertionError('Our celerite2 implementation cannot compute '
                                 'multi-dimensional GPs, please choose a '
                                 'different GP code.')

    def setup(self):
        """Setup a model for evaluation and fitting.
        """
        self.gps = []
        for c in range(self.nchannel_fitted):
            if self.nchannel_fitted > 1:
                chan = self.fitted_channels[c]
            else:
                chan = 0

            # Make the gp object
            gp = self.setup_GP(tt, chan)
            self.gps.append(gp)

    def eval(self, fit_lc, channel=None, gp=None, **kwargs):
        """Evaluate the function with the given values.

        Parameters
        ----------
        input_fit : ndarray
            The rest of the current model evaluated.
        eval : bool; optional
            If true evaluate the model, otherwise simply compile the model.
            Defaults to True.
        channel : int; optional
            If not None, only consider one of the channels. Defaults to None.
        **kwargs : dict
            Must pass in the time array here if not already set.

        Returns
        -------
        lcfinal : ndarray
            Predicted systematics model
        """
        input_gp = gp

        if channel is None:
            nchan = self.nchannel_fitted
            channels = self.fitted_channels
        else:
            nchan = 1
            channels = [channel, ]

        # Get the time
        if self.time is None:
            self.time = kwargs.get('time')

        lcfinal = np.ma.array([])

        # Parse parameters as coefficients
        for c in range(nchan):
            if self.nchannel_fitted > 1:
                chan = channels[c]
                # get flux and uncertainties for current channel
                flux, unc_fit = split([self.flux, self.unc_fit],
                                      self.nints, chan)
                if channel is None:
                    fit_lc_temp = split([fit_lc, ], self.nints, chan)[0]
                else:
                    # If only a specific channel is being evaluated, then only
                    # that channel's fitted mode will be passed in
                    fit_lc_temp = fit_lc
            else:
                chan = 0
                # get flux and uncertainties for current channel
                flux = self.flux
                fit_lc_temp = fit_lc
                unc_fit = self.unc_fit
            residuals = np.ma.masked_invalid(flux-fit_lc_temp)
            if self.multwhite:
                time = split([self.time, ], self.nints, chan)[0]
            else:
                time = self.time
            residuals = np.ma.masked_where(time.mask, residuals)

            # Remove poorly handled masked values
            good = ~np.ma.getmaskarray(residuals)
            unc_fit = unc_fit[good]
            residuals = residuals[good]

            # Create the GP object with current parameters
            if input_gp is None:
                gp = self.setup_GP(np, chan)
            else:
                gp = input_gp

            kernel_inputs = self.kernel_inputs[chan][0][good]
            gp.compute(kernel_inputs, yerr=unc_fit)
            mu = gp.predict(residuals).eval()

            # Re-insert and mask bad values
            mu_full = np.ma.zeros(len(time))
            mu_full[good] = mu
            mu_full = np.ma.masked_where(~good, mu_full)

            # Append this channel to the outputs
            lcfinal = np.ma.append(lcfinal, mu_full)

        return lcfinal

    def setup_inputs(self, lib):
        """Setting up kernel inputs as array and standardizing them if asked.

        For details on the benefits of normalization, see e.g.
        Evans et al. 2017.
        """
        self.kernel_inputs = []
        for c in range(self.nchannel_fitted):
            if self.nchannel_fitted > 1:
                chan = self.fitted_channels[c]
            else:
                chan = 0

            if self.multwhite:
                time = split([self.time, ], self.nints, chan)[0]
            else:
                time = self.time

            kernel_inputs_channel = lib.zeros((0, time.size))
            for name in self.kernel_input_names:
                if name == 'time':
                    x = np.ma.copy(self.time)
                else:
                    # add more input options here
                    raise ValueError('Currently, only GPs as a function of '
                                     'time are supported, but you have '
                                     'specified a GP as a function of '
                                     f'{name}.')

                if self.multwhite:
                    x = split([x, ], self.nints, chan)[0]

                if self.normalize:
                    x = (x-np.ma.mean(x))/np.ma.std(x)

                kernel_inputs_channel = lib.concatenate([kernel_inputs_channel,
                                                         x[np.newaxis]])

            self.kernel_inputs.append(kernel_inputs_channel)

    def setup_GP(self, lib, c=0):
        """Set up GP kernels and GP object.

        Parameters
        ----------
        c : int; optional
            The current channel index. Defaults to 0.

        Returns
        -------
        celerite2.GP, george.GP, or tinygp.GaussianProcess
            The GP object to use for this fit.
        """
        if c == 0:
            chankey = ''
        else:
            chankey = f'_ch{c}'

        if lib == tt:
            model = self.model
        else:
            model = self.fit

        coeffs = np.zeros((self.nkernels, 2)).tolist()
        for i, par in enumerate(['A', 'm']):
            for k in range(self.nkernels):
                if k == 0:
                    kernelkey = ''
                else:
                    kernelkey = str(k)
                index = f'{par}{kernelkey}{chankey}'
                coeffs[k][i] = getattr(model, index)

        if self.kernel_inputs is None:
            self.setup_inputs(lib=lib)

        # get the kernel which is the sum of the individual kernel functions
        kernel = self.get_kernel(lib, self.kernel_types[0], coeffs, 0, c)
        for k in range(1, self.nkernels):
            kernel += self.get_kernel(lib, self.kernel_types[k], coeffs, k, c)

        # Make the gp object
        return celerite2.GaussianProcess(kernel, mean=0, fit_mean=False)

    def get_kernel(self, lib, kernel_name, coeffs, k, c=0):
        """Get individual kernels.

        Parameters
        ----------
        lib : module
            Either the np module for evaluated models or the tt module for
            gradient-based inference.
        kernel_name : str
            The name of the kernel to get.
        coeffs : list
            A three-dimensional list of GP hyperparameter coefficients of shape
            (self.nchannel_fitted, self.nkernels, 2).
        k : int
            The kernel number.
        c : int; optional
            The channel index, by default 0.

        Returns
        -------
        kernel
            The requested kernel.
        """
        # get metric and amplitude for the current kernel and channel
        amp = lib.exp(coeffs[k][0])
        ls = lib.exp(coeffs[k][1])

        if kernel_name == 'Matern32':
            kernel = celerite2.terms.Matern32Term(sigma=1, rho=ls)
        else:
            raise AssertionError('Our celerite2 implementation currently only '
                                 'supports a Matern32 kernel.')

        # Setting the amplitude
        kernel *= celerite2.terms.RealTerm(a=amp, c=0)

        return kernel

    def loglikelihood(self, fit_lc, channel=None):
        """Compute log likelihood of GP

        Parameters
        ----------
        fit_lc : ndarray
            The fitted model.
        channel : int; optional
            If not None, only consider one of the channels. Defaults to None.

        Returns
        -------
        float
            log likelihood of the GP evaluated by celerite2
        """
        if channel is None:
            nchan = self.nchannel_fitted
            channels = self.fitted_channels
        else:
            nchan = 1
            channels = [channel, ]

        logL = 0
        for c in np.arange(nchan):
            if self.nchannel_fitted > 1:
                chan = channels[c]
                # get flux and uncertainties for current channel
                flux, unc_fit = split([self.flux, self.unc_fit],
                                      self.nints, chan)
                if channel is None:
                    fit = split([fit_lc, ], self.nints, chan)[0]
                else:
                    # If only a specific channel is being evaluated, then only
                    # that channel's fitted model will be passed in
                    fit = fit_lc
            else:
                chan = 0
                # get flux and uncertainties for current channel
                flux = self.flux
                fit = fit_lc
                unc_fit = self.unc_fit
            residuals = np.ma.masked_invalid(flux-fit)
            if self.multwhite:
                time = split([self.time, ], self.nints, chan)[0]
            else:
                time = self.time
            residuals = np.ma.masked_where(time.mask, residuals)

            # Remove poorly handled masked values
            good = ~np.ma.getmaskarray(residuals)
            unc_fit = unc_fit[good]
            residuals = residuals[good]

            # set up GP with current parameters
            gp = self.setup_GP(np, chan)

            kernel_inputs = self.kernel_inputs[chan][0][good]
            gp.compute(kernel_inputs, yerr=unc_fit)
            logL_temp = gp.log_likelihood(residuals).eval()

            logL += logL_temp

        return logL