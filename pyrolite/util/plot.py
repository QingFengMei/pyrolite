import os
import inspect
from copy import copy
from types import MethodType
from pathlib import Path
import numpy as np
from numpy.linalg import LinAlgError
import pandas as pd
from scipy.stats.kde import gaussian_kde
import scipy.spatial
import scipy.interpolate
import matplotlib.pyplot as plt
import matplotlib.colors
import matplotlib.lines
import matplotlib.patches
import matplotlib.path
from mpl_toolkits.axes_grid1 import make_axes_locatable
import matplotlib.axes as matax

from matplotlib.transforms import Bbox
from sklearn.decomposition import PCA
import logging

try:
    import statsmodels.api as sm
    HAVE_SM = True
except ImportError:
    HAVE_SM = False

from ..util.math import (
    eigsorted,
    nancov,
    interpolate_line,
    flattengrid,
    linspc_,
    logspc_,
)
from ..comp.codata import close, alr, ilr, clr, inverse_alr, inverse_clr, inverse_ilr

logging.getLogger(__name__).addHandler(logging.NullHandler())
logger = logging.getLogger()

__DEFAULT_CONT_COLORMAP__ = plt.cm.viridis
__DEFAULT_DISC_COLORMAP__ = plt.cm.tab10


def modify_legend_handles(ax, **kwargs):
    """
    Modify the handles of a legend based for a single axis.

    Parameters
    ----------
    ax : :class:`matplotlib.axes.Axes`
        Axis for which to obtain modifed legend handles.

    Returns
    -------
    handles : :class:`list`
        Handles to be passed to a legend call.
    labels : :class:`list`
        Labels to be passed to a legend call.
    """
    hndls, labls = ax.get_legend_handles_labels()
    _hndls = []
    for h in hndls:
        _h = copy(h)
        _h.update(kwargs)
        _hndls.append(_h)
    return _hndls, labls


def interpolated_patch_path(patch, resolution=100):
    """
    Obtain the periodic interpolation of the existing path of a patch at a
    given resolution.

    Parameters
    -----------
    patch : :class:`matplotlib.patches.Patch`
        Patch to obtain the original path from.
    resolution :class:`int`
        Resolution at which to obtain the new path. The verticies of the new path
        will have shape (`resolution`, 2).

    Returns
    --------
    :class:`matplotlib.path.Path`
        Interpolated :class:`~matplotlib.path.Path` object.
    """
    pth = patch.get_path()
    tfm = patch.get_transform()
    pathtfm = tfm.transform_path(pth)
    x, y = pathtfm.vertices.T
    tck, u = scipy.interpolate.splprep([x[:-1], y[:-1]], per=True, s=1)
    xi, yi = scipy.interpolate.splev(np.linspace(0.0, 1.0, resolution), tck)
    # could get control points for path and construct codes here
    codes = None
    return matplotlib.path.Path(np.vstack([xi, yi]).T, codes=None)


def add_colorbar(mappable, **kwargs):
    """
    Adds a colorbar to a given mappable object.

    Source: http://joseph-long.com/writing/colorbars/

    Parameters
    ----------
    mappable
        The Image, ContourSet, etc. to which the colorbar applies.

    Returns
    ----------
    :class:`matplotlib.colorbar.Colorbar`
    """
    ax = kwargs.get("ax", None)
    if hasattr(mappable, "axes"):
        ax = ax or mappable.axes
    elif hasattr(mappable, "ax"):
        ax = ax or mappable.ax

    position = kwargs.pop("position", "right")
    size = kwargs.pop("size", "5%")
    pad = kwargs.pop("pad", 0.05)

    fig = ax.figure
    divider = make_axes_locatable(ax)
    cax = divider.append_axes(position, size=size, pad=pad)
    return fig.colorbar(mappable, cax=cax, **kwargs)


def bin_centres_to_edges(centres):
    """
    Translates point estimates at the centres of bins to equivalent edges,
    for the case of evenly spaced bins.

    Todo
    ------
        * This can be updated to unevenly spaced bins, just need to calculate outer bins.
    """
    step = (centres[1] - centres[0]) / 2
    return np.append(centres - step, centres[-1] + step)


