# SPHEREx – Lance's Lookout

A website for spotting things that move or change brightness in NASA's SPHEREx
all-sky survey. Type a star name or coordinates and it shows a looping "blink" of
every SPHEREx visit to that patch of sky, aligned and stacked, so a fast-moving
star or a variable star stands out against the fixed background.

Lance's Lookout was built by The Buttered Croissants for the NASA Space Apps Challenge 2026 (Planet X and SPHEREx challenge).

Daniel George Kyritsis (@daniel0kyritsis-boop)
Hiba Ahsen (@hibahsen)
Meggi Bega Sejdini
Lance Wahlstedt
Hania Sohail
Ophelia Yau

Built for the **Planet X and SPHEREx** challenge. All five required test targets work:

| Target | Type | What you see |
|---|---|---|
| Barnard's Star | moving, ~10″/yr | Moves north across 3 epochs |
| eps Ind B | moving, ~4.7″/yr | Steps south-east across 5 epochs |
| WISE 0855 | moving, ~8″/yr | Faint; only visible on detectors 5–6 (3.8–5 µm). Moves west |
| RW Aur | variable | Brightens between 2025.69 and 2026.70 |
| R Dra | variable | Fades between 2025.47 and 2026.47 (saturated core) |

> **Use of AI.** The code in this repository (Python, the web page and the tests) was
> written with an AI coding assistant, [Claude](https://claude.ai) by Anthropic, working
> under our team's direction. The team chose the challenge approach (blinking SPHEREx
> epochs), made the design decisions, and checked the results against the challenge's
> five test targets. No AI-generated images, audio or video are used, and nothing uses
> NASA branding. See [Credits and data](#credits-and-data) for all other resources.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python prefetch.py --detectors 2                                              # download the 5 test targets
python prefetch.py "WISE J085510.83-071442.5" --detectors 5,6 --out prefetch_wise.json
python make_frames.py                                                          # build their blink frames
python make_frames.py "WISE J085510.83-071442.5" --detectors 5,6
uvicorn server:app --reload                                                    # open http://127.0.0.1:8000
```

The prefetch and frame-building steps are optional: the site downloads and builds
anything it doesn't have yet. They just make the five test targets load instantly.
A new target takes about 1–3 minutes the first time, then loads instantly.

## Using the site

- **Search** any position on the sky, by name (`Proxima Cen`), decimal degrees
  (`269.452 4.693`) or sexagesimal (`17h57m48s +04d41m36s`). Coordinates are ICRS
  RA/Dec (J2000). Names are looked up in SIMBAD, including proper motion, so a
  fast-moving star is centred where it actually was during the SPHEREx observations,
  not at its year-2000 catalogue position.
- **Suggestions:** typing a name shows matching stars as you type (arrow keys + Enter,
  or click). It tolerates typos (`betelguese` → Betelgeuse) and knows common aliases
  (`alpha cen`, `GJ 699`, `WISE 0855`). A name that isn't found gets a "Did you mean"
  list. Any name SIMBAD knows can still be searched; the list only drives suggestions.
- **Spectrum (live):** under the viewer, the target's brightness in every SPHEREx image,
  plotted against wavelength and coloured by epoch. The epoch on screen is highlighted
  and follows the blink. Below it, *Change at matched wavelengths* compares that epoch
  with the average of all epochs bin by bin (bins ~5% wide in wavelength), so a
  brightness change isn't confused with epochs sampling different wavelengths. RW Aur:
  0.75× the average in 2025.69, then 1.00 and 1.02. eps Ind B (not variable): within
  ±3%. Saturated points (blank pixels) are drawn hollow and left out.
- **Famous stars:** a row of quick-access buttons under the test targets, showing only
  the stars already built, so every button loads instantly (Sirius, Betelgeuse,
  Polaris and Proxima Centauri at present). The list in `spherex_data/names.py` has
  17; the others appear once built with `make_frames.py … --detectors auto`. The
  brightest ones saturate SPHEREx's detectors, so they show as large discs with blank
  cores.
- **Modes:**
  - *Frames*: each epoch's stacked image.
  - *Difference*: each epoch minus the median of all epochs. Anything constant cancels
    to grey, so only what moved or changed is left.
  - *Pair*: last epoch minus first. A moving object is a black spot (where it was)
    next to a white spot (where it is now).
- **Detectors** pick the wavelength band (D1 0.75–1.1 µm … D6 4.4–5.0 µm).
  - *Auto* (the default) picks the band where the target stands out most above the
    noise without its core saturating. It samples 3 small images per detector, so a
    new target's first load takes ~20 s longer; the choice is remembered. If the
    target is faint everywhere, it combines the bands where it's detected; if it
    saturates everywhere, it takes the least saturated band. The info card says
    which detector was chosen and why. The five test targets keep detectors chosen
    and checked by hand (D2; D5+6 for WISE 0855).
  - *All* (or any several detectors) stacks each detector separately, then averages
    them weighted by their noise, so quiet detectors count more. SPHEREx's detectors
    work in pairs (1+4, 2+5, 3+6) that see neighbouring patches of sky, so a star
    reaches every band only over a few days; near the ecliptic poles, short epochs
    are merged until each contains every detector, so every frame has the same mix
    of bands.
- **Keys:** `space` play/pause, `←` `→` step, `d` next mode. Hover over the image for RA/Dec.
- **Links:** the address bar always describes the current view, so it can be
  shared or bookmarked. **Copy link** copies it.

URL parameters (also usable to embed the viewer in another page):

| Parameter | Example | Meaning |
|---|---|---|
| `target` | `Barnard's Star` | Name or `"ra dec"` |
| `ra`, `dec` | `269.452`, `4.693` | Coordinates in degrees, instead of `target` |
| `fov` | `0.05` | Field of view in degrees (0.02–0.25; default 0.1) |
| `detectors` | `5,6` or `all` | Which detectors to use (default: chosen automatically) |
| `mode` | `diff` | `frames`, `diff` or `pair` |
| `speed` | `400` | Milliseconds per frame (the slider shows it as faster to the right) |
| `embed` | `1` | Hide everything except the viewer and its controls |

## How it works

| Step | Code | What happens |
|---|---|---|
| Name suggestions | `spherex_data/names.py` | Offline list (`star_names.json`, built by `build_names.py`): the ~450 IAU star names plus ~70 nearby moving stars, brown dwarfs and variables, every one checked against Sesame. Prefix, word and typo matching. |
| Name → position | `spherex_data/targets.py` | CDS Sesame (SIMBAD data) gives position, proper motion and parallax. The five test targets have built-in positions, so the demo never depends on a lookup. |
| Find images | `spherex_data/query.py` | IRSA TAP query for every SPHEREx image whose footprint contains the position. Image lists are cached for 24 h. |
| Download | `spherex_data/fetch.py` | IRSA's cutout service, 10 downloads in parallel with retries. Cutouts are cached on disk; failed downloads are reported, not fatal. |
| Epochs | `spherex_data/epochs.py` | A new epoch starts after a gap of 30+ days (SPHEREx maps the whole sky every ~6 months). Near the ecliptic poles the same spot is seen almost daily, so long gap-free runs are cut into ~30-day bins. |
| Quality flags | `spherex_data/flags.py` | Bit names and meanings are read from each file's FLAGS header (`MSKNnnnn` / `MSKDnnnn`). `SOURCE` and `FULLSAMPLE` are informational and not counted as problems. |
| Best detector | `spherex_data/best.py` | Samples each detector, measures the target's S/N and whether its core is saturated (NaN or OVERFLOW/NONLINEAR flags), and applies the rule above. Choices are kept in `frames/_auto/`. |
| Frames | `spherex_data/frames.py` | Per cutout: subtract the zodiacal-light model, blank broken pixels, reproject onto one north-up grid (3.1″ pixels), subtract the sky. Then median-stack each epoch (several detectors: per detector, then a noise-weighted average) and write PNGs, difference images, `stacks.fits` and `frames.json`. |
| Spectrum | `spherex_data/spectrum.py` | Aperture photometry (12.4″ radius, local sky subtracted) at the target's position on each image's date, with that image's wavelength. Points are binned in wavelength and each epoch is compared with the all-epoch median per bin (bins need 2+ epochs and S/N ≥ 5). Kept in `frames/_spectra/`. |
| API | `server.py` | FastAPI. Builds frames on first request and serves them from `frames/` after that. |
| Web page | `web/index.html` | One self-contained page: search, blink player, modes, URL sync. |

Image display details:

- **Normal frames** use an asinh stretch, so faint stars and very bright ones are
  both visible. All epochs share one brightness scale, so a real brightness change
  shows as one.
- **Difference images** use a linear grey scale at least 10× the noise wide, so noise
  stays a quiet grey and only real changes stand out.
- **Saturated star cores** are blank (NaN) in SPHEREx data. Small enclosed holes
  are filled with their brightest neighbour for display only; `frames.json` records
  how many pixels were filled.

## API

Interactive docs at `/docs` while the server runs.

| Endpoint | Returns |
|---|---|
| `GET /api/targets` | The five test targets, their type, best detectors and whether frames are ready |
| `GET /api/suggest?q=barn` | Star names matching the text so far, with kind and position |
| `GET /api/famous` | The famous-stars quick-access list (pre-built stars only) |
| `GET /api/spectrum?target=…` (or `ra`, `dec`; `refresh=true`) | Every measurement (epoch, detector, wavelength, flux in mJy, saturated/flagged) and each epoch's matched-wavelength change |
| `GET /api/frames?target=…` (or `ra`, `dec`; optional `fov`, `detectors`, `refresh=true`) | Image URLs for each epoch (`url`, `diff_url`), the pair image, dates, image counts, wavelengths and the grid's WCS |
| `GET /api/images?target=…` | Every individual image: time, detector, wavelength at the target, quality flags |
| `GET /frames/<folder>/<file>` | The PNGs and GIFs |

## Command-line tools

| Script | Use |
|---|---|
| `prefetch.py` | Download cutouts into the cache. `--refresh` re-asks IRSA for new images; `--detectors 5,6`; `--out` for the summary file. |
| `make_frames.py` | Build frames for targets from the cache. Writes to `frames/<folder>/`, the same folders the API uses. `--detectors auto` chooses like the website; `--detectors all` combines every detector. Retries when IRSA is briefly unavailable. |
| `plot_epochs.py` | Quick matplotlib figure of a target, one panel per epoch, with the predicted position marked. |
| `make_spectra.py` | Pre-build spectra into `frames/_spectra/` (default: the five test targets). |
| `build_names.py` | Rebuild `spherex_data/star_names.json` (the suggestion list) from the IAU Catalog of Star Names plus the extras listed in the script. Star names: IAU WGSN, CC BY 4.0. |

From Python:

```python
from spherex_data import get_cutouts, frames

cs = get_cutouts("Barnard's Star", detectors=[2])   # also (ra, dec) or "17h57m48s +04d41m36s"
cs.n_epochs, cs.by_epoch()                           # cutouts grouped by epoch
c = cs.cutouts[0]
c.image, c.flags, c.variance, c.zodi, c.wcs          # arrays (MJy/sr) and sky coordinates
c.wavelength_um, c.wavelength_map()                  # wavelength at the target / every pixel
c.flag_summary                                       # named flags, problems at the target

ss = frames.stack_epochs(cs)                         # aligned, stacked epochs
frames.write(ss, "frames/barnards-star")
```

## Keeping up with new data

IRSA adds SPHEREx data roughly weekly, and its search index lags about a day.
Run `python prefetch.py --refresh` daily (cron, Task Scheduler or a GitHub Action),
then `python make_frames.py`, or call `/api/frames?…&refresh=true`.

Settings can be changed with environment variables (see `spherex_data/config.py`):
`SPHEREX_CACHE_DIR` (default `~/.cache/spherex`), `SPHEREX_QUERY_TTL_HOURS`,
`SPHEREX_MAX_WORKERS`, `SPHEREX_HTTP_TIMEOUT_S`, `SPHEREX_HTTP_RETRIES`,
`SPHEREX_MAX_SIZE_DEG`, `SPHEREX_EPOCH_GAP_DAYS`, `SPHEREX_EPOCH_MAX_SPAN_DAYS`,
`SPHEREX_EPOCH_BIN_DAYS`.

## Deploying

The site runs as one Docker container (see `Dockerfile`; it listens on `$PORT`,
default 7860). It needs about 130 MB of memory idle and under 400 MB at worst.

**Render (free):** put this folder in a GitHub repository, then on
[render.com](https://render.com) choose **New → Blueprint** and pick the repository.
`render.yaml` sets up a free Docker web service. Render rebuilds automatically on
every push. Free instances sleep after 15 minutes without visitors and take about
a minute to wake.

**Hugging Face Spaces (needs PRO for Docker):** `deploy_hf.py` publishes there without git:

```bash
pip install huggingface_hub
hf auth login                                   # paste a "write" token from huggingface.co/settings/tokens
python deploy_hf.py YOUR-USERNAME/lances-lookout
```

Pre-built frames for the five test targets and the famous-stars row ship with the app, so they load instantly
even though free hosting wipes its disk on restart. On start-up the server rebuilds
any test target that's missing, in the background (`SPHEREX_WARM_ON_START=0` turns
this off). Other targets are downloaded and built on first request.

## Tests

```bash
pytest -q tests
```

The tests use synthetic FITS files and fake archive responses, so they need no network.

## Known limitations

- **New targets are slow the first time** (1–3 minutes), because every cutout is
  downloaded from IRSA. The request blocks until it's done.
- **Bright stars saturate.** RW Aur, R Dra and Barnard's Star have flagged,
  saturated cores on detector 2, so brightness measurements there are unreliable.
  Longer-wavelength detectors saturate less.
- **Positions in the images are only accurate to one grid pixel (3.1″)**, because
  movement is judged by eye from the stacked images. WISE 0855's last epoch overlaps
  a background star.
- **IRSA outages.** If IRSA's image search is down, the site uses image lists it
  has cached (even old ones) and the pre-built targets still work, but a target it
  has never seen can't be built, and *Auto* falls back to detector 2 (not remembered,
  so it's retried later). Searches give up after 30 s, and after a failure IRSA
  isn't asked again for 5 minutes. A target already built on detector 2 is shown
  straight away instead of waiting to compare detectors.
- **Spectra built during an outage cover only the cached detectors** (the shipped
  ones were built on 15 Nov 2026 while IRSA's search was down: detector 2 for most;
  2, 5 and 6 for WISE 0855). Rebuild with `/api/spectrum?…&refresh=true` or
  `make_spectra.py` when IRSA is up.
- **Spectra of saturated or faint moving targets.** Saturated stars give no
  comparison. A faint mover can pick up light from background stars it passes
  (WISE 0855's 1–1.6 µm points are a background star; its 4–5 µm points, ~0.4–0.75
  mJy, are WISE 0855). Fluxes aren't corrected for light outside the aperture.
- **Each epoch mixes wavelengths within its band(s).** Ordinary field stars change by
  only 1–3% between epochs from this, but very red stars (M dwarfs, Miras, brown
  dwarfs) can change more, so check small brightness changes against neighbours.
- **Name lookup needs the internet.** astroquery's SIMBAD route currently fails
  (SIMBAD returns 404), so lookups go through CDS Sesame. Coordinates and the five
  test targets work offline.

## Credits and data

- **NASA SPHEREx** Level 2 spectral images, from NASA/IPAC's Infrared Science Archive
  ([IRSA](https://irsa.ipac.caltech.edu/Missions/spherex.html)): found with IRSA's
  [TAP service](https://irsa.ipac.caltech.edu/docs/program_interface/TAP.html) and
  downloaded with its cutout service, following IRSA's SPHEREx tutorials.
- **Test targets** from the NASA Space Apps 2026 challenge *Planet X and SPHEREx*.
- **Star names, positions and proper motions:** [CDS Sesame](https://cds.unistra.fr/cgi-bin/Sesame)
  and [SIMBAD](https://simbad.cds.unistra.fr/) (CDS, Strasbourg).
- **Name suggestions:** the IAU Catalog of Star Names (IAU WGSN, CC BY 4.0).
- **Software:** Astropy, reproject, PyVO, Astroquery, NumPy, SciPy, Pillow, Matplotlib,
  Requests, FastAPI and Uvicorn; Docker; hosted on Render; Roboto font from Google Fonts.
- **AI assistance:** code written with Claude (Anthropic), as described at the top.

## Project layout

```
server.py            FastAPI app (API + serves the web page)
Dockerfile           container for hosting (port $PORT, default 7860)
render.yaml          free hosting on Render
deploy_hf.py         publish to a Hugging Face Space
web/index.html       the website
prefetch.py          download / refresh cached cutouts
make_frames.py       build blink frames from the cache
make_spectra.py      build spectra (brightness vs wavelength per epoch)
plot_epochs.py       quick-look matplotlib figure
build_names.py       rebuild the star-name suggestion list
spherex_data/        the library: targets, query, fetch, epochs, flags, core, frames, config
tests/               offline tests
frames/              built frames (generated)
```
