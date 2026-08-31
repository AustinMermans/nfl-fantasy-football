import numpy as np

from nfl_fantasy_football.calibration import fit_calibrator


def test_beta_calibration_is_monotonic() -> None:
    probability = np.linspace(0.05, 0.95, 100)
    target = (probability > 0.6).astype(int)
    calibrator = fit_calibrator("beta", probability, target)
    calibrated = calibrator.predict(probability)
    assert np.all(np.diff(calibrated) >= 0)