def bin_edges_to_centres(edges):
    """
    Translates edges of histogram bins to bin centres.
    """
    if edges.ndim == 1:
        steps = (edges[1:] - edges[:-1]) / 2
        return edges[:-1] + steps
    else:
        steps = (edges[1:, 1:] - edges[:-1, :-1]) / 2
        centres = edges[:-1, :-1] + steps
        return centres


def affine_transform(mtx=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]])):
    def tfm(data):
        xy = data[:, :2]
        return (mtx @ np.vstack((xy.T[:2], np.ones(xy.T.shape[1]))))[:2]

    return tfm


def ABC_to_xy(ABC, xscale=1.0, yscale=1.0):
    assert ABC.shape[-1] == 3
    # transform from ternary to xy cartesian
    scale = affine_transform(np.array([[xscale, 0, 0], [0, yscale, 0], [0, 0, 1]]))
    shear = affine_transform(np.array([[1, 1 / 2, 0], [0, 1, 0], [0, 0, 1]]))
    xy = scale(shear(close(ABC)).T)
    return xy.T


def xy_to_ABC(xy, xscale=1.0, yscale=1.0):
    assert xy.shape[-1] == 2
    # transform from xy cartesian to ternary
    scale = affine_transform(
        np.array([[1 / xscale, 0, 0], [0, 1 / yscale, 0], [0, 0, 1]])
    )
    shear = affine_transform(np.array([[1, -1 / 2, 0], [0, 1, 0], [0, 0, 1]]))
    xs, ys = shear(scale(xy).T)
    zs = 1.0 - (xs + ys)  # + (xscale-1) + (yscale-1)
    return np.vstack([xs, ys, zs]).T


