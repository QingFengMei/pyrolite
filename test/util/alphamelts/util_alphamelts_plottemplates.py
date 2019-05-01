import unittest
import pandas as pd
from pyrolite.util.alphamelts.download import install_melts
from pyrolite.util.general import check_perl, temp_path, remove_tempdir
from pyrolite.util.alphamelts.automation import *
from pyrolite.util.alphamelts.plottemplates import *
from pyrolite.util.alphamelts.tables import get_experiments_summary

_env = (
    pyrolite_datafolder(subfolder="alphamelts")
    / "localinstall"
    / "examples"
    / "alphamelts_default_env.txt"
)

_melts = (
    pyrolite_datafolder(subfolder="alphamelts")
    / "localinstall"
    / "examples"
    / "Morb.melts"
)


if not (pyrolite_datafolder(subfolder="alphamelts") / "localinstall").exists():
    install_melts(local=True)  # install melts for example files etc


@unittest.skipIf(not check_perl(), "Perl is not installed.")
class TestTemplates(unittest.TestCase):
    def setUp(self):
        self.dir = temp_path() / ("test_melts_temp" + self.__class__.__name__)
        self.meltsfile = _melts
        self.envfile = _env  # use default

        # create one experiment folder and run the experiment
        self.folder = make_meltsfolder(
            self.meltsfile, "MORB", env=self.envfile, dir=self.dir
        )
        self.process = MeltsProcess(
            meltsfile=self.meltsfile, env=self.envfile, fromdir=str(self.folder)
        )
        self.process.write(3, 1, 4, wait=True, log=False)
        self.process.terminate()

        self.summary = get_experiments_summary(self.dir)

    def test_plot_phasetable(self):
        ax = plot_phasetable(self.summary)  # phasevol

    def test_plot_comptable(self):
        plot_comptable(self.summary)  # liquidcomp

    def test_plot_phase_composition(self):
        plot_phase_composition(self.summary)  # olivine

    def tearDown(self):
        if self.dir.exists():
            remove_tempdir(self.dir)


if __name__ == "__main__":

    unittest.main()
