"""Settings for the SPHEREx data layer. Override any of these with environment variables."""
import os
from pathlib import Path

IRSA_BASE = os.environ.get("SPHEREX_IRSA_BASE", "https://irsa.ipac.caltech.edu/")
TAP_URL = os.environ.get("SPHEREX_TAP_URL", "https://irsa.ipac.caltech.edu/TAP")

# Where downloaded cutouts and cached query results live.
CACHE_DIR = Path(os.environ.get("SPHEREX_CACHE_DIR", Path.home() / ".cache" / "spherex"))

# How long a cached image list is trusted before IRSA is asked again.
# IRSA releases new SPHEREx data weekly and its SIA/TAP index lags about a day,
# so 24 hours keeps the tool current without hammering the archive.
QUERY_TTL_HOURS = float(os.environ.get("SPHEREX_QUERY_TTL_HOURS", "24"))

# Parallel downloads. IRSA's own tutorial uses 10 workers.
MAX_WORKERS = int(os.environ.get("SPHEREX_MAX_WORKERS", "10"))
HTTP_TIMEOUT_S = float(os.environ.get("SPHEREX_HTTP_TIMEOUT_S", "60"))
HTTP_RETRIES = int(os.environ.get("SPHEREX_HTTP_RETRIES", "3"))

# Cutout size limits in degrees. A SPHEREx pixel is about 6.2 arcsec.
DEFAULT_SIZE_DEG = 0.1
MAX_SIZE_DEG = float(os.environ.get("SPHEREX_MAX_SIZE_DEG", "0.5"))

# Observations separated by more than this many days count as different epochs.
# The sky is covered once per ~6-month survey, and visits to one spot within a
# survey are bunched together, so a 30-day gap separates surveys cleanly.
EPOCH_GAP_DAYS = float(os.environ.get("SPHEREX_EPOCH_GAP_DAYS", "30"))
# Near the ecliptic poles there are no gaps (the spot is seen nearly every day).
# A gap-free run longer than EPOCH_MAX_SPAN_DAYS is cut into EPOCH_BIN_DAYS bins.
EPOCH_MAX_SPAN_DAYS = float(os.environ.get("SPHEREX_EPOCH_MAX_SPAN_DAYS", "60"))
EPOCH_BIN_DAYS = float(os.environ.get("SPHEREX_EPOCH_BIN_DAYS", "30"))

# The six detector arrays and their approximate wavelength coverage (microns).
DETECTORS = {
    1: (0.75, 1.09),
    2: (1.10, 1.62),
    3: (1.63, 2.41),
    4: (2.42, 3.82),
    5: (3.83, 4.41),
    6: (4.42, 5.00),
}