def ternary_heatmap(
    data,
    bins=10,
    margin=0.01,
    force_margin=False,
    remove_background=True,
    transform=ilr,
    inverse_transform=inverse_ilr,
    mode="histogram",
    aspect="eq",
    ret_centres=False,
    **kwargs
):
    """
    Heatmap for ternary diagrams.

    Parameters
    -----------
    data : :class:`numpy.ndarray`
        Ternary data to obtain heatmap coords from.
    bins : :class:`int`
        Number of bins for the grid.
    margin : :class:`float`
        Optional specification of margin around ternary diagram to draw the grid.
    force_margin : :class:`bool`
        Whether to enforce the minimum margin.
    remove_background : :class:`bool`
        Whether to display cells with no counts.
    transform : :class:`callable` | :class:`sklearn.base.TransformerMixin`, :func:`~pyrolite.comp.codata.ilr`
        Callable function or Transformer class.
    inverse_transform : :class:`callable`, :func:`~pyrolite.comp.codata.inverse_ilr`
        Inverse function for `transform`, necessary if transformer class not specified.
    mode : :class:`str`, {'histogram', 'density'}
        Which mode to render the histogram/KDE in.
    aspect : :class:`str`, {'unit', 'equilateral'}
        Aspect of the ternary plot - whether to plot with an equilateral triangle
        (yscale = 3**0.5/2) or a triangle within a unit square (yscale = 1.)
    ret_centres : :class:`bool`
        Whether to return the centres of the ternary bins.

    Returns
    -------
    :class:`tuple` of :class:`numpy.ndarray`
        :code:`x` bin edges :code:`xe`, :code:`y` bin edges :code:`ye`, histogram/density estimates :code:`Z`.
        If :code:`ret_centres` is :code:`True`, the last return value will contain the
        bin :code:`centres`.

    Todo
    -----
        * Add hexbin mode
    """
    if inspect.isclass(transform):
        # TransformerMixin
        tcls = transform()
        tfm = tcls.transform
        itfm = tcls.inverse_transform
    else:
        # callable
        tfm = transform
        assert callable(inverse_transform)
        itfm = inverse_transform

    if aspect == "unit":
        yscale = 1.0
    else:
        yscale = np.sqrt(3) / 2

    AXtfm = lambda x: ABC_to_xy(x, yscale=yscale).T
    XAtfm = lambda x: xy_to_ABC(x, yscale=yscale).T

    data = close(data)
    if not force_margin:
        margin = min([margin, np.nanmin(data[data > 0])])
    # this appears to cause problems for ternary density diagrams
    _min, _max = (margin, 1.0 - margin)

    bounds = np.array(  # three points defining the edges of what will be rendered
        [
            [margin, margin, 1 - 2 * margin],
            [margin, 1 - 2 * margin, margin],
            [1 - 2 * margin, margin, margin],
        ]
    )
    xbounds, ybounds = AXtfm(bounds)
    xbounds = np.hstack((xbounds, [xbounds[0]]))
    ybounds = np.hstack((ybounds, [ybounds[0]]))
    tck, u = scipy.interpolate.splprep([xbounds, ybounds], per=True, s=0, k=1)
    xi, yi = scipy.interpolate.splev(np.linspace(0, 1.0, 10000), tck)

    xs, ys, zs = XAtfm(np.vstack([xi, yi]).T)
    bound_data = np.vstack([xs, ys, zs])
    abounds = tfm(bound_data.T)
    axmin, axmax = np.nanmin(abounds[:, 0]), np.nanmax(abounds[:, 0])
    aymin, aymax = np.nanmin(abounds[:, 1]), np.nanmax(abounds[:, 1])

    adata = tfm(data)

    ndim = adata.shape[1]
    # bins for evaluation
    bins = [
        np.linspace(np.nanmin(abounds[:, dim]), np.nanmax(abounds[:, dim]), bins)
        for dim in range(ndim)
    ]
    centres = np.meshgrid(*bins)
    binedges = [bin_centres_to_edges(b) for b in bins]
    edges = np.meshgrid(*binedges)

    assert len(bins) == ndim
    # histogram in logspace
    if mode == "density":
        kdedata = adata[np.isfinite(adata).all(axis=1), :]
        k = gaussian_kde(kdedata.T)  # gaussian kernel approximation on the grid
        cdata = np.vstack([c.flatten() for c in centres])
        H = k(cdata).T.reshape((bins[0].size, bins[1].size))
    elif "hist" in mode:
        H, hedges = np.histogramdd(adata, bins=binedges)
        H = H.T
    elif "hex" in mode:
        # could do this in practice, but need to immplement transforms for hexbins
        raise NotImplementedError
    else:
        raise NotImplementedError

    e_shape = edges[0].shape
    flatedges = np.vstack([e.flatten() for e in edges])
    xe, ye = AXtfm(itfm(flatedges.T))
    xe, ye = xe.reshape(e_shape), ye.reshape(e_shape)

    c_shape = centres[0].shape
    flatcentres = np.vstack([c.flatten() for c in centres])
    xi, yi = AXtfm(itfm(flatcentres.T))
    xi, yi = xi.reshape(c_shape), yi.reshape(c_shape)
    centres = [xi, yi]

    if remove_background:
        H[H == 0] = np.nan
    if ret_centres:
        return xe, ye, H, centres
    return xe, ye, H


