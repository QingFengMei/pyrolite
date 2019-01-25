import unittest
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.axes as matax
import matplotlib.pyplot as plt
from pyrolite.comp.codata import close
from pyrolite.util.plot import *
from pyrolite.util.general import remove_tempdir
from scipy.stats import multivariate_normal

try:
    from sklearn.decomposition import PCA

    HAVE_SKLEARN = True
except ImportError:
    HAVE_SKLEARN = False


class TestAddColorbar(unittest.TestCase):
    """
    Tests the add_colorbar utility function.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)
        self.mappable = plt.imshow(np.random.random((10, 10)), cmap=plt.cm.BuPu_r)

    def test_colorbar(self):
        add_colorbar(self.mappable)


class TestModifyLegendHandles(unittest.TestCase):
    """
    Tests the modify_legend_handles utility function.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)
        self.ax.plot(np.random.random(10), np.random.random(10), color="g", label="a")

    def test_modify_legend_handles(self):
        _hndls, labls = modify_legend_handles(self.ax, **{"color": "k"})
        self.assertTrue(_hndls[0].get_color() == "k")


class TestABC2TernXY(unittest.TestCase):
    """
    Tests the ABC_to_tern_xy utility function.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)
        self.data = np.random.random((3, 10))
        self.data = close(self.data)

    def test_ABC_to_tern_xy(self):
        conv = ABC_to_tern_xy(self.data)
        self.assertTrue(len(conv) == 2)  # xd, yd


class TestTernHeatmapCoords(unittest.TestCase):
    """
    Tests the tern_heatmapcoords utility function.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)
        self.data = np.random.random((3, 10))
        self.data = close(self.data)

    def test_tern_heatmapcoords(self):
        coords = tern_heatmapcoords(self.data)
        self.assertTrue(isinstance(coords, dict))
        # need to test completeness of keys


class TestLegendProxies(unittest.TestCase):
    """
    Tests the proxy_rect and proxy_line utility functions.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)

    def test_proxy_rect(self):
        rect = proxy_rect()
        self.assertTrue(isinstance(rect, matplotlib.patches.Polygon))
        self.assertTrue(isinstance(rect, matplotlib.patches.Rectangle))

    def test_proxy_rect(self):
        line = proxy_line()
        self.assertTrue(isinstance(line, matplotlib.lines.Line2D))


@unittest.skipUnless(HAVE_SKLEARN, "Requires Scikit-learn")
class TestDrawVector(unittest.TestCase):
    """
    Tests the draw_vector utility function.
    """

    def setUp(self):
        xs = 1.0 / (np.random.randn(5) + 4)
        self.X = np.array([xs, 1 - xs])
        self.X = close(self.X)

    def test_plot(self):
        fig, ax = plt.subplots(1)
        pca = PCA(n_components=2)
        d = self.X
        pca.fit(d)
        for variance, vector in zip(pca.explained_variance_, pca.components_):
            v = vector[:2] * 3 * np.sqrt(variance)
            draw_vector(pca.mean_[:2], pca.mean_[:2] + v, ax=ax)

    def tearDown(self):
        plt.close("all")


@unittest.skipUnless(HAVE_SKLEARN, "Requires Scikit-learn")
class TestVectorToLine(unittest.TestCase):
    """
    Tests the vector_to_line utility function.
    """

    def setUp(self):
        xs = 1.0 / (np.random.randn(5) + 4)
        self.X = np.array([xs, 1 - xs])
        self.X = close(self.X)

    def test_to_line(self):
        pca = PCA(n_components=2)
        d = self.X
        pca.fit(d)
        for variance, vector in zip(pca.explained_variance_, pca.components_):
            line = vector_to_line(pca.mean_[:2], vector[:2], variance, spans=6)

        self.assertTrue(isinstance(line, np.ndarray))
        self.assertTrue(line.shape[1] == 2)


class Test2DHull(unittest.TestCase):
    """
    Tests the plot_2dhull utility function.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)
        self.data = np.random.random((2, 10)).T

    def test_2d_hull(self):
        lines = plot_2dhull(self.ax, self.data)
        self.assertTrue(isinstance(lines[0], matplotlib.lines.Line2D))


