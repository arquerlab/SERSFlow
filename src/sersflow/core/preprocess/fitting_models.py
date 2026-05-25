import numpy as np

def gaussian(x, *params):
    pos = params[0]
    amp = params[1]
    fwhm = params[2]
    return amp * np.exp(-(np.power(x-pos,2)/(fwhm*fwhm/4.0/np.log(2.0))))

def polynomial_background(x, *params):
    return np.polyval(params, x)

def combined_models(*models):
    return sum(models)