def conditional_prob_density(
    y,
    x=None,
    logy=False,
    resolution=5,
    ybins=100,
    rescale=True,
    mode="binkde",
    ret_centres=False,
):
    """
    Estimate the conditional probability density of one dependent variable.

    Parameters
    -----------
    y : :class:`np.ndarray`
        Dependent variable for which to calculate conditional probability P(y | X=x)
    x : :class:`np.ndarray`, :code:`None`
        Optionally-specified independent index.
    logy : :class:`bool`
        Whether to use a logarithmic bin spacing on the y axis.
    resolution : :class:`int`
        Points added per segment via interpolation along the x axis.
    ybins : :class:`int`
        Bins for histograms and grids along the independent axis.
    rescale : :class:`bool`
        Whether to rescale bins to give the same max Z across x.
    mode : :class:`str`
        Mode of computation.

            If mode is :code:`"ckde"`, use
            :func:`statsmodels.nonparametric.KDEMultivariateConditional` to compute a
            conditional kernel density estimate. If mode is :code:`"kde"`, use a normal
            gaussian kernel density estimate. If mode is :code:`"binkde"`, use a gaussian
            kernel density estimate over y for each bin. If mode is :code:`"hist"`,
            compute a histogram.
    ret_centres : :class:`bool`
        Whether to return bin centres in addtion to histogram edges,
        e.g. for later contouring.

    Returns
    -------
    :class:`tuple` of :class:`numpy.ndarray`
        :code:`x` bin edges :code:`xe`, :code:`y` bin edges :code:`ye`, histogram/density
        estimates :code:`Z`. If :code:`ret_centres` is :code:`True`, the last two return
        values will contain the bin centres :code:`xi`, :code:`yi`.


    Notes
    ------
        * Bins along the x axis are defined such that the x points (including
            interpolated points) are the centres.

    Todo
    -----
        * Tests
        * Implement log grids (for y)
        * Add approach for interpolation? (need resolution etc) - this will resolve lines, not points!
    """
    # check for shapes
    assert not ((x is None) and (y is None))
    if y is None:  # Swap the variables. Create an index for x
        y = x
        x = None

    if x is None:  # Create a simple arange-based index
        x = np.arange(y.shape[1])

    if not x.shape == y.shape:
        try:  # x is an index to be tiled
            assert y.shape[1] == x.shape[0]
            x = np.tile(x, y.shape[0]).reshape(*y.shape)
        except AssertionError:
            # shape mismatch
            msg = "Mismatched shapes: x: {}, y: {}. Needs either ".format(
                x.shape, y.shape
            )
            raise AssertionError(msg)

    if resolution:
        xy = np.array([x, y])
        xy = np.swapaxes(xy, 1, 0)
        xy = interpolate_line(xy, n=resolution)
        x, y = np.swapaxes(xy, 0, 1)
    xx, yy = (
        np.sort(x[0]),
        [linspc_, logspc_][logy](np.nanmin(y), np.nanmax(y), bins=ybins),
    )
    xi, yi = np.meshgrid(xx, yy)
    xe, ye = np.meshgrid(bin_centres_to_edges(xx), bin_centres_to_edges(yy))
    # scipy.interpolate.bisplrep
    if mode == "ckde":
        if HAVE_SM:
            dens_c = sm.nonparametric.KDEMultivariateConditional(
                endog=[y.flatten()],
                exog=[x.flatten()],
                dep_type="c",
                indep_type="c",
                bw="normal_reference",
            )
        else:
            raise ImportError("Requires statsmodels.")
        # statsmodels pdf takes values in reverse order
        zi = dens_c.pdf(*flattengrid([yi, xi])).reshape(xi.shape)
    elif mode == "kde":  # kde of dataset
        try:
            kde = gaussian_kde(np.vstack([x.flatten(), y.flatten()]))
        except LinAlgError:  # singular matrix, need to add miniscule noise on x?
            logger.warn("Singular Matrix")
            logger.x = x + np.random.randn(*x.shape) * np.finfo(np.float).eps
            kde = gaussian_kde(flattengrid([x, y]).T)

        xkde = gaussian_kde(x[0])(x[0])  # marginal density along x
        zi = kde(flattengrid([xi, yi])).T.reshape(xi.shape) / xkde[np.newaxis, :]
    elif mode == "binkde":  # calclate a kde per bin
        zi = np.zeros(xi.shape)
        for bin in range(x.shape[1]):
            kde = gaussian_kde(y[:, bin])
            zi[:, bin] = kde(yi[:, bin])
    elif "hist" in mode.lower():  # simply compute the histogram
        H, hedges = np.histogramdd(
            flattengrid([x, y]).T,
            bins=[bin_centres_to_edges(xx), bin_centres_to_edges(yy)],
        )
        zi = H.T.reshape(xi.shape)
    else:
        raise NotImplementedError

    if rescale:  # rescale bins across x
        xzfactors = np.nanmax(zi) / np.nanmax(zi, axis=0)
        zi *= xzfactors[np.newaxis, :]

    if ret_centres:
        return xe, ye, zi, xi, yi
    return xe, ye, zi


