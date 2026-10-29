"""Generate the synthetic sample files used by the Help tutorials.

Writes tab-separated text files (the format SpecFlow reads) and a zip with all of them to
``src/sersflow/api/web/help/sample/``. The data are invented: no real measurements.

    python scripts/make_help_sample_data.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "src" / "sersflow" / "api" / "web" / "help" / "sample"
RNG = np.random.default_rng(42)


def lorentz(x, pos, fwhm):
    return 1.0 / (1.0 + ((x - pos) / (fwhm / 2.0)) ** 2)


def gauss(x, pos, fwhm):
    return np.exp(-4.0 * np.log(2.0) * ((x - pos) / fwhm) ** 2)


def gl(x, pos, fwhm, m=0.3):
    return m * lorentz(x, pos, fwhm) + (1.0 - m) * gauss(x, pos, fwhm)


def write_xy(path: Path, header: str, x, y) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(header + "\n")
        for xi, yi in zip(x, y):
            fh.write(f"{xi:.4f}\t{yi:.3f}\n")


def sers_spectrum(x, potential_v: float, spikes: bool, scale=1.0):
    """Two bands (1080, 1580 cm-1) that trade intensity with potential, on a fluorescence background."""
    t = (abs(potential_v) - 0.1) / 0.9  # 0..1
    band_a = 5200 * (1.0 - 0.75 * t) * lorentz(x, 1080, 22)
    band_b = 2600 * (0.25 + 1.6 * t) * lorentz(x, 1580, 26)
    minor = 700 * gauss(x, 1350, 40)
    background = 4000 + 3.5 * (x - 400) + 6500 * gauss(x, 1200, 700) * scale
    y = background + band_a + band_b + minor
    y = y + RNG.normal(0, 55, x.size)
    if spikes:
        for pos in RNG.choice(np.arange(60, x.size - 60), size=2, replace=False):
            y[pos] += RNG.uniform(9000, 15000)
            y[pos + 1] += RNG.uniform(1500, 3000)
    return y


def make_sers(out: Path) -> list[Path]:
    x = np.arange(400.0, 2000.0 + 0.5, 1.0)
    paths = []
    for i, pot in enumerate(np.round(np.arange(-0.1, -1.01, -0.1), 2)):
        tag = f"{abs(pot):.1f}".replace(".", "d")
        name = f"AgNP_785nm_1p_2s_pH7_-{tag}VRHE_0d1M_KHCO3_CO2.txt"
        y = sers_spectrum(x, float(pot), spikes=i in (2, 5, 8), scale=1.0 + 0.05 * i)
        p = out / name
        write_xy(p, "Raman shift (cm-1)\tIntensity", x, y)
        paths.append(p)
    return paths


def make_series(out: Path) -> Path:
    """Time series: band at 1580 grows, band at 1080 decays, over 20 time points."""
    x = np.arange(800.0, 1800.0 + 0.5, 2.0)
    path = out / "AgNP_785nm_timeseries_pH7_CO2.txt"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("Raman time (s)\tRaman shift (cm-1)\tIntensity\n")
        for k in range(20):
            t = k * 15.0
            f = k / 19.0
            y = (
                3000 + 2.0 * (x - 800) + 3000 * gauss(x, 1200, 600)
                + 4800 * (1 - 0.7 * f) * lorentz(x, 1080, 22)
                + 2400 * (0.3 + 1.4 * f) * lorentz(x, 1580, 26)
                + RNG.normal(0, 45, x.size)
            )
            for xi, yi in zip(x, y):
                fh.write(f"{t:.1f}\t{xi:.1f}\t{yi:.3f}\n")
    return path


def make_map(out: Path) -> Path:
    """4 x 4 map with a hot spot: band at 1580 is strongest near (3, 2)."""
    x = np.arange(800.0, 1800.0 + 0.5, 2.0)
    path = out / "AgNP_785nm_map_pH7_CO2.txt"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("Raman X (um)\tY (um)\tRaman shift (cm-1)\tIntensity\n")
        for ix in range(4):
            for iy in range(4):
                hot = np.exp(-(((ix - 3) ** 2 + (iy - 2) ** 2) / 2.0))
                y = (
                    2500 + 2.0 * (x - 800) + 2500 * gauss(x, 1200, 600)
                    + 2000 * lorentz(x, 1080, 22) * (0.4 + 0.3 * hot)
                    + 4200 * hot * lorentz(x, 1580, 26)
                    + RNG.normal(0, 45, x.size)
                )
                for xi, yi in zip(x, y):
                    fh.write(f"{ix * 5.0:.1f}\t{iy * 5.0:.1f}\t{xi:.1f}\t{yi:.3f}\n")
    return path


def shirley_step(x, signal, k=0.5):
    """Shirley-like background: step proportional to the integrated signal at higher binding energy."""
    order = np.argsort(x)[::-1]  # high BE first
    cum = np.cumsum(signal[order])
    cum = cum / cum[-1]
    bg = np.empty_like(signal)
    bg[order] = cum
    return k * signal.max() * bg


def make_xps(out: Path) -> list[Path]:
    paths = []
    pots = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4]
    shifts = [0.65, 0.62, 0.68, 0.65, 0.63, 0.67, 0.64, 0.66]  # charging: the sample sits about 0.65 eV too high
    for pot, sh in zip(pots, shifts):
        tag = f"{pot:.1f}".replace(".", "d")
        # C 1s
        x = np.arange(280.0, 296.0 + 0.05, 0.1)
        sig = (
            1000 * gl(x, 284.8 + sh, 1.15)
            + 280 * gl(x, 286.4 + sh, 1.3)
            + 90 * gl(x, 288.8 + sh, 1.3)
        )
        y = 400 + sig + shirley_step(x, sig, 0.08)
        y = RNG.poisson(np.clip(y, 1, None)).astype(float)
        p = out / f"NiFeOx_pH13_{tag}VRHE_C1s.txt"
        write_xy(p, "Binding energy (eV)\tIntensity", x, y)
        paths.append(p)
        # O 1s: hydroxide fraction rises with potential
        x = np.arange(526.0, 536.0 + 0.05, 0.1)
        oh = 0.25 + 0.45 * pot / 1.4
        sig = (
            2400 * (1 - oh) * gl(x, 529.8 + sh, 1.25)
            + 2400 * oh * gl(x, 531.4 + sh, 1.6)
            + 250 * gl(x, 533.0 + sh, 1.8)
        )
        y = 900 + sig + shirley_step(x, sig, 0.10)
        y = RNG.poisson(np.clip(y, 1, None)).astype(float)
        p = out / f"NiFeOx_pH13_{tag}VRHE_O1s.txt"
        write_xy(p, "Binding energy (eV)\tIntensity", x, y)
        paths.append(p)
    return paths


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        if old.is_file():
            old.unlink()
    sers = make_sers(OUT)
    series = make_series(OUT)
    mp = make_map(OUT)
    xps = make_xps(OUT)
    groups = {
        "specflow_sample_sers.zip": sers,
        "specflow_sample_series_and_map.zip": [series, mp],
        "specflow_sample_xps.zip": xps,
    }
    for zname, files in groups.items():
        with zipfile.ZipFile(OUT / zname, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.name)
    # zips are the download; keep loose files out of the repo to stay small
    for f in sers + [series, mp] + xps:
        f.unlink()
    for z in sorted(OUT.glob("*.zip")):
        print(z.name, f"{z.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