class TestPercentileContourValuesFromMeshZ(unittest.TestCase):
    def setUp(self):
        x, y = np.mgrid[-1:1:100j, -1:1:100j]
        pos = np.empty(x.shape + (2,))
        pos[:, :, 0] = x
        pos[:, :, 1] = y
        self.z = multivariate_normal([0.5, -0.2], [[2.0, 0.3], [0.3, 0.5]]).pdf(pos)

    def test_default(self):
        percentile_contour_values_from_meshz(self.z)

    def test_percentiles(self):
        for ps in [[1.0], [0.001], np.linspace(0.001, 1, 10), [0.95, 0.10]]:
            with self.subTest(ps=ps):
                percentile_contour_values_from_meshz(self.z, percentiles=ps)

    def test_resolution(self):
        for res in [10, 100, 1000, 10000]:
            with self.subTest(res=res):
                percentile_contour_values_from_meshz(self.z, resolution=res)


class TestPlotZPercentiles(unittest.TestCase):
    def setUp(self):
        x, y = np.mgrid[-1:1:100j, -1:1:100j]
        pos = np.empty(x.shape + (2,))
        pos[:, :, 0] = x
        pos[:, :, 1] = y
        self.xi, self.yi = x, y
        self.zi = multivariate_normal([0.5, -0.2], [[2.0, 0.3], [0.3, 0.5]]).pdf(pos)

    def test_default(self):
        plot_Z_percentiles(self.xi, self.yi, self.zi)

    def test_percentiles(self):
        for ps in [[1.0], [0.001], np.linspace(0.001, 1, 10), [0.95, 0.10]]:
            with self.subTest(ps=ps):
                plot_Z_percentiles(self.xi, self.yi, self.zi, percentiles=ps)

    def test_external_ax(self):
        fig, ax = plt.subplots(1)
        plot_Z_percentiles(self.xi, self.yi, self.zi, ax=ax)

    def test_extent(self):
        for extent in [[-1, 1, -1, 1], [-0.01, 0.99, -1.01, -0.01], [-2, 2, -2, -2]]:
            with self.subTest(extent=extent):
                plot_Z_percentiles(self.xi, self.yi, self.zi,  extent=extent)


class TestNaNScatter(unittest.TestCase):
    """
    Tests the nan_scatter utility plotting function.
    """

    def setUp(self):
        self.x = np.random.randn(1000) - 1
        self.y = 2 + np.random.randn(1000)
        self.x[self.x < -1] = np.nan
        self.y[self.y < 2] = np.nan

    def test_plot(self):
        fig, ax = plt.subplots()
        ax = nan_scatter(self.x, self.y, ax=ax)
        self.assertTrue(isinstance(ax, matax.Axes))

    def tearDown(self):
        plt.close("all")


class TestSaveUtilities(unittest.TestCase):
    def setUp(self):
        self.fig, self.ax = plt.subplots(1)

    def test_get_full_extent(self):
        extent = get_full_extent(self.ax)

    def tearDown(self):
        plt.close("all")


class TestSaveFunctions(unittest.TestCase):
    """
    Tests the collection of plot saving functions.
    """

    def setUp(self):
        self.fig, self.ax = plt.subplots(1)
        self.tempdir = Path("./testing_temp_figures")
        if not self.tempdir.exists():
            self.tempdir.mkdir()

    def test_save_figure(self):
        save_figure(self.fig, name="test_fig", save_at=str(self.tempdir))

    def test_save_axes(self):
        save_axes(self.ax, name="test_ax", save_at=str(self.tempdir))

    def tearDown(self):
        remove_tempdir(str(self.tempdir))
        plt.close("all")


if __name__ == "__main__":
    unittest.main()