def proxy_rect(**kwargs):
    """
    Generates a legend proxy for a filled region.

    Returns
    ----------
    :class:`matplotlib.patches.Rectangle`
    """
    return matplotlib.patches.Rectangle((0, 0), 1, 1, **kwargs)


def proxy_line(**kwargs):
    """
    Generates a legend proxy for a line region.

    Returns
    ----------
    :class:`matplotlib.lines.Line2D`
    """
    return matplotlib.lines.Line2D(range(1), range(1), **kwargs)


def draw_vector(v0, v1, ax=None, **kwargs):
    """
    Plots an arrow represnting the direction and magnitue of a principal
    component on a biaxial plot.

    Modified after Jake VanderPlas' Python Data Science Handbook
    https://jakevdp.github.io/PythonDataScienceHandbook/ \
    05.09-principal-component-analysis.html

    Todo
    -----
        Update for ternary plots.

    """
    ax = ax
    arrowprops = dict(arrowstyle="->", linewidth=2, shrinkA=0, shrinkB=0)
    arrowprops.update(kwargs)
    ax.annotate("", v1, v0, arrowprops=arrowprops)


def vector_to_line(
    mu: np.array, vector: np.array, variance: float, spans: int = 4, expand: int = 10
):
    """
    Creates an array of points representing a line along a vector - typically
    for principal component analysis. Modified after Jake VanderPlas' Python Data
    Science Handbook https://jakevdp.github.io/PythonDataScienceHandbook/ \
    05.09-principal-component-analysis.html
    """
    length = np.sqrt(variance)
    parts = np.linspace(-spans, spans, expand * spans + 1)
    line = length * np.dot(parts[:, np.newaxis], vector[np.newaxis, :]) + mu
    line = length * parts.reshape(parts.shape[0], 1) * vector + mu
    return line


def plot_stdev_ellipses(comp, nstds=4, scale=100, transform=None, ax=None, **kwargs):
    """
    Plot covariance ellipses at a number of standard deviations from the mean.

    Parameters
    -------------
    comp : :class:`numpy.ndarray`
        Composition to use.
    nstds : :class:`int`
        Number of standard deviations from the mean for which to plot the ellipses.
    scale : :class:`float`
        Scale applying to all x-y data points. For intergration with python-ternary.
    transform : :class:`callable`
        Function for transformation of data prior to plotting (to either 2D or 3D).
    ax : :class:`matplotlib.axes.Axes`
        Axes to plot on.

    Returns
    -------
    ax :  :class:`matplotlib.axes.Axes`
    """
    mean, cov = np.nanmean(comp, axis=0), nancov(comp)
    vals, vecs = eigsorted(cov)
    theta = np.degrees(np.arctan2(*vecs[::-1]))

    if ax is None:
        fig, ax = plt.subplots(1)

    for nstd in np.arange(1, nstds + 1)[::-1]:  # backwards for svg construction
        # here we use the absolute eigenvalues
        xsig, ysig = nstd * np.sqrt(np.abs(vals))  # n sigmas
        ell = matplotlib.patches.Ellipse(
            xy=mean.flatten(), width=2 * xsig, height=2 * ysig, angle=theta[:1]
        )
        points = interpolated_patch_path(ell, resolution=1000).vertices

        if callable(transform) and (transform is not None):
            points = transform(points)  # transform to compositional data

        if points.shape[1] == 3:
            xy = ABC_to_xy(points, yscale=np.sqrt(3) / 2)
        else:
            xy = points
        xy *= scale
        patch = matplotlib.patches.PathPatch(matplotlib.path.Path(xy), **kwargs)
        patch.set_edgecolor("k")
        patch.set_alpha(1.0 / nstd)
        patch.set_linewidth(0.5)
        ax.add_artist(patch)
    return ax


def plot_pca_vectors(comp, nstds=2, scale=100.0, transform=None, ax=None, **kwargs):
    """
    Plot vectors corresponding to principal components and their magnitudes.

    Parameters
    -------------
    comp : :class:`numpy.ndarray`
        Composition to use.
    nstds : :class:`int`
        Multiplier for magnitude of individual principal component vectors.
    scale : :class:`float`
        Scale applying to all x-y data points. For intergration with python-ternary.
    transform : :class:`callable`
        Function for transformation of data prior to plotting (to either 2D or 3D).
    ax : :class:`matplotlib.axes.Axes`
        Axes to plot on.

    Returns
    -------
    ax :  :class:`matplotlib.axes.Axes`
    """
    pca = PCA(n_components=2)
    pca.fit(comp)

    if ax is None:
        fig, ax = plt.subplots(1)

    for variance, vector in zip(pca.explained_variance_, pca.components_):
        line = vector_to_line(pca.mean_, vector, variance, spans=nstds)
        if callable(transform) and (transform is not None):
            line = transform(line)
        if line.shape[1] == 3:
            xy = ABC_to_xy(line, yscale=np.sqrt(3) / 2)
        else:
            xy = line
        xy *= scale
        ax.plot(*xy.T, **kwargs)
    return ax


def plot_2dhull(ax, data, splines=False, s=0, **plotkwargs):
    """
    Plots a 2D convex hull around an array of xy data points.
    """
    chull = scipy.spatial.ConvexHull(data, incremental=True)
    x, y = data[chull.vertices].T
    if not splines:
        lines = ax.plot(np.append(x, [x[0]]), np.append(y, [y[0]]), **plotkwargs)
    else:
        # https://stackoverflow.com/questions/33962717/interpolating-a-closed-curve-using-scipy
        tck, u = scipy.interpolate.splprep([x, y], per=True, s=s)
        xi, yi = scipy.interpolate.splev(np.linspace(0, 1, 1000), tck)
        lines = ax.plot(xi, yi, **plotkwargs)
    return lines


def percentile_contour_values_from_meshz(
    z, percentiles=[0.95, 0.66, 0.33], resolution=1000
):
    """
    Integrate a probability density distribution Z(X,Y) to obtain contours in Z which
    correspond to specified percentile contours.T

    Parameters
    ----------
    z : :class:`numpy.ndarray`
        Probability density function over x, y.
    percentiles : :class:`numpy.ndarray`
        Percentile values for which to create contours.
    resolution : :class:`int`
        Number of bins for thresholds between 0. and max(Z)

    Returns
    -------
    labels : :class:`list`
        Labels for contours (percentiles, if above minimum z value).

    contours : :class:`list`
        Contour height values.
    """
    percentiles = sorted(percentiles, reverse=True)
    # Integral approach from https://stackoverflow.com/a/37932566
    t = np.linspace(0.0, z.max(), resolution)
    integral = ((z >= t[:, None, None]) * z).sum(axis=(1, 2))
    f = scipy.interpolate.interp1d(integral, t)
    try:
        t_contours = f(np.array(percentiles) * z.sum())
        return percentiles, t_contours
    except ValueError:
        logger.debug(
            "Percentile contour below minimum for given resolution"
            "Returning Minimium."
        )
        non_one = integral[~np.isclose(integral, np.ones_like(integral))]
        return ["min"], f(np.array([np.nanmax(non_one)]))


def plot_Z_percentiles(
    xi,
    yi,
    zi,
    percentiles=[0.95, 0.66, 0.33],
    ax=None,
    extent=None,
    fontsize=8,
    cmap=None,
    contour_labels=None,
    label_contours=True,
    **kwargs
):
    """
    Plot percentile contours onto a 2D  (scaled or unscaled) probability density
    distribution Z over X,Y.

    Parameters
    ------------
    z : :class:`numpy.ndarray`
        Probability density function over x, y.
    percentiles : :class:`list`
        Percentile values for which to create contours.
    ax : :class:`matplotlib.axes.Axes`, :code:`None`
        Axes on which to plot. If none given, will create a new Axes instance.
    extent : :class:`list`, :code:`None`
        List or np.ndarray in the form [-x, +x, -y, +y] over which the image extends.
    fontsize : :class:`float`
        Fontsize for the contour labels.
    cmap : :class:`matplotlib.colors.ListedColormap`
        Color map for the contours, contour labels and imshow.
    contour_labels : :class:`dict`
        Labels to assign to contours, organised by level.
    label_contours :class:`bool`
        Whether to add text labels to individual contours.
    Returns
    -------
    :class:`matplotlib.contour.QuadContourSet`
        Plotted and formatted contour set.
    """
    if ax is None:
        fig, ax = plt.subplots(1, figsize=(6, 6))

    if extent is None:
        xmin, xmax = np.min(xi), np.max(xi)
        ymin, ymax = np.min(yi), np.max(yi)
        extent = [xmin, xmax, ymin, ymax]

    clabels, contours = percentile_contour_values_from_meshz(
        zi, percentiles=percentiles
    )
    cs = ax.contour(xi, yi, zi, levels=contours, extent=extent, cmap=cmap, **kwargs)
    if label_contours:
        fs = kwargs.pop("fontsize", None) or 8
        lbls = ax.clabel(cs, fontsize=fs, inline_spacing=0)
        z_contours = sorted(list(set([float(l.get_text()) for l in lbls])))
        trans = {
            float(t): str(p)
            for t, p in zip(z_contours, sorted(percentiles, reverse=True))
        }
        if contour_labels is None:
            _labels = [trans[float(l.get_text())] for l in lbls]
        else:  # get the labels from the dictionary provided
            contour_labels = {str(k): str(v) for k, v in contour_labels.items()}
            _labels = [contour_labels[trans[float(l.get_text())]] for l in lbls]

        [l.set_text(t) for l, t in zip(lbls, _labels)]
    return cs


def nan_scatter(xdata, ydata, ax=None, axes_width=0.2, **kwargs):
    """
    Scatter plot with additional marginal axes to plot data for which data is partially
    missing. Additional keyword arguments are passed to matplotlib.

    Parameters
    -----------
    xdata : :class:`numpy.ndarray`
        X data
    ydata: class:`numpy.ndarray` | pd.Series
        Y data
    ax : :class:`matplotlib.axes.Axes`
        Axes on which to plot.
    axes_width : :class:`float`
        Width of the marginal axes.

    Returns
    -------
    :class:`matplotlib.axes.Axes`
        Axes on which the nan_scatter is plotted.
    """
    if ax is None:
        fig, ax = plt.subplots(1)

    ax.scatter(xdata, ydata, **kwargs)

    if hasattr(ax, "divider"):  # Don't rebuild axes
        div = ax.divider
        nanaxx = div.nanaxx
        nanaxy = div.nanaxy
    else:  # Build axes
        ax.yaxis.set_tick_params(labelleft=False, left=False)
        ax.xaxis.set_tick_params(labelbottom=False, bottom=False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        div = make_axes_locatable(ax)
        ax.divider = div

        nanaxx = div.append_axes("bottom", axes_width, pad=0, sharex=ax)
        div.nanaxx = nanaxx
        nanaxx.invert_yaxis()
        nanaxx.yaxis.set_visible(False)
        nanaxx.spines["left"].set_visible(False)
        nanaxx.spines["right"].set_visible(False)
        nanaxx.set_facecolor("none")

        nanaxy = div.append_axes("left", axes_width, pad=0, sharey=ax)
        div.nanaxy = nanaxy
        nanaxy.invert_xaxis()
        nanaxy.xaxis.set_visible(False)
        nanaxy.spines["top"].set_visible(False)
        nanaxy.spines["bottom"].set_visible(False)
        nanaxy.set_facecolor("none")

    nanxdata = xdata[(np.isnan(ydata) & np.isfinite(xdata))]
    nanydata = ydata[(np.isnan(xdata) & np.isfinite(ydata))]

    yminmax = np.nanmin(ydata), np.nanmax(ydata)
    no_ybins = 50
    ybinwidth = (np.nanmax(ydata) - np.nanmin(ydata)) / no_ybins
    ybins = np.linspace(np.nanmin(ydata), np.nanmax(ydata) + ybinwidth, no_ybins)

    nanaxy.hist(nanydata, bins=ybins, orientation="horizontal", **kwargs)
    nanaxy.scatter(
        10 * np.ones_like(nanydata) + 5 * np.random.randn(len(nanydata)),
        nanydata,
        zorder=-1,
        **kwargs
    )

    xminmax = np.nanmin(xdata), np.nanmax(xdata)
    no_xbins = 50
    xbinwidth = (np.nanmax(xdata) - np.nanmin(xdata)) / no_xbins
    xbins = np.linspace(np.nanmin(xdata), np.nanmax(xdata) + xbinwidth, no_xbins)

    nanaxx.hist(nanxdata, bins=xbins, **kwargs)
    nanaxx.scatter(
        nanxdata,
        10 * np.ones_like(nanxdata) + 5 * np.random.randn(len(nanxdata)),
        zorder=-1,
        **kwargs
    )

    return ax


def save_figure(
    figure, save_at="", name="fig", save_fmts=["png"], output=False, **kwargs
):
    """
    Save a figure at a specified location in a number of formats.
    """
    default_config = dict(dpi=600, bbox_inches="tight", transparent=True)
    config = default_config.copy()
    config.update(kwargs)
    for fmt in save_fmts:
        out_filename = os.path.join(save_at, name + "." + fmt)
        if output:
            logger.info("Saving " + out_filename)
        figure.savefig(out_filename, format=fmt, **config)


def save_axes(ax, save_at="", name="fig", save_fmts=["png"], pad=0.0, **kwargs):
    """
    Save either a single or multiple axes (from a single figure) based on their
    extent. Uses the save_figure procedure to save at a specific location using
    a number of formats.
    """
    # Check if axes is a single axis or list of axes

    if isinstance(ax, matax.Axes):
        extent = get_full_extent(ax, pad=pad)
        figure = ax.figure
    else:
        extent_items = []
        for a in ax:
            extent_items.append(get_full_extent(a, pad=pad))
        figure = ax[0].figure
        extent = Bbox.union([item for item in extent_items])
    save_figure(
        figure,
        bbox_inches=extent,
        save_at=save_at,
        name=name,
        save_fmts=save_fmts,
        **kwargs
    )


def get_full_extent(ax, pad=0.0):
    """Get the full extent of an axes, including axes labels, tick labels, and
    titles. Text objects are first drawn to define the extents.

    Parameters
    -----------
    ax : :class:`matplotlib.axes.Axes`
        Axes of which to check items to get full extent.
    pad : :class:`float` | :class:`tuple`
        Amount of padding to add to the full extent prior to returning. If a tuple is
        passed, the padding will be as above, but for x and y directions, respectively.

    Returns
    --------
    :class:`matplotlib.transforms.Bbox`
        Bbox of the axes with optional additional padding.
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.renderer

    items = [ax]

    if len(ax.get_title()):
        items += [ax.title]

    for a in [ax.xaxis, ax.yaxis]:
        if len(a.get_label_text()):
            items += [a.label]

    for t_lb in [ax.get_xticklabels(), ax.get_yticklabels()]:
        if np.array([len(i.get_text()) > 0 for i in t_lb]).any():
            items += t_lb

    bbox = Bbox.union([item.get_window_extent(renderer) for item in items])
    if isinstance(pad, (float, int)):
        full_extent = bbox.expanded(1.0 + pad, 1.0 + pad)
    elif isinstance(pad, (list, tuple)):
        full_extent = bbox.expanded(1.0 + pad[0], 1.0 + pad[1])
    else:
        raise NotImplementedError
    return full_extent.transformed(ax.figure.dpi_scale_trans.inverted())
