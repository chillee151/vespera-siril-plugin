##############################################
# Vespera Pro — Drizzle Preprocessing
# Automated Stacking for Alt-Az Mounts
# Author: Claude (Anthropic) (2025)
# Contact: github.com/anthropics
##############################################
# (c) 2025 - MIT License
# Vespera Pro Drizzle Preprocessing
# Version 2.0.0
#
# Credits / Origin
# ----------------
#   • Based on Siril's OSC_Preprocessing_BayerDrizzle.ssf
#   • Optimized for Vaonis Vespera Pro telescope (Sony IMX676 sensor)
#   • Handles single dark frame capture (Expert Mode)
#   • Dual-band filter support (Ha/OIII extraction)

"""
Overview
--------
Full-featured preprocessing script for Vaonis Vespera Pro astrophotography data.
Designed to handle the unique characteristics of alt-az mounted smart telescopes
including field rotation, various filter configurations, and different sky conditions.

Features
--------
• Bayer Drizzle: Handles field rotation from alt-az tracking without grid artifacts
• Single Dark Support: Automatically detects and handles 1 or multiple dark frames
• Dual-Band Filter: Ha/OIII extraction for narrowband imaging
• Sky Quality Presets: Optimized settings for dark to urban skies
• Sensor Profile: IMX676-specific processing parameters
• Auto Cleanup: Removes all temporary files after successful processing
• Post-Processing Options: Auto background extraction and color calibration
• Apple Silicon Optimized: Parallel frame analysis using M1/M2/M3/M4 Pro cores
• Frame Quality Checker: Detects obstructions, clouds, tracking issues with auto-reject

Compatibility
-------------
• Siril 1.4+
• Python 3.10+ (via sirilpy)
• Dependencies: sirilpy, PyQt6

License
-------
Released under MIT License.
"""

import sys
import os
import glob
import shutil
import traceback
import re

try:
    import sirilpy as s
    from sirilpy import LogColor
except ImportError:
    print("Error: sirilpy module not found. This script must be run within Siril.")
    sys.exit(1)

# Ensure dependencies
s.ensure_installed("PyQt6")
s.ensure_installed("numpy")
s.ensure_installed("astropy")  # For thorough frame analysis
s.ensure_installed("scipy")    # For sharpness detection (Laplacian)

# Optimize numpy for Apple Silicon (M1/M2/M3/M4 Pro)
# These environment variables must be set BEFORE numpy is imported
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")  # Per-worker thread limit
os.environ.setdefault("MKL_NUM_THREADS", "4")       # Intel MKL (if used)
os.environ.setdefault("NUMEXPR_NUM_THREADS", "4")   # NumExpr library

from PyQt6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QProgressBar, QMessageBox,
                             QTextEdit, QGroupBox, QComboBox, QCheckBox,
                             QSpinBox, QDoubleSpinBox, QTabWidget, QWidget,
                             QGridLayout, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

VERSION = "2.2.0"  # Added M4 Pro multiprocessing optimization

##############################################
# CONFIGURATION PRESETS
##############################################

# Vespera Pro Sensor (Sony IMX676)
SENSOR_PROFILE = {
    "name": "Sony IMX676 (Vespera Pro)",
    "bayer_pattern": "GBRG",
    "pixel_size": 2.0,  # microns
    "resolution": (3536, 3536),
    "bit_depth": 12,
    "qe_peak": 0.91,  # 91% quantum efficiency
    # RGB weights for accurate luminance (from VeraLux profiles)
    "lum_weights": (0.25, 0.68, 0.07),  # R, G, B
}

# Sky Quality Presets (Bortle scale)
SKY_PRESETS = {
    "Bortle 1-2 (Excellent Dark)": {
        "description": "Remote dark sites, minimal light pollution",
        "sigma_low": 3.0,
        "sigma_high": 3.0,
        "bg_samples": 6,
        "bg_tolerance": 1.0,
        "gradient_correction": False,
    },
    "Bortle 3-4 (Rural)": {
        "description": "Rural areas, some light domes on horizon",
        "sigma_low": 3.0,
        "sigma_high": 3.0,
        "bg_samples": 9,
        "bg_tolerance": 1.0,
        "gradient_correction": True,
    },
    "Bortle 5-6 (Suburban)": {
        "description": "Suburban skies, noticeable light pollution",
        "sigma_low": 2.5,
        "sigma_high": 3.0,
        "bg_samples": 12,
        "bg_tolerance": 0.8,
        "gradient_correction": True,
    },
    "Bortle 7-8 (Urban)": {
        "description": "City skies, heavy light pollution",
        "sigma_low": 2.0,
        "sigma_high": 2.5,
        "bg_samples": 16,
        "bg_tolerance": 0.5,
        "gradient_correction": True,
    },
}

# Filter configurations
FILTER_CONFIGS = {
    "No Filter (Stock)": {
        "type": "broadband",
        "script": "standard",
        "description": "Standard RGB processing",
    },
    "SVBONY SV220 Dual-Band (Ha/OIII)": {
        "type": "dualband",
        "script": "extract_haoiii",
        "description": "Extracts Ha and OIII channels for HOO palette",
        "ha_channel": "red",
        "oiii_channel": "blue",
    },
    "L-Pro / CLS (Light Pollution)": {
        "type": "broadband_lp",
        "script": "standard",
        "description": "Broadband with LP suppression - standard RGB processing",
    },
    "Ha Narrowband": {
        "type": "narrowband",
        "script": "extract_ha",
        "description": "Extracts Ha channel only (monochrome output)",
    },
    "OIII Narrowband": {
        "type": "narrowband",
        "script": "extract_oiii",
        "description": "Extracts OIII channel only (monochrome output)",
    },
}

# Mosaic/CovalENS mode settings
MOSAIC_SETTINGS = {
    "pre_stack_gradient": True,     # seqsubsky before stacking
    "overlap_norm": True,           # -overlap_norm in stack
    "default_feather": 30,          # pixels for edge blending
    "aggressive_bge": True,         # two-stage BGE post-processing
}


def detect_covalens_mode(folder_path):
    """
    Detect CovalENS mosaic mode from Vespera folder naming convention.

    Non-mosaic: 2026-01-01_09-34-24_observation_M42
    CovalENS:   2026-01-17_07-07-25_observation_NGC2237_44

    The _XX suffix (typically a number) indicates CovalENS/balens mosaic mode.

    Returns: (is_covalens: bool, panel_info: str or None, target_name: str or None)
    """
    folder_name = os.path.basename(folder_path.rstrip('/\\'))

    # Pattern: date_time_observation_TARGET or date_time_observation_TARGET_NUMBER
    # The _NUMBER suffix indicates CovalENS mode
    # Note: Target names can contain underscores (e.g., NGC_2237) so we match greedily
    pattern = r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_observation_(.+?)_(\d+)$'
    match = re.match(pattern, folder_name)

    if match:
        target = match.group(1)
        panel_info = match.group(2)
        return True, panel_info, target

    # Try pattern without number suffix (non-CovalENS)
    pattern_simple = r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_observation_(.+)$'
    match_simple = re.match(pattern_simple, folder_name)

    if match_simple:
        target = match_simple.group(1)
        return False, None, target

    return False, None, None


def is_icloud_placeholder(filepath):
    """
    Check if a file is an iCloud placeholder (not downloaded locally).

    On macOS, iCloud Drive files that haven't been downloaded have a
    companion .icloud file. This is a FAST check - no subprocess calls.
    """
    # Check for .icloud placeholder file - this is instant (just a stat call)
    dirname = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    icloud_placeholder = os.path.join(dirname, f".{basename}.icloud")
    return os.path.exists(icloud_placeholder)


def count_icloud_placeholders(directory):
    """
    Count how many files in a directory are iCloud placeholders.
    Returns (placeholder_count, total_fits_count).
    """
    placeholder_count = 0
    fits_files = []

    for pattern in ['*.fits', '*.fit', '*.FITS', '*.FIT']:
        fits_files.extend(glob.glob(os.path.join(directory, pattern)))

    # Exclude dark files
    fits_files = [f for f in fits_files if '-dark' not in os.path.basename(f).lower()]

    for f in fits_files:
        if is_icloud_placeholder(f):
            placeholder_count += 1

    return placeholder_count, len(fits_files)


def trigger_icloud_download(directory):
    """
    Trigger iCloud to download all files in a directory.
    Uses 'brctl download' command on macOS.
    Returns True if command was executed, False otherwise.
    """
    import subprocess
    try:
        # brctl download triggers iCloud to download files
        subprocess.run(['brctl', 'download', directory], check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def analyze_frame_quality(fits_dir, log_callback=None):
    """
    Analyze frames in a directory and return quality scores.

    Uses brightness anomaly detection to identify frames that may be
    obstructed (darker than normal) or affected by clouds (brighter).

    This is a FAST version that reads only a tiny sample from each file
    to avoid freezing the UI on large datasets.

    Args:
        fits_dir: Directory containing FITS files
        log_callback: Optional function to call with log messages

    Returns:
        List of (filename, score, issues) tuples sorted by filename
        Also returns (session_median, session_std, total_frames)
    """
    import numpy as np

    def log(msg):
        if log_callback:
            log_callback(msg)

    # Find all FITS files
    fits_files = []
    for pattern in ['*.fits', '*.fit', '*.FITS', '*.FIT']:
        fits_files.extend(glob.glob(os.path.join(fits_dir, pattern)))

    # Exclude dark files
    fits_files = [f for f in fits_files if '-dark' not in os.path.basename(f).lower()]
    fits_files = sorted(fits_files)

    total_files = len(fits_files)
    if total_files < 3:
        log(f"Not enough frames to analyze ({total_files} found)")
        return [], (0, 0, total_files)

    # Quick iCloud check - just look for .icloud placeholder files (instant)
    icloud_dir = os.path.dirname(fits_files[0]) if fits_files else ""
    icloud_files = glob.glob(os.path.join(icloud_dir, ".*.icloud"))
    if icloud_files:
        log(f"WARNING: {len(icloud_files)} files may be in iCloud - download first!")

    log(f"Analyzing {total_files} frames...")

    # Read a small sample from each file to detect brightness anomalies
    # We read from a fixed offset to skip FITS headers
    SAMPLE_OFFSET = 100000  # 100KB into file (well past headers)
    SAMPLE_SIZE = 4000      # Read 4KB (2000 uint16 values) - very small

    brightness_values = []

    for i, fits_file in enumerate(fits_files):
        try:
            # Quick brightness sample
            with open(fits_file, 'rb') as f:
                f.seek(SAMPLE_OFFSET)
                raw = f.read(SAMPLE_SIZE)

            # Sum bytes as quick brightness proxy (faster than numpy)
            brightness = sum(raw)
            brightness_values.append((fits_file, float(brightness)))

            # Progress update every 50 frames (more granular to find stuck point)
            if (i + 1) % 50 == 0 or (i + 1) == total_files:
                log(f"  Scanned {i + 1}/{total_files} frames...")

        except Exception as e:
            # Log which file failed and why
            log(f"  WARNING: Failed to read {os.path.basename(fits_file)}: {e}")
            continue

    if len(brightness_values) < 3:
        log("Not enough readable frames")
        return [], (0, 0, total_files)

    log(f"Calculating statistics for {len(brightness_values)} frames...")

    # Calculate session statistics
    all_brightness = np.array([b for _, b in brightness_values])
    session_median = float(np.median(all_brightness))
    session_std = float(np.std(all_brightness))

    # Avoid division by zero
    if session_std < 1:
        session_std = 1.0

    log(f"Brightness stats: median={session_median:.0f}, std={session_std:.1f}")
    log("Scoring frames...")

    # Score frames based on brightness deviation
    results = []
    good_count = 0
    marginal_count = 0
    bad_count = 0

    for fits_file, brightness in brightness_values:
        issues = []
        score = 100

        # Check brightness deviation using z-score
        z_score = (brightness - session_median) / session_std

        if z_score < -3:
            issues.append(f"Very dark (z={z_score:.1f}) - possible obstruction")
            score = max(0, score - 50)
        elif z_score < -2:
            issues.append(f"Darker than normal (z={z_score:.1f})")
            score = max(0, score - 25)
        elif z_score > 3:
            issues.append(f"Very bright (z={z_score:.1f}) - possible clouds")
            score = max(0, score - 40)
        elif z_score > 2:
            issues.append(f"Brighter than normal (z={z_score:.1f})")
            score = max(0, score - 15)

        if score >= 80:
            good_count += 1
        elif score >= 50:
            marginal_count += 1
        else:
            bad_count += 1

        results.append((os.path.basename(fits_file), score, issues, brightness))

    log(f"Summary: {good_count} good, {marginal_count} marginal, {bad_count} flagged")

    return results, (session_median, session_std, total_files)


def _analyze_single_frame(fits_file):
    """
    Analyze a single FITS frame and return metrics.

    This is a standalone function (not a method) so it can be pickled
    for multiprocessing on M4 Pro and similar multi-core systems.

    Args:
        fits_file: Path to FITS file

    Returns:
        Tuple of (fits_file, metrics_dict, None) on success
        Tuple of (fits_file, None, error_string) on error
    """
    # Import inside function for multiprocessing worker isolation
    import numpy as np
    try:
        from astropy.io import fits as astropy_fits
    except ImportError as e:
        return (fits_file, None, f"astropy import failed: {e}")
    try:
        from scipy import ndimage
    except ImportError as e:
        return (fits_file, None, f"scipy import failed: {e}")

    try:
        # memmap=False required for FITS with BZERO/BSCALE/BLANK headers (Vespera format)
        with astropy_fits.open(fits_file, memmap=False) as hdul:
            data = hdul[0].data

            if data is None:
                return (fits_file, None, "No data in FITS file")

            # Handle 3D data (color) by using luminance
            if len(data.shape) == 3:
                # RGB or multi-channel - use mean across channels
                data = np.mean(data, axis=0)

            # Convert to float for calculations
            data = data.astype(np.float32)

            # === METRICS ===

            # 1. Brightness: median value (robust to outliers)
            brightness = float(np.median(data))

            # 2. Background noise: standard deviation of darkest 20%
            flat = data.flatten()
            percentile_20 = np.percentile(flat, 20)
            dark_pixels = flat[flat <= percentile_20]
            noise = float(np.std(dark_pixels)) if len(dark_pixels) > 100 else 0

            # 3. Star count: count peaks above threshold
            # Use a simple peak detection: pixels significantly above local median
            threshold = brightness + 5 * noise
            bright_pixels = np.sum(data > threshold)
            # Rough star count (each star is ~10-50 pixels depending on seeing)
            star_estimate = bright_pixels // 25

            # 4. Sharpness: high-frequency content via Laplacian
            # Higher values = sharper image
            laplacian = ndimage.laplace(data[::4, ::4])  # Subsample for speed
            sharpness = float(np.var(laplacian))

            # 5. Gradient: check for uneven illumination
            # Compare corners to center
            h, w = data.shape
            corner_size = min(h, w) // 8
            corners = [
                data[:corner_size, :corner_size],           # top-left
                data[:corner_size, -corner_size:],          # top-right
                data[-corner_size:, :corner_size],          # bottom-left
                data[-corner_size:, -corner_size:],         # bottom-right
            ]
            center = data[h//3:2*h//3, w//3:2*w//3]
            corner_mean = np.mean([np.median(c) for c in corners])
            center_mean = np.median(center)
            gradient = abs(corner_mean - center_mean) / max(brightness, 1)

            metrics = {
                'brightness': brightness,
                'noise': noise,
                'star_estimate': star_estimate,
                'sharpness': sharpness,
                'gradient': gradient,
            }

            return (fits_file, metrics, None)

    except Exception as e:
        return (fits_file, None, str(e))


def analyze_frame_quality_thorough(fits_dir, log_callback=None, use_parallel=True):
    """
    Thorough frame quality analysis using astropy to read full FITS data.

    Optimized for Apple Silicon (M4 Pro, etc.) using multiprocessing for
    parallel analysis across multiple cores.

    Analyzes multiple quality metrics:
    - Brightness (median pixel value)
    - Star count (peaks above threshold)
    - Background noise level
    - Image sharpness (high-frequency content)
    - Gradient (vignetting/light pollution detection)

    Args:
        fits_dir: Directory containing FITS files
        log_callback: Optional function to call with log messages
        use_parallel: Use multiprocessing (default True, best for M4 Pro)

    Returns:
        List of (filename, score, issues, metrics) tuples sorted by filename
        Also returns stats dict with session statistics
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import multiprocessing
    import numpy as np

    def log(msg):
        if log_callback:
            log_callback(msg)

    # Find all FITS files
    fits_files = []
    for pattern in ['*.fits', '*.fit', '*.FITS', '*.FIT']:
        fits_files.extend(glob.glob(os.path.join(fits_dir, pattern)))

    # Exclude dark files
    fits_files = [f for f in fits_files if '-dark' not in os.path.basename(f).lower()]
    fits_files = sorted(fits_files)

    total_files = len(fits_files)
    if total_files < 3:
        log(f"Not enough frames to analyze ({total_files} found)")
        return [], {}

    # Determine number of workers - M4 Pro has 10-14 cores
    # Use performance cores minus 2 to leave headroom for UI
    cpu_count = multiprocessing.cpu_count()
    # For Apple Silicon, we want to use most cores but leave some for responsiveness
    max_workers = max(2, cpu_count - 2)

    log(f"Thorough analysis of {total_files} frames...")
    if use_parallel and total_files >= 10:
        log(f"  Using {max_workers} parallel threads (optimized for Apple Silicon)")
    else:
        log("  Using single-threaded mode")

    # Collect metrics for all frames
    frame_metrics = []
    errors = []

    first_error = None  # Track first error for diagnostics

    if use_parallel and total_files >= 10:
        # Parallel processing using ThreadPoolExecutor
        # Note: Using threads instead of processes because:
        # 1. Siril's Python environment has issues with process spawning
        # 2. astropy releases GIL during I/O operations
        # 3. numpy releases GIL for most array operations
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all files for parallel processing
            future_to_file = {executor.submit(_analyze_single_frame, f): f for f in fits_files}

            for future in as_completed(future_to_file):
                fits_file = future_to_file[future]
                try:
                    result = future.result()
                    fits_path, metrics, error = result

                    if metrics is not None:
                        frame_metrics.append((fits_path, metrics))
                    else:
                        errors.append(os.path.basename(fits_path))
                        if first_error is None and error:
                            first_error = error

                except Exception as e:
                    errors.append(f"{os.path.basename(fits_file)}: {e}")
                    if first_error is None:
                        first_error = str(e)

                completed += 1
                # Progress update every 25 frames or at milestones
                if completed % 25 == 0 or completed == total_files:
                    log(f"  Analyzed {completed}/{total_files} frames...")
    else:
        # Sequential processing for small datasets or when parallel disabled
        for i, fits_file in enumerate(fits_files):
            result = _analyze_single_frame(fits_file)
            fits_path, metrics, error = result

            if metrics is not None:
                frame_metrics.append((fits_path, metrics))
            else:
                errors.append(os.path.basename(fits_path))
                if first_error is None and error:
                    first_error = error

            # Progress update every 10 frames
            if (i + 1) % 10 == 0 or (i + 1) == total_files:
                log(f"  Analyzed {i + 1}/{total_files} frames...")

    if errors:
        log(f"  WARNING: {len(errors)} frames failed to analyze")
        if first_error:
            log(f"  First error: {first_error}")

    if len(frame_metrics) < 3:
        log("Not enough readable frames")
        return [], {}

    log("Calculating session statistics...")

    # Calculate session-wide statistics for each metric
    all_brightness = np.array([m['brightness'] for _, m in frame_metrics])
    all_noise = np.array([m['noise'] for _, m in frame_metrics])
    all_stars = np.array([m['star_estimate'] for _, m in frame_metrics])
    all_sharpness = np.array([m['sharpness'] for _, m in frame_metrics])
    all_gradient = np.array([m['gradient'] for _, m in frame_metrics])

    stats = {
        'brightness': {'median': np.median(all_brightness), 'std': np.std(all_brightness)},
        'noise': {'median': np.median(all_noise), 'std': np.std(all_noise)},
        'stars': {'median': np.median(all_stars), 'std': np.std(all_stars)},
        'sharpness': {'median': np.median(all_sharpness), 'std': np.std(all_sharpness)},
        'gradient': {'median': np.median(all_gradient), 'std': np.std(all_gradient)},
        'total_frames': total_files,
    }

    log(f"Session stats:")
    log(f"  Brightness: {stats['brightness']['median']:.0f} ± {stats['brightness']['std']:.0f}")
    log(f"  Stars: {stats['stars']['median']:.0f} ± {stats['stars']['std']:.0f}")
    log(f"  Sharpness: {stats['sharpness']['median']:.1f} ± {stats['sharpness']['std']:.1f}")

    # Score each frame
    results = []
    good_count = 0
    marginal_count = 0
    bad_count = 0

    for fits_file, metrics in frame_metrics:
        issues = []
        score = 100

        # Brightness check (z-score)
        if stats['brightness']['std'] > 0:
            z_bright = (metrics['brightness'] - stats['brightness']['median']) / stats['brightness']['std']
            if z_bright < -3:
                issues.append(f"Very dark (z={z_bright:.1f}) - obstruction?")
                score -= 40
            elif z_bright < -2:
                issues.append(f"Dark (z={z_bright:.1f})")
                score -= 20
            elif z_bright > 3:
                issues.append(f"Very bright (z={z_bright:.1f}) - clouds?")
                score -= 30
            elif z_bright > 2:
                issues.append(f"Bright (z={z_bright:.1f})")
                score -= 10

        # Star count check
        if stats['stars']['std'] > 0 and stats['stars']['median'] > 10:
            z_stars = (metrics['star_estimate'] - stats['stars']['median']) / stats['stars']['std']
            if z_stars < -2.5:
                issues.append(f"Few stars ({metrics['star_estimate']:.0f} vs {stats['stars']['median']:.0f})")
                score -= 30
            elif z_stars < -1.5:
                issues.append(f"Below avg stars ({metrics['star_estimate']:.0f})")
                score -= 10

        # Sharpness check (lower = blurry)
        if stats['sharpness']['std'] > 0:
            z_sharp = (metrics['sharpness'] - stats['sharpness']['median']) / stats['sharpness']['std']
            if z_sharp < -2.5:
                issues.append(f"Blurry (sharpness {metrics['sharpness']:.1f})")
                score -= 25
            elif z_sharp < -1.5:
                issues.append(f"Soft focus")
                score -= 10

        # Gradient check (vignetting or light pollution)
        if metrics['gradient'] > 0.15:
            issues.append(f"Strong gradient ({metrics['gradient']:.1%})")
            score -= 15
        elif metrics['gradient'] > 0.10:
            issues.append(f"Moderate gradient")
            score -= 5

        # Noise check (high noise = short exposure or hot sensor)
        if stats['noise']['std'] > 0:
            z_noise = (metrics['noise'] - stats['noise']['median']) / stats['noise']['std']
            if z_noise > 3:
                issues.append(f"High noise")
                score -= 15

        score = max(0, score)

        if score >= 80:
            good_count += 1
        elif score >= 50:
            marginal_count += 1
        else:
            bad_count += 1

        results.append((os.path.basename(fits_file), score, issues, metrics))

    log(f"Summary: {good_count} good, {marginal_count} marginal, {bad_count} flagged")

    return results, stats


class FrameAnalysisThread(QThread):
    """Background thread for frame quality analysis to prevent UI freezing"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list, tuple)

    def __init__(self, lights_dir, thorough=False):
        super().__init__()
        self.lights_dir = lights_dir
        self.thorough = thorough

    def run(self):
        """Run analysis in background thread"""
        def log_with_yield(msg):
            """Emit progress and yield to allow signal processing"""
            self.progress.emit(msg)
            self.msleep(10)  # Small delay to allow UI updates

        try:
            if self.thorough:
                self.progress.emit("Starting thorough frame analysis...")
                self.msleep(50)
                results, stats = analyze_frame_quality_thorough(
                    self.lights_dir,
                    log_callback=log_with_yield
                )
                # Convert stats dict to tuple format for compatibility
                if stats:
                    stats_tuple = (
                        stats['brightness']['median'],
                        stats['brightness']['std'],
                        stats['total_frames']
                    )
                else:
                    stats_tuple = (0, 0, 0)
                self.finished.emit(results, stats_tuple)
            else:
                self.progress.emit("Starting quick frame analysis...")
                self.msleep(50)
                results, stats = analyze_frame_quality(
                    self.lights_dir,
                    log_callback=log_with_yield
                )
                self.finished.emit(results, stats)
        except Exception as e:
            self.progress.emit(f"Analysis error: {e}")
            import traceback
            self.progress.emit(traceback.format_exc())
            self.finished.emit([], (0, 0, 0))


# Stacking methods with tooltips explaining technical details
STACKING_METHODS = {
    "Bayer Drizzle (Recommended)": {
        "description": "Best for field rotation, gaussian kernel for smooth CFA",
        "tooltip": (
            "Uses Gaussian drizzle kernel with area-based interpolation.\n\n"
            "• Gaussian kernel: Produces smooth, centrally-peaked PSFs\n"
            "• Area interpolation: Reduces moiré patterns from field rotation\n"
            "• Best choice for typical Vespera Pro sessions with 10-15° rotation\n\n"
            "Technical: scale=1.0, pixfrac=1.0, kernel=gaussian, interp=area"
        ),
        "use_drizzle": True,
        "drizzle_scale": 1.0,
        "drizzle_pixfrac": 1.0,
        "drizzle_kernel": "gaussian",
        "interp": "area",
    },
    "Bayer Drizzle (Square)": {
        "description": "Classic drizzle kernel, mathematically flux-preserving",
        "tooltip": (
            "Uses classic square drizzle kernel (original HST algorithm).\n\n"
            "• Square kernel: Mathematically flux-preserving by construction\n"
            "• May show subtle grid patterns with significant field rotation\n"
            "• Better for photometry applications\n\n"
            "Technical: scale=1.0, pixfrac=1.0, kernel=square, interp=area"
        ),
        "use_drizzle": True,
        "drizzle_scale": 1.0,
        "drizzle_pixfrac": 1.0,
        "drizzle_kernel": "square",
        "interp": "area",
    },
    "Bayer Drizzle (Nearest)": {
        "description": "Nearest-neighbor interpolation to minimize moiré patterns",
        "tooltip": (
            "Uses nearest-neighbor interpolation to eliminate moiré.\n\n"
            "• Nearest interpolation: No interpolation artifacts at CFA boundaries\n"
            "• May appear slightly blocky at pixel level\n"
            "• Try this if other methods show checkerboard patterns\n\n"
            "Technical: scale=1.0, pixfrac=1.0, kernel=gaussian, interp=nearest"
        ),
        "use_drizzle": True,
        "drizzle_scale": 1.0,
        "drizzle_pixfrac": 1.0,
        "drizzle_kernel": "gaussian",
        "interp": "nearest",
    },
    "Standard Registration": {
        "description": "Faster processing, good for short sessions with minimal rotation",
        "tooltip": (
            "Standard debayer-then-register workflow (no drizzle).\n\n"
            "• Faster processing, lower memory usage\n"
            "• Works well for sessions under 30 minutes\n"
            "• May show field rotation artifacts at image edges\n"
            "• Not recommended for sessions with >5° total rotation"
        ),
        "use_drizzle": False,
    },
    "Drizzle 2x Upscale": {
        "description": "Doubles resolution, requires many well-dithered frames (50+)",
        "tooltip": (
            "Upscales to 2x resolution using drizzle algorithm.\n\n"
            "• Requires 50+ frames with good sub-pixel dithering\n"
            "• Output will be 7072x7072 pixels (vs 3536x3536)\n"
            "• Uses square kernel (only valid choice for scale>1)\n"
            "• Significantly increased processing time and file sizes\n\n"
            "Note: Lanczos kernels cannot be used with scale>1.0\n"
            "Technical: scale=2.0, pixfrac=1.0, kernel=square, interp=area"
        ),
        "use_drizzle": True,
        "drizzle_scale": 2.0,
        "drizzle_pixfrac": 1.0,
        "drizzle_kernel": "square",
        "interp": "area",
    },
}

##############################################
# DARK STYLESHEET
##############################################

DARK_STYLESHEET = """
QDialog { background-color: #2b2b2b; color: #e0e0e0; }
QTabWidget::pane { border: 1px solid #444444; background-color: #2b2b2b; }
QTabBar::tab { 
    background-color: #3c3c3c; 
    color: #aaaaaa; 
    padding: 8px 16px; 
    border: 1px solid #444444;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected { background-color: #2b2b2b; color: #ffffff; }
QTabBar::tab:hover { background-color: #444444; }

QGroupBox { 
    border: 1px solid #444444; 
    margin-top: 12px; 
    font-weight: bold; 
    border-radius: 4px; 
    padding-top: 8px;
}
QGroupBox::title { 
    subcontrol-origin: margin; 
    left: 10px; 
    padding: 0 5px; 
    color: #88aaff; 
}

QLabel { color: #cccccc; font-size: 10pt; }
QLabel#title { color: #88aaff; font-size: 14pt; font-weight: bold; }
QLabel#subtitle { color: #888888; font-size: 9pt; }
QLabel#status { color: #ffcc00; font-size: 10pt; }
QLabel#success { color: #88ff88; }
QLabel#error { color: #ff8888; }
QLabel#info { color: #88aaff; font-size: 9pt; }

QComboBox {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 5px 10px;
    min-width: 200px;
}
QComboBox:hover { border-color: #88aaff; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { 
    width: 0; height: 0; 
    border-left: 5px solid transparent; 
    border-right: 5px solid transparent; 
    border-top: 6px solid #aaaaaa; 
}
QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    color: #ffffff;
    selection-background-color: #285299;
    border: 1px solid #555555;
}

QCheckBox { color: #cccccc; spacing: 8px; }
QCheckBox::indicator { 
    width: 16px; height: 16px; 
    border: 1px solid #666666; 
    background: #3c3c3c; 
    border-radius: 3px; 
}
QCheckBox::indicator:checked { 
    background-color: #285299; 
    border: 1px solid #88aaff; 
}
QCheckBox::indicator:hover { border-color: #88aaff; }

QSpinBox, QDoubleSpinBox {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 4px;
}

QProgressBar { 
    border: 1px solid #555555; 
    border-radius: 4px; 
    background-color: #3c3c3c;
    text-align: center;
    color: #ffffff;
    min-height: 20px;
}
QProgressBar::chunk { background-color: #285299; border-radius: 3px; }

QPushButton { 
    background-color: #444444; 
    color: #dddddd; 
    border: 1px solid #666666; 
    border-radius: 4px; 
    padding: 8px 20px;
    font-weight: bold;
    min-width: 100px;
}
QPushButton:hover { background-color: #555555; border-color: #777777; }
QPushButton:pressed { background-color: #333333; }
QPushButton:disabled { background-color: #333333; color: #666666; }

QPushButton#start { background-color: #285299; border: 1px solid #1e3f7a; }
QPushButton#start:hover { background-color: #3366bb; }
QPushButton#start:disabled { background-color: #1a1a2e; color: #555555; }

QTextEdit {
    background-color: #1e1e1e;
    color: #aaaaaa;
    border: 1px solid #444444;
    border-radius: 4px;
    font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
    font-size: 9pt;
    padding: 5px;
}

QFrame#separator {
    background-color: #444444;
    min-height: 1px;
    max-height: 1px;
}
"""

##############################################
# PROCESSING THREAD
##############################################

class ProcessingThread(QThread):
    """Background thread for preprocessing"""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, siril, workdir, settings, folder_structure):
        super().__init__()
        self.siril = siril
        self.workdir = workdir
        self.settings = settings
        self.folder_structure = folder_structure  # 'native' or 'organized'
        
    def run(self):
        try:
            self._process()
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")
            traceback.print_exc()
    
    def _log(self, msg):
        self.log.emit(msg)
        try:
            self.siril.log(f"VesperaPro: {msg}")
        except:
            pass
    
    def _process(self):
        # Extract settings
        filter_config = FILTER_CONFIGS[self.settings["filter"]]
        sky_preset = SKY_PRESETS[self.settings["sky_quality"]]
        stack_method = STACKING_METHODS[self.settings["stacking_method"]]

        sigma_low = sky_preset["sigma_low"]
        sigma_high = sky_preset["sigma_high"]
        use_drizzle = stack_method["use_drizzle"]

        # Define paths based on folder structure
        process_dir = os.path.join(self.workdir, "process")
        masters_dir = os.path.join(self.workdir, "masters")

        if self.folder_structure == 'native':
            # Native Vespera structure: dark in root, lights in 01-images-initial
            darks_dir = self.workdir  # Dark is in root
            lights_dir = os.path.join(self.workdir, "01-images-initial")
            # For Siril convert, we need exact prefix - find the dark file pattern
            dark_convert_pattern = "img-0001-dark"  # Vespera names darks as img-XXXX-dark
            dark_seq_name = "dark"  # Sequence name after convert
            # Light pattern: use "img-" prefix (TIFFs are moved before this step)
            light_convert_pattern = "img-"
            light_seq_name = "img-"  # Sequence name after convert
        else:
            # Organized structure: darks/ and lights/ folders
            darks_dir = os.path.join(self.workdir, "darks")
            lights_dir = os.path.join(self.workdir, "lights")
            dark_convert_pattern = "dark"
            dark_seq_name = "dark"
            light_convert_pattern = "light"
            light_seq_name = "light"

        # Verify folders exist
        if not os.path.exists(darks_dir):
            self.finished.emit(False, f"Dark folder not found: {darks_dir}")
            return
        if not os.path.exists(lights_dir):
            self.finished.emit(False, f"Light folder not found: {lights_dir}")
            return

        os.makedirs(process_dir, exist_ok=True)
        os.makedirs(masters_dir, exist_ok=True)

        # Count files
        if self.folder_structure == 'native':
            num_darks = len([f for f in glob.glob(os.path.join(darks_dir, "*.fits")) +
                            glob.glob(os.path.join(darks_dir, "*.fit"))
                            if '-dark' in f.lower()])
            num_lights = len([f for f in glob.glob(os.path.join(lights_dir, "*.fits")) +
                             glob.glob(os.path.join(lights_dir, "*.fit"))
                             if '-dark' not in f.lower()])
        else:
            num_darks = self._count_fits(darks_dir)
            num_lights = self._count_fits(lights_dir)

        self._log(f"Configuration: {self.settings['filter']}")
        self._log(f"Sky Quality: {self.settings['sky_quality']}")
        self._log(f"Stacking: {self.settings['stacking_method']}")
        self._log(f"Structure: {self.folder_structure}")
        self._log(f"Found {num_darks} dark(s), {num_lights} light(s)")

        if num_darks == 0:
            self.finished.emit(False, "No dark frames found")
            return
        if num_lights == 0:
            self.finished.emit(False, "No light frames found")
            return

        # === CLEANUP ===
        self.progress.emit(5, "Cleaning previous files...")
        if not self.settings["keep_temp_files"]:
            self._cleanup_folder(process_dir)
            self._cleanup_folder(masters_dir)

        # === DARK PROCESSING ===
        self.progress.emit(10, "Processing darks...")

        if self.folder_structure == 'native':
            # Native: for single dark, load directly and save to masters
            if num_darks == 1:
                self._log("Single dark → using directly as master")
                # Find the dark file and load it directly
                dark_files = glob.glob(os.path.join(self.workdir, "*-dark.fits")) + \
                            glob.glob(os.path.join(self.workdir, "*-dark.fit"))
                if dark_files:
                    dark_file = os.path.basename(dark_files[0])
                    dark_name = os.path.splitext(dark_file)[0]  # Remove extension
                    self.siril.cmd("load", dark_name)
                    self.siril.cmd("save", "masters/dark_stacked")
            else:
                # Multiple darks - convert and stack
                self.siril.cmd("convert", dark_convert_pattern, "-out=masters")
                self.siril.cmd("cd", "masters")
                self._log(f"Stacking {num_darks} darks...")
                self.siril.cmd("stack", dark_seq_name, "rej",
                              str(sigma_low), str(sigma_high),
                              "-nonorm", "-out=dark_stacked")
                self.siril.cmd("cd", "..")
        else:
            # Organized: convert from darks folder
            self.siril.cmd("cd", "darks")
            self.siril.cmd("convert", dark_convert_pattern, "-out=../masters")
            self.siril.cmd("cd", "../masters")

            if num_darks == 1:
                self._log("Single dark → using directly as master")
                self.siril.cmd("load", f"{dark_seq_name}_00001")
                self.siril.cmd("save", "dark_stacked")
            else:
                self._log(f"Stacking {num_darks} darks...")
                self.siril.cmd("stack", dark_seq_name, "rej",
                              str(sigma_low), str(sigma_high),
                              "-nonorm", "-out=dark_stacked")
            self.siril.cmd("cd", "..")

        # === LIGHT PROCESSING ===
        self.progress.emit(20, "Converting lights...")

        if self.folder_structure == 'native':
            # Native: First move any TIFF reference images out of the way
            # TIFF files cause calibration failure (3-layer RGB vs 1-layer CFA)
            tiff_moved = self._move_tiff_to_reference(lights_dir)
            if tiff_moved > 0:
                self._log(f"Moved {tiff_moved} TIFF reference image(s) to reference/")

            # Native: convert from 01-images-initial (now only FITS files remain)
            self.siril.cmd("cd", "01-images-initial")
            # Convert all FITS files (TIFFs already moved to reference/)
            self.siril.cmd("convert", light_convert_pattern, "-out=../process")
            self.siril.cmd("cd", "../process")
        else:
            # Organized: convert from lights folder
            self.siril.cmd("cd", "lights")
            self.siril.cmd("convert", light_convert_pattern, "-out=../process")
            self.siril.cmd("cd", "../process")

        # Store sequence name for calibration step
        self.light_seq_name = light_seq_name
        
        # Branch based on filter type
        if filter_config["type"] == "dualband":
            self._process_dualband(filter_config, stack_method, sigma_low, sigma_high)
        elif filter_config["script"] == "extract_ha":
            self._process_narrowband_ha(stack_method, sigma_low, sigma_high)
        elif filter_config["script"] == "extract_oiii":
            self._process_narrowband_oiii(stack_method, sigma_low, sigma_high)
        else:
            self._process_standard(stack_method, sigma_low, sigma_high)
        
        # === POST-PROCESSING ===
        if self.settings["auto_background_extraction"]:
            mosaic_mode = self.settings.get("mosaic_mode", False)

            if mosaic_mode and MOSAIC_SETTINGS["aggressive_bge"]:
                # Two-stage background extraction for mosaic artifacts
                self.progress.emit(90, "Background extraction (stage 1)...")
                self._log("Running two-stage background extraction (mosaic mode)...")
                try:
                    # Stage 1: Aggressive pass to remove large-scale gradients
                    self._log("  Stage 1: Removing large-scale gradients...")
                    self.siril.cmd("subsky", "-rbf", "-smooth=0.3", "-samples=20")
                    # Stage 2: Refinement pass for localized variations
                    self.progress.emit(93, "Background extraction (stage 2)...")
                    self._log("  Stage 2: Refining localized variations...")
                    self.siril.cmd("subsky", "-rbf", "-smooth=0.7", "-samples=10")
                except Exception as e:
                    self._log(f"Background extraction warning: {e}")
            else:
                # Standard single-pass background extraction
                self.progress.emit(92, "Background extraction...")
                self._log("Running background extraction...")
                try:
                    self.siril.cmd("subsky", "-rbf", "-smooth=0.5", "-samples=12")
                except Exception as e:
                    self._log(f"Background extraction warning: {e}")
        
        if self.settings["auto_color_calibration"]:
            self.progress.emit(95, "Color calibration...")
            self._log("Running photometric color calibration...")
            try:
                self.siril.cmd("pcc")
            except Exception as e:
                self._log(f"Color calibration warning: {e}")
        
        # === CLEANUP ===
        if not self.settings["keep_temp_files"]:
            self.progress.emit(98, "Cleaning up...")
            deleted = self._cleanup_folder(process_dir)
            deleted += self._cleanup_folder(masters_dir)
            self._log(f"Cleaned {deleted} temp files")
        
        self.progress.emit(100, "Complete!")
        self.finished.emit(True, "Processing complete!")
    
    def _process_standard(self, stack_method, sigma_low, sigma_high):
        """Standard RGB processing"""
        self.progress.emit(30, "Calibrating...")
        self._log("Calibrating with dark subtraction...")

        # Use the sequence name from the convert step
        seq_name = self.light_seq_name
        mosaic_mode = self.settings.get("mosaic_mode", False)

        if mosaic_mode:
            self._log("CovalENS/Mosaic mode: enabling mosaic-specific processing")

        if stack_method["use_drizzle"]:
            # Drizzle path - no debayer yet
            self.siril.cmd("calibrate", seq_name,
                          "-dark=../masters/dark_stacked",
                          "-cc=dark", "-cfa", "-equalize_cfa")

            # Pre-stack gradient normalization for mosaic mode
            if mosaic_mode and MOSAIC_SETTINGS["pre_stack_gradient"]:
                self.progress.emit(40, "Pre-stack gradient normalization...")
                self._log("Normalizing gradients across frames (mosaic mode)...")
                try:
                    # seqsubsky with polynomial degree 1 removes large-scale gradients
                    self.siril.cmd("seqsubsky", f"pp_{seq_name}", "1")
                except Exception as e:
                    self._log(f"Pre-stack gradient warning: {e}")

            self.progress.emit(50, "Bayer Drizzle registration...")
            self._log("Registering with Bayer Drizzle...")
            scale = stack_method.get("drizzle_scale", 1.0)
            pixfrac = stack_method.get("drizzle_pixfrac", 1.0)
            kernel = stack_method.get("drizzle_kernel", "square")
            interp = stack_method.get("interp", "area")
            self.siril.cmd("register", f"pp_{seq_name}",
                          "-drizzle", f"-scale={scale}",
                          f"-pixfrac={pixfrac}", f"-kernel={kernel}",
                          f"-interp={interp}")
        else:
            # Standard path - debayer during calibration
            self.siril.cmd("calibrate", seq_name,
                          "-dark=../masters/dark_stacked",
                          "-cc=dark", "-cfa", "-equalize_cfa", "-debayer")

            # Pre-stack gradient normalization for mosaic mode
            if mosaic_mode and MOSAIC_SETTINGS["pre_stack_gradient"]:
                self.progress.emit(40, "Pre-stack gradient normalization...")
                self._log("Normalizing gradients across frames (mosaic mode)...")
                try:
                    self.siril.cmd("seqsubsky", f"pp_{seq_name}", "1")
                except Exception as e:
                    self._log(f"Pre-stack gradient warning: {e}")

            self.progress.emit(50, "Registering...")
            self._log("Standard registration...")
            self.siril.cmd("register", f"pp_{seq_name}")

        # Build stack command with mosaic-specific options
        self.progress.emit(75, "Stacking...")
        stack_args = [
            f"r_pp_{seq_name}",
            "rej", str(sigma_low), str(sigma_high),
            "-norm=addscale", "-output_norm", "-32b"
        ]

        if mosaic_mode:
            self._log("Stacking with mosaic mode options...")
            # Add overlap normalization for mosaics
            if MOSAIC_SETTINGS["overlap_norm"]:
                stack_args.append("-overlap_norm")
            # Add feathering for seamless tile blending
            feather = self.settings.get("feather_amount", MOSAIC_SETTINGS["default_feather"])
            if feather > 0:
                stack_args.append(f"-feather={feather}")
                self._log(f"  Using {feather}px feathering for tile blending")
        else:
            self._log("Stacking with sigma rejection...")

        stack_args.append("-out=result")
        self.siril.cmd("stack", *stack_args)

        self.progress.emit(88, "Finalizing...")
        self.siril.cmd("load", "result")
        self.siril.cmd("mirrorx", "-bottomup")
        self.siril.cmd("icc_remove")  # Remove ICC profile for VeraLux compatibility
        self.siril.cmd("save", "../result_$LIVETIME:%d$s")
        self.siril.cmd("cd", "..")
    
    def _process_dualband(self, filter_config, stack_method, sigma_low, sigma_high):
        """Dual-band Ha/OIII extraction processing"""
        self.progress.emit(30, "Calibrating for dual-band...")
        self._log("Dual-band processing: Ha/OIII extraction")

        seq_name = self.light_seq_name

        # Calibrate without debayer first
        self.siril.cmd("calibrate", seq_name,
                      "-dark=../masters/dark_stacked",
                      "-cc=dark", "-cfa", "-equalize_cfa")
        
        if stack_method["use_drizzle"]:
            self.progress.emit(45, "Bayer Drizzle registration...")
            scale = stack_method.get("drizzle_scale", 1.0)
            pixfrac = stack_method.get("drizzle_pixfrac", 1.0)
            kernel = stack_method.get("drizzle_kernel", "square")
            interp = stack_method.get("interp", "area")
            self.siril.cmd("register", f"pp_{seq_name}",
                          "-drizzle", f"-scale={scale}", f"-pixfrac={pixfrac}",
                          f"-kernel={kernel}", f"-interp={interp}")
        else:
            self.progress.emit(45, "Registering...")
            self.siril.cmd("register", f"pp_{seq_name}", "-cfa")

        self.progress.emit(60, "Stacking...")
        self.siril.cmd("stack", f"r_pp_{seq_name}",
                      "rej", str(sigma_low), str(sigma_high),
                      "-norm=addscale", "-output_norm", "-32b", "-out=result_cfa")

        # Extract Ha and OIII
        self.progress.emit(75, "Extracting Ha channel...")
        self._log("Extracting Ha (red channel)...")
        self.siril.cmd("load", "result_cfa")
        self.siril.cmd("split_cfa")

        # Ha is typically in CFA0 and CFA3 (red pixels)
        # OIII is in CFA1 and CFA2 (blue/green pixels)
        # This creates result_cfa_CFA0, CFA1, CFA2, CFA3

        self.progress.emit(80, "Building Ha image...")
        self.siril.cmd("load", "result_cfa_CFA0")
        self.siril.cmd("icc_remove")  # Remove ICC profile for VeraLux compatibility
        self.siril.cmd("save", "../Ha_result")

        self.progress.emit(85, "Building OIII image...")
        self.siril.cmd("load", "result_cfa_CFA1")
        self.siril.cmd("icc_remove")  # Remove ICC profile for VeraLux compatibility
        self.siril.cmd("save", "../OIII_result")

        # Create HOO composite
        self.progress.emit(88, "Creating HOO composite...")
        self._log("Creating HOO palette composite...")
        try:
            self.siril.cmd("rgbcomp", "../Ha_result", "../OIII_result", "../OIII_result",
                          "-out=../HOO_result")
            self.siril.cmd("load", "../HOO_result")
            self.siril.cmd("mirrorx", "-bottomup")
            self.siril.cmd("icc_remove")  # Remove ICC profile for VeraLux compatibility
            self.siril.cmd("save", "../HOO_result_$LIVETIME:%d$s")
        except Exception as e:
            self._log(f"HOO composite note: {e}")
        
        self.siril.cmd("cd", "..")
        self._log("Created: Ha_result.fit, OIII_result.fit, HOO_result.fit")
    
    def _process_narrowband_ha(self, stack_method, sigma_low, sigma_high):
        """Ha-only narrowband processing"""
        self._log("Narrowband Ha extraction")
        self.progress.emit(30, "Calibrating...")

        seq_name = self.light_seq_name

        self.siril.cmd("calibrate", seq_name,
                      "-dark=../masters/dark_stacked",
                      "-cc=dark", "-cfa", "-equalize_cfa")
        
        self.progress.emit(50, "Registering...")
        if stack_method["use_drizzle"]:
            scale = stack_method.get("drizzle_scale", 1.0)
            pixfrac = stack_method.get("drizzle_pixfrac", 1.0)
            kernel = stack_method.get("drizzle_kernel", "square")
            interp = stack_method.get("interp", "area")
            self.siril.cmd("register", f"pp_{seq_name}",
                          "-drizzle", f"-scale={scale}", f"-pixfrac={pixfrac}",
                          f"-kernel={kernel}", f"-interp={interp}")
        else:
            self.siril.cmd("register", f"pp_{seq_name}", "-cfa")

        self.progress.emit(70, "Stacking...")
        self.siril.cmd("stack", f"r_pp_{seq_name}",
                      "rej", str(sigma_low), str(sigma_high),
                      "-norm=addscale", "-output_norm", "-32b", "-out=result_cfa")

        self.progress.emit(85, "Extracting Ha...")
        self.siril.cmd("load", "result_cfa")
        self.siril.cmd("split_cfa")
        self.siril.cmd("load", "result_cfa_CFA0")
        self.siril.cmd("mirrorx", "-bottomup")
        self.siril.cmd("icc_remove")  # Remove ICC profile for VeraLux compatibility
        self.siril.cmd("save", "../Ha_result_$LIVETIME:%d$s")
        self.siril.cmd("cd", "..")

    def _process_narrowband_oiii(self, stack_method, sigma_low, sigma_high):
        """OIII-only narrowband processing"""
        self._log("Narrowband OIII extraction")
        self.progress.emit(30, "Calibrating...")

        seq_name = self.light_seq_name

        self.siril.cmd("calibrate", seq_name,
                      "-dark=../masters/dark_stacked",
                      "-cc=dark", "-cfa", "-equalize_cfa")

        self.progress.emit(50, "Registering...")
        if stack_method["use_drizzle"]:
            scale = stack_method.get("drizzle_scale", 1.0)
            pixfrac = stack_method.get("drizzle_pixfrac", 1.0)
            kernel = stack_method.get("drizzle_kernel", "square")
            interp = stack_method.get("interp", "area")
            self.siril.cmd("register", f"pp_{seq_name}",
                          "-drizzle", f"-scale={scale}", f"-pixfrac={pixfrac}",
                          f"-kernel={kernel}", f"-interp={interp}")
        else:
            self.siril.cmd("register", f"pp_{seq_name}", "-cfa")

        self.progress.emit(70, "Stacking...")
        self.siril.cmd("stack", f"r_pp_{seq_name}",
                      "rej", str(sigma_low), str(sigma_high),
                      "-norm=addscale", "-output_norm", "-32b", "-out=result_cfa")

        self.progress.emit(85, "Extracting OIII...")
        self.siril.cmd("load", "result_cfa")
        self.siril.cmd("split_cfa")
        self.siril.cmd("load", "result_cfa_CFA1")
        self.siril.cmd("mirrorx", "-bottomup")
        self.siril.cmd("icc_remove")  # Remove ICC profile for VeraLux compatibility
        self.siril.cmd("save", "../OIII_result_$LIVETIME:%d$s")
        self.siril.cmd("cd", "..")
    
    def _count_fits(self, folder):
        """Count FITS files in folder"""
        count = 0
        for ext in ['*.fit', '*.fits', '*.FIT', '*.FITS']:
            count += len(glob.glob(os.path.join(folder, ext)))
        return count

    def _move_tiff_to_reference(self, lights_dir):
        """Move TIFF reference images to a reference folder before processing.

        Vespera Pro creates TIFF reference images that cause calibration to fail
        due to layer mismatch (3-layer RGB vs 1-layer CFA). This moves them to
        a reference/ folder to preserve them while excluding from processing.
        """
        # Find all TIFF files in lights directory
        tiff_files = []
        for pattern in ['*.tif', '*.tiff', '*.TIF', '*.TIFF']:
            tiff_files.extend(glob.glob(os.path.join(lights_dir, pattern)))

        if not tiff_files:
            return 0

        # Create reference folder in the working directory
        reference_dir = os.path.join(self.workdir, "reference")
        os.makedirs(reference_dir, exist_ok=True)

        moved_count = 0
        for tiff_file in tiff_files:
            try:
                filename = os.path.basename(tiff_file)
                dest_path = os.path.join(reference_dir, filename)
                shutil.move(tiff_file, dest_path)
                self._log(f"Moved reference image: {filename} → reference/")
                moved_count += 1
            except Exception as e:
                self._log(f"Warning: Could not move {tiff_file}: {e}")

        return moved_count
    
    def _cleanup_folder(self, folder):
        """Remove all temp files and subfolders from folder"""
        count = 0
        if not os.path.exists(folder):
            return 0

        # Remove FITS, sequence, and conversion text files
        for ext in ['*.fit', '*.fits', '*.FIT', '*.FITS', '*.seq', '*conversion.txt']:
            for f in glob.glob(os.path.join(folder, ext)):
                try:
                    os.remove(f)
                    count += 1
                except:
                    pass

        # Remove temp subfolders created by Siril (cache, drizztmp, etc.)
        temp_subdirs = ['cache', 'drizztmp', 'other']
        for subdir in temp_subdirs:
            subdir_path = os.path.join(folder, subdir)
            if os.path.exists(subdir_path) and os.path.isdir(subdir_path):
                try:
                    shutil.rmtree(subdir_path)
                    count += 1
                except:
                    pass

        return count


##############################################
# MAIN GUI
##############################################

class VesperaProGUI(QDialog):
    """Full-featured Vespera Pro preprocessing dialog"""
    
    def __init__(self, siril, app):
        super().__init__()
        self.siril = siril
        self.app = app
        self.worker = None
        self.qsettings = QSettings("VesperaPro", "DrizzlePreprocessing")
        
        self.setWindowTitle(f"Vespera Pro - Drizzle Preprocessing v{VERSION}")
        self.setMinimumWidth(620)
        self.setMinimumHeight(950)
        self.resize(650, 1000)
        self.setStyleSheet(DARK_STYLESHEET)
        
        self._setup_ui()
        self._load_settings()
        self._check_folders()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Header
        header = QVBoxLayout()
        title = QLabel("Vespera Pro - Drizzle Preprocessing")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(title)
        
        subtitle = QLabel(f"v{VERSION} • Sony IMX676 Sensor • Alt-Az Field Rotation Handling")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(subtitle)
        layout.addLayout(header)
        
        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._create_main_tab(), "Main")
        tabs.addTab(self._create_options_tab(), "Options")
        tabs.addTab(self._create_info_tab(), "Info")
        layout.addWidget(tabs)
        
        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        progress_layout.addWidget(self.progress)
        
        self.status = QLabel("Ready")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.status)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(100)
        progress_layout.addWidget(self.log_area)
        
        layout.addWidget(progress_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_start = QPushButton("Start Processing")
        self.btn_start.setObjectName("start")
        self.btn_start.clicked.connect(self._start_processing)
        btn_layout.addWidget(self.btn_start)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
    
    def _create_main_tab(self):
        """Main settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Folder Status
        status_group = QGroupBox("Folder Status")
        status_layout = QVBoxLayout(status_group)

        self.lbl_workdir = QLabel("Working directory: ...")
        self.lbl_workdir.setObjectName("info")
        self.lbl_workdir.setWordWrap(True)
        status_layout.addWidget(self.lbl_workdir)

        folder_row = QHBoxLayout()
        self.lbl_darks = QLabel("Darks: checking...")
        self.lbl_lights = QLabel("Lights: checking...")
        folder_row.addWidget(self.lbl_darks)
        folder_row.addWidget(self.lbl_lights)
        status_layout.addLayout(folder_row)

        # Structure detection label
        self.lbl_structure = QLabel("")
        self.lbl_structure.setObjectName("info")
        self.lbl_structure.setWordWrap(True)
        status_layout.addWidget(self.lbl_structure)

        # CovalENS status (visible on main tab)
        self.lbl_covalens_main = QLabel("")
        self.lbl_covalens_main.setObjectName("info")
        self.lbl_covalens_main.setWordWrap(True)
        status_layout.addWidget(self.lbl_covalens_main)

        # Analyze frames button
        self.btn_analyze = QPushButton("Analyze Frame Quality")
        self.btn_analyze.setToolTip(
            "Scan frames for quality issues:\n"
            "- Brightness anomalies (obstructions, clouds)\n"
            "- Identifies bad frames by z-score deviation\n"
            "Click to generate a quality report"
        )
        self.btn_analyze.clicked.connect(self._analyze_frames)
        status_layout.addWidget(self.btn_analyze)

        layout.addWidget(status_group)
        
        # Filter Selection
        filter_group = QGroupBox("Filter Configuration")
        filter_layout = QVBoxLayout(filter_group)
        
        self.combo_filter = QComboBox()
        for name in FILTER_CONFIGS.keys():
            self.combo_filter.addItem(name)
        self.combo_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.combo_filter)
        
        self.lbl_filter_desc = QLabel("")
        self.lbl_filter_desc.setObjectName("info")
        self.lbl_filter_desc.setWordWrap(True)
        filter_layout.addWidget(self.lbl_filter_desc)
        
        layout.addWidget(filter_group)
        
        # Sky Quality
        sky_group = QGroupBox("Sky Quality (Location)")
        sky_layout = QVBoxLayout(sky_group)
        
        self.combo_sky = QComboBox()
        for name in SKY_PRESETS.keys():
            self.combo_sky.addItem(name)
        self.combo_sky.currentTextChanged.connect(self._on_sky_changed)
        sky_layout.addWidget(self.combo_sky)
        
        self.lbl_sky_desc = QLabel("")
        self.lbl_sky_desc.setObjectName("info")
        sky_layout.addWidget(self.lbl_sky_desc)
        
        layout.addWidget(sky_group)
        
        # Stacking Method
        stack_group = QGroupBox("Stacking Method")
        stack_layout = QVBoxLayout(stack_group)
        
        self.combo_stack = QComboBox()
        for idx, (name, config) in enumerate(STACKING_METHODS.items()):
            self.combo_stack.addItem(name)
            # Set tooltip for each item
            if "tooltip" in config:
                self.combo_stack.setItemData(idx, config["tooltip"], Qt.ItemDataRole.ToolTipRole)
        self.combo_stack.currentTextChanged.connect(self._on_stack_changed)
        stack_layout.addWidget(self.combo_stack)

        self.lbl_stack_desc = QLabel("")
        self.lbl_stack_desc.setObjectName("info")
        self.lbl_stack_desc.setWordWrap(True)
        stack_layout.addWidget(self.lbl_stack_desc)
        
        layout.addWidget(stack_group)
        
        layout.addStretch()
        return widget
    
    def _create_options_tab(self):
        """Additional options tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # CovalENS/Mosaic Mode
        mosaic_group = QGroupBox("CovalENS / Mosaic Mode")
        mosaic_layout = QVBoxLayout(mosaic_group)

        # Auto-detection status label
        self.lbl_covalens_status = QLabel("CovalENS detection: checking...")
        self.lbl_covalens_status.setObjectName("info")
        mosaic_layout.addWidget(self.lbl_covalens_status)

        # Manual override checkbox
        self.chk_mosaic_mode = QCheckBox("Enable Mosaic Mode processing")
        self.chk_mosaic_mode.setToolTip(
            "When enabled, applies mosaic-specific processing:\n"
            "• Pre-stack gradient normalization\n"
            "• Overlap normalization during stacking\n"
            "• Edge feathering for seamless tile blending\n"
            "• Aggressive background extraction"
        )
        mosaic_layout.addWidget(self.chk_mosaic_mode)

        # Feather amount
        feather_row = QHBoxLayout()
        feather_row.addWidget(QLabel("Feather amount:"))
        self.spin_feather = QSpinBox()
        self.spin_feather.setRange(0, 100)
        self.spin_feather.setValue(MOSAIC_SETTINGS["default_feather"])
        self.spin_feather.setSuffix(" px")
        self.spin_feather.setToolTip(
            "Edge blending width in pixels (0 = disabled)\n"
            "Higher values create smoother tile transitions\n"
            "Recommended: 20-50 pixels"
        )
        feather_row.addWidget(self.spin_feather)
        feather_row.addStretch()
        mosaic_layout.addLayout(feather_row)

        layout.addWidget(mosaic_group)

        # Post-Processing
        post_group = QGroupBox("Post-Processing (Auto)")
        post_layout = QVBoxLayout(post_group)

        self.chk_background = QCheckBox("Run Background Extraction after stacking")
        self.chk_background.setToolTip("Automatically remove gradients from light pollution")
        post_layout.addWidget(self.chk_background)

        self.chk_color_cal = QCheckBox("Run Photometric Color Calibration")
        self.chk_color_cal.setToolTip("Automatically calibrate colors using star catalog")
        post_layout.addWidget(self.chk_color_cal)

        layout.addWidget(post_group)

        # Debug Options
        debug_group = QGroupBox("Advanced Options")
        debug_layout = QVBoxLayout(debug_group)
        
        self.chk_keep_temp = QCheckBox("Keep temporary files (for debugging)")
        self.chk_keep_temp.setToolTip("Don't delete process/ and masters/ folders")
        debug_layout.addWidget(self.chk_keep_temp)
        
        layout.addWidget(debug_group)
        
        # Sensor Info
        sensor_group = QGroupBox("Sensor Profile")
        sensor_layout = QGridLayout(sensor_group)
        
        sensor_layout.addWidget(QLabel("Sensor:"), 0, 0)
        sensor_layout.addWidget(QLabel(SENSOR_PROFILE["name"]), 0, 1)
        
        sensor_layout.addWidget(QLabel("Resolution:"), 1, 0)
        res = SENSOR_PROFILE["resolution"]
        sensor_layout.addWidget(QLabel(f"{res[0]} × {res[1]}"), 1, 1)
        
        sensor_layout.addWidget(QLabel("Pixel Size:"), 2, 0)
        sensor_layout.addWidget(QLabel(f"{SENSOR_PROFILE['pixel_size']} µm"), 2, 1)
        
        sensor_layout.addWidget(QLabel("Bayer Pattern:"), 3, 0)
        sensor_layout.addWidget(QLabel(SENSOR_PROFILE["bayer_pattern"]), 3, 1)
        
        layout.addWidget(sensor_group)
        
        layout.addStretch()
        return widget
    
    def _create_info_tab(self):
        """Information/help tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setHtml("""
        <h3 style="color: #88aaff;">Vespera Pro Preprocessing</h3>

        <p><b>No Setup Required!</b></p>
        <p>Just point this plugin at your Vespera observation folder. It auto-detects
        darks vs lights by filename - no file reorganization needed.</p>

        <hr style="border-color: #444;">
        <h4 style="color: #88aaff;">Why Restack? (vs Vespera's Built-in)</h4>

        <p>Vespera already outputs a stacked TIFF. This plugin restacks from raw FITS for better quality:</p>

        <table style="color: #e0e0e0; margin: 10px 0;">
        <tr><td><b>Vespera:</b></td><td>Debayer → Stack (loses sub-pixel info)</td></tr>
        <tr><td><b>This Plugin:</b></td><td>Stack → Debayer (preserves CFA data)</td></tr>
        </table>

        <p><b>Benefits of Restacking:</b></p>
        <ul>
        <li>~20% sharper color detail from Bayer Drizzle</li>
        <li>Sigma rejection removes satellites &amp; planes</li>
        <li>32-bit output (vs 16-bit) for more stretching headroom</li>
        <li>Your actual darks (vs Vespera's algorithmic BalENS)</li>
        <li>Proper Ha/OIII extraction for dual-band filters</li>
        </ul>

        <p><i>For social media, Vespera TIFF is fine. For prints, restack here.</i></p>

        <hr style="border-color: #444;">
        <h4 style="color: #88aaff;">CovalENS / Mosaic Mode</h4>

        <p><b>What is CovalENS?</b></p>
        <p>CovalENS is Vespera Pro's mosaic mode that captures multiple overlapping tiles
        and stitches them together for a wider field of view. The plugin auto-detects
        CovalENS observations from the folder name (indicated by a _XX suffix).</p>

        <p><b>Grid Pattern Artifacts:</b></p>
        <p>CovalENS mosaics can show visible grid patterns at tile boundaries due to
        gradient mismatches between tiles. When Mosaic Mode is enabled, the plugin applies:</p>
        <ul>
        <li><b>Pre-stack gradient normalization:</b> Removes large-scale gradients from each frame</li>
        <li><b>Overlap normalization:</b> Normalizes brightness in overlapping regions</li>
        <li><b>Feathering:</b> Smoothly blends tile edges (adjustable, default 30px)</li>
        <li><b>Two-stage BGE:</b> Aggressive background extraction to remove residual gradients</li>
        </ul>

        <p><b>Frame Quality Checker:</b></p>
        <p>Use "Analyze Frame Quality" to detect bad frames (obstructions, clouds, tracking issues)
        before processing. This identifies frames with unusual brightness that should be excluded.</p>

        <hr style="border-color: #444;">
        <h4 style="color: #88aaff;">Filter Options</h4>
        <ul>
        <li><b>No Filter:</b> Standard RGB processing</li>
        <li><b>SVBONY SV220:</b> Extracts Ha and OIII channels, creates HOO composite</li>
        <li><b>L-Pro/CLS:</b> Standard RGB (filter reduces LP optically)</li>
        <li><b>Ha/OIII Narrowband:</b> Single channel extraction</li>
        </ul>

        <hr style="border-color: #444;">
        <h4 style="color: #88aaff;">Drizzle & Pattern Artifacts</h4>

        <p><b>Why Bayer Drizzle?</b></p>
        <p>The Vespera Pro's alt-az mount causes field rotation (10-15° per hour).
        Bayer Drizzle handles this while preserving CFA pattern data.</p>

        <p><b>Checkerboard/Grid Patterns:</b></p>
        <p>If you see checkerboard or moiré patterns in your stacked image, this is caused by
        <i>interpolation artifacts</i> when Siril applies geometric transforms to correct field rotation.
        The pattern appears at CFA (color filter) cell boundaries.</p>

        <p><b>Solutions:</b></p>
        <ul>
        <li><b>Gaussian kernel (Recommended):</b> Smoothest results, reduces pattern visibility</li>
        <li><b>Nearest interpolation:</b> Eliminates interpolation artifacts but may look slightly blocky</li>
        <li><b>More frames:</b> Additional well-dithered frames help average out patterns</li>
        </ul>

        <p><b>Drizzle Kernel Types:</b></p>
        <ul>
        <li><b>Gaussian:</b> Smooth, centrally-peaked PSFs - best for deep-sky CFA data</li>
        <li><b>Square:</b> Classic HST algorithm, mathematically flux-preserving - better for photometry</li>
        <li><b>Lanczos:</b> Only valid at scale=1.0, pixfrac=1.0 - NOT for 2x upscaling</li>
        </ul>

        <p><b>Interpolation Methods:</b></p>
        <ul>
        <li><b>Area:</b> Area-based averaging - good balance of quality and artifact reduction</li>
        <li><b>Nearest:</b> No interpolation - eliminates moiré but may look blocky</li>
        <li><b>Cubic/Lanczos:</b> High quality but can cause ringing at high-contrast edges</li>
        </ul>

        <hr style="border-color: #444;">
        <h4 style="color: #88aaff;">Sony IMX676 Sensor</h4>
        <p>The Vespera Pro uses a Sony IMX676 CMOS sensor:</p>
        <ul>
        <li>Resolution: 3536 × 3536 (12.5 MP)</li>
        <li>Pixel size: 2.0 µm</li>
        <li>Bayer pattern: Standard RGGB</li>
        <li>Technology: STARVIS 2 back-illuminated</li>
        </ul>

        <p><b>Output:</b></p>
        <p>Linear 32-bit FITS file (0-1 normalized) ready for stretching in VeraLux, GHS, or Siril.</p>

        <p style="color: #888888;">Created by Claude (Anthropic) • MIT License</p>
        """)
        layout.addWidget(info_text)
        
        return widget
    
    def _on_filter_changed(self, name):
        if name in FILTER_CONFIGS:
            self.lbl_filter_desc.setText(FILTER_CONFIGS[name]["description"])
    
    def _on_sky_changed(self, name):
        if name in SKY_PRESETS:
            self.lbl_sky_desc.setText(SKY_PRESETS[name]["description"])
    
    def _on_stack_changed(self, name):
        if name in STACKING_METHODS:
            self.lbl_stack_desc.setText(STACKING_METHODS[name]["description"])
    
    def _load_settings(self):
        """Load saved settings"""
        self.combo_filter.setCurrentText(
            self.qsettings.value("filter", "No Filter (Stock)"))
        self.combo_sky.setCurrentText(
            self.qsettings.value("sky_quality", "Bortle 3-4 (Rural)"))
        self.combo_stack.setCurrentText(
            self.qsettings.value("stacking_method", "Bayer Drizzle (Recommended)"))
        self.chk_background.setChecked(
            self.qsettings.value("auto_background", False, type=bool))
        self.chk_color_cal.setChecked(
            self.qsettings.value("auto_color_cal", False, type=bool))
        self.chk_keep_temp.setChecked(
            self.qsettings.value("keep_temp", False, type=bool))
        # Mosaic settings (don't override auto-detection)
        self.spin_feather.setValue(
            self.qsettings.value("feather_amount", MOSAIC_SETTINGS["default_feather"], type=int))

        # Trigger description updates
        self._on_filter_changed(self.combo_filter.currentText())
        self._on_sky_changed(self.combo_sky.currentText())
        self._on_stack_changed(self.combo_stack.currentText())
    
    def _save_settings(self):
        """Save current settings"""
        self.qsettings.setValue("filter", self.combo_filter.currentText())
        self.qsettings.setValue("sky_quality", self.combo_sky.currentText())
        self.qsettings.setValue("stacking_method", self.combo_stack.currentText())
        self.qsettings.setValue("auto_background", self.chk_background.isChecked())
        self.qsettings.setValue("auto_color_cal", self.chk_color_cal.isChecked())
        self.qsettings.setValue("keep_temp", self.chk_keep_temp.isChecked())
        self.qsettings.setValue("feather_amount", self.spin_feather.value())
    
    def _check_folders(self):
        """Check folder status - supports both organized and native Vespera structure"""
        try:
            workdir = self.siril.get_siril_wd()
            self.lbl_workdir.setText(f"Working directory: {workdir}")

            # First check for organized structure (darks/ and lights/ folders)
            darks_dir = os.path.join(workdir, "darks")
            lights_dir = os.path.join(workdir, "lights")

            num_darks_organized = self._count_fits(darks_dir) if os.path.exists(darks_dir) else 0
            num_lights_organized = self._count_fits(lights_dir) if os.path.exists(lights_dir) else 0

            # Check for native Vespera structure
            native = self._detect_native_structure(workdir)

            # Determine which structure to use
            if num_darks_organized > 0 and num_lights_organized > 0:
                # Use organized structure
                self.folder_structure = 'organized'
                num_darks = num_darks_organized
                num_lights = num_lights_organized
                self.lbl_structure.setText("Using organized folders (darks/, lights/)")
                self.lbl_structure.setStyleSheet("color: #88aaff;")
            elif native:
                # Use native Vespera structure
                self.folder_structure = 'native'
                num_darks = native['num_darks']
                num_lights = native['num_lights']
                self.lbl_structure.setText("Using Vespera native structure")
                self.lbl_structure.setStyleSheet("color: #88aaff;")
            else:
                # No valid structure found
                self.folder_structure = None
                num_darks = 0
                num_lights = 0
                self.lbl_structure.setText("No valid folder structure detected")
                self.lbl_structure.setStyleSheet("color: #ff8888;")

            # Update status labels
            if num_darks > 0:
                self.lbl_darks.setText(f"✓ Darks: {num_darks}")
                self.lbl_darks.setStyleSheet("color: #88ff88;")
            else:
                self.lbl_darks.setText("✗ Darks: not found")
                self.lbl_darks.setStyleSheet("color: #ff8888;")

            if num_lights > 0:
                self.lbl_lights.setText(f"✓ Lights: {num_lights}")
                self.lbl_lights.setStyleSheet("color: #88ff88;")
            else:
                self.lbl_lights.setText("✗ Lights: not found")
                self.lbl_lights.setStyleSheet("color: #ff8888;")

            self.btn_start.setEnabled(num_darks > 0 and num_lights > 0)

            # Check for CovalENS mode
            is_covalens, panel_info, target = detect_covalens_mode(workdir)
            if is_covalens:
                covalens_text = f"✓ CovalENS mosaic detected: {target} (panel {panel_info})"
                self.lbl_covalens_status.setText(covalens_text)
                self.lbl_covalens_status.setStyleSheet("color: #88aaff;")
                self.lbl_covalens_main.setText(covalens_text)
                self.lbl_covalens_main.setStyleSheet("color: #88aaff; font-weight: bold;")
                # Auto-enable mosaic mode
                self.chk_mosaic_mode.setChecked(True)
                self._log(f"CovalENS mosaic mode auto-detected (target: {target})")
            elif target:
                self.lbl_covalens_status.setText(f"Standard mode: {target}")
                self.lbl_covalens_status.setStyleSheet("color: #888888;")
                self.lbl_covalens_main.setText(f"Target: {target}")
                self.lbl_covalens_main.setStyleSheet("color: #88ff88;")
            else:
                self.lbl_covalens_status.setText("Could not detect observation type")
                self.lbl_covalens_status.setStyleSheet("color: #888888;")
                self.lbl_covalens_main.setText("")

        except Exception as e:
            self._log(f"Error: {e}")
            self.btn_start.setEnabled(False)

    def _detect_native_structure(self, workdir):
        """Detect native Vespera Pro folder structure"""
        # Normalize path (remove trailing slash)
        workdir = os.path.normpath(workdir)

        # Look for dark frames in root (files containing '-dark' in name)
        dark_files = set()
        for pattern in ['*-dark.fits', '*-dark.fit', '*-dark.FITS', '*-dark.FIT']:
            dark_files.update(glob.glob(os.path.join(workdir, pattern)))

        # Look for lights in 01-images-initial subfolder
        images_initial = os.path.join(workdir, "01-images-initial")
        light_files = set()
        if os.path.exists(images_initial):
            for pattern in ['*.fits', '*.fit', '*.FITS', '*.FIT']:
                all_fits = glob.glob(os.path.join(images_initial, pattern))
                # Exclude any dark files
                light_files.update([f for f in all_fits if '-dark' not in f.lower()])

        dark_files = list(dark_files)
        light_files = list(light_files)

        if dark_files and light_files:
            return {
                'dark_files': dark_files,
                'light_files': light_files,
                'num_darks': len(dark_files),
                'num_lights': len(light_files),
                'images_initial': images_initial
            }
        return None

    def _count_fits(self, folder):
        count = 0
        for ext in ['*.fit', '*.fits', '*.FIT', '*.FITS']:
            count += len(glob.glob(os.path.join(folder, ext)))
        return count
    
    def _log(self, msg):
        self.log_area.append(msg)
        try:
            self.siril.log(f"VesperaPro: {msg}")
        except:
            pass

    def _analyze_frames(self):
        """Analyze frame quality - runs in background thread"""
        try:
            workdir = self.siril.get_siril_wd()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not get working directory: {e}")
            return

        # Determine lights directory based on folder structure
        if self.folder_structure == 'native':
            lights_dir = os.path.join(workdir, "01-images-initial")
        elif self.folder_structure == 'organized':
            lights_dir = os.path.join(workdir, "lights")
        else:
            QMessageBox.warning(self, "Error", "No valid folder structure detected")
            return

        if not os.path.exists(lights_dir):
            QMessageBox.warning(self, "Error", f"Lights directory not found: {lights_dir}")
            return

        # Check for iCloud placeholders before starting analysis
        icloud_count, total_count = count_icloud_placeholders(lights_dir)

        # Default to thorough analysis - it's more accurate
        thorough_mode = True

        if icloud_count > 0:
            # Files in iCloud - offer to download first
            reply = QMessageBox.question(
                self, "iCloud Files Detected",
                f"{icloud_count} of {total_count} files are in iCloud.\n\n"
                f"Download files first? (Recommended for accurate analysis)",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel
            )

            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Yes:
                self._log(f"Triggering iCloud download for {icloud_count} files...")
                if trigger_icloud_download(lights_dir):
                    self._log("Download started. Run analysis again once complete.")
                    QMessageBox.information(
                        self, "Download Started",
                        "iCloud download triggered.\n"
                        "Check Finder for progress, then run analysis again."
                    )
                    return
                else:
                    self._log("Could not trigger download. Proceeding anyway...")
            # If No, proceed with thorough analysis (will be slow but works)

        # Disable button during analysis
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("Analyzing...")

        self._log("=" * 40)
        if thorough_mode:
            self._log("THOROUGH FRAME QUALITY ANALYSIS")
            self._log("(Stars, sharpness, gradients, noise)")
        else:
            self._log("QUICK FRAME QUALITY ANALYSIS")
            self._log("(Brightness anomaly detection only)")
        self._log("=" * 40)

        # Run analysis in background thread
        self.analysis_thread = FrameAnalysisThread(lights_dir, thorough=thorough_mode)
        self.analysis_thread.progress.connect(self._on_analysis_progress)
        self.analysis_thread.finished.connect(self._on_analysis_finished)
        self.analysis_thread.start()

    def _on_analysis_progress(self, message):
        """Handle progress updates from analysis thread"""
        self._log(message)
        self.app.processEvents()  # Keep UI responsive

    def _on_analysis_finished(self, results, stats):
        """Handle analysis completion"""
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("Analyze Frame Quality")

        if not results:
            self._log("No frames to analyze or analysis failed")
            QMessageBox.information(self, "Analysis Complete", "No frames found or analysis failed.")
            return

        session_median, session_std, total_frames = stats

        # Count by quality
        good = [r for r in results if r[1] >= 80]
        marginal = [r for r in results if 50 <= r[1] < 80]
        bad = [r for r in results if r[1] < 50]

        # Build report as a single batch to avoid UI freezing
        # (calling _log hundreds of times would freeze the UI)
        report_lines = []
        report_lines.append(f"Session brightness: median={session_median:.0f}, std={session_std:.1f}")
        report_lines.append("")

        # Show flagged frames (limit detail to first 20 to avoid spam)
        if bad:
            report_lines.append(f"FLAGGED FRAMES ({len(bad)} total, score < 50):")
            for fname, score, issues, brightness in bad[:20]:
                issue_str = "; ".join(issues) if issues else "Unknown issue"
                report_lines.append(f"  X {fname}: {score} - {issue_str}")
            if len(bad) > 20:
                report_lines.append(f"  ... and {len(bad) - 20} more flagged frames")
            report_lines.append("")

        if marginal:
            report_lines.append(f"MARGINAL FRAMES ({len(marginal)} total, score 50-79):")
            for fname, score, issues, brightness in marginal[:10]:
                issue_str = "; ".join(issues) if issues else "Minor variation"
                report_lines.append(f"  ? {fname}: {score} - {issue_str}")
            if len(marginal) > 10:
                report_lines.append(f"  ... and {len(marginal) - 10} more marginal frames")
            report_lines.append("")

        report_lines.append(f"SUMMARY: {len(good)} good, {len(marginal)} marginal, {len(bad)} flagged")

        if bad:
            report_lines.append("")
            report_lines.append("TIP: Move flagged frames out of the lights folder before processing")

        # Log as single batch (one append to log_area, one siril.log call)
        full_report = "\n".join(report_lines)
        self.log_area.append(full_report)
        try:
            self.siril.log(f"VesperaPro: Analysis complete - {len(good)} good, {len(marginal)} marginal, {len(bad)} flagged")
        except:
            pass

        # Store results for potential exclusion
        self._last_analysis_results = results
        self._last_analysis_bad = bad

        # Show summary in message box with option to exclude bad frames
        summary = f"Analyzed {total_frames} frames:\n\n"
        summary += f"✓ Good: {len(good)}\n"
        summary += f"? Marginal: {len(marginal)}\n"
        summary += f"✗ Flagged: {len(bad)}\n"

        if bad:
            summary += f"\nFlagged frames (possible obstructions):\n"
            for fname, score, issues, _ in bad[:5]:
                summary += f"  - {fname}\n"
            if len(bad) > 5:
                summary += f"  ... and {len(bad) - 5} more\n"

            # Ask if user wants to move bad frames
            summary += f"\nMove {len(bad)} flagged frames to 'rejected' folder?"

            reply = QMessageBox.question(
                self, "Frame Quality Analysis",
                summary,
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._move_flagged_frames(bad)
        else:
            QMessageBox.information(self, "Frame Quality Analysis", summary + "\n\nAll frames look good!")

    def _move_flagged_frames(self, bad_frames):
        """Move flagged frames to a 'rejected' subfolder"""
        try:
            workdir = self.siril.get_siril_wd()

            # Determine lights directory based on folder structure
            if self.folder_structure == 'native':
                lights_dir = os.path.join(workdir, "01-images-initial")
            elif self.folder_structure == 'organized':
                lights_dir = os.path.join(workdir, "lights")
            else:
                self._log("Error: Could not determine lights directory")
                return

            # Create rejected folder
            rejected_dir = os.path.join(lights_dir, "rejected")
            os.makedirs(rejected_dir, exist_ok=True)

            moved_count = 0
            failed_count = 0

            for fname, score, issues, brightness in bad_frames:
                src_path = os.path.join(lights_dir, fname)
                dst_path = os.path.join(rejected_dir, fname)

                if os.path.exists(src_path):
                    try:
                        import shutil
                        shutil.move(src_path, dst_path)
                        moved_count += 1
                    except Exception as e:
                        self._log(f"  Failed to move {fname}: {e}")
                        failed_count += 1
                else:
                    self._log(f"  File not found: {fname}")
                    failed_count += 1

            self._log(f"Moved {moved_count} flagged frames to: {rejected_dir}")
            if failed_count > 0:
                self._log(f"Failed to move {failed_count} frames")

            # Refresh folder status to update frame counts in UI
            self._check_folders()

            QMessageBox.information(
                self, "Frames Moved",
                f"Moved {moved_count} flagged frames to:\n{rejected_dir}\n\n"
                f"You can restore them later if needed."
            )

        except Exception as e:
            self._log(f"Error moving frames: {e}")
            QMessageBox.warning(self, "Error", f"Failed to move frames: {e}")

    def _start_processing(self):
        self._save_settings()
        self.btn_start.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Processing...")
        self.log_area.clear()
        
        settings = {
            "filter": self.combo_filter.currentText(),
            "sky_quality": self.combo_sky.currentText(),
            "stacking_method": self.combo_stack.currentText(),
            "auto_background_extraction": self.chk_background.isChecked(),
            "auto_color_calibration": self.chk_color_cal.isChecked(),
            "keep_temp_files": self.chk_keep_temp.isChecked(),
            # Mosaic/CovalENS settings
            "mosaic_mode": self.chk_mosaic_mode.isChecked(),
            "feather_amount": self.spin_feather.value(),
        }
        
        try:
            workdir = self.siril.get_siril_wd()
            self.worker = ProcessingThread(self.siril, workdir, settings, self.folder_structure)
            self.worker.progress.connect(self._on_progress)
            self.worker.finished.connect(self._on_finished)
            self.worker.log.connect(self._log)
            self.worker.start()
        except Exception as e:
            self._log(f"Start error: {e}")
            self.btn_start.setEnabled(True)
    
    def _on_progress(self, percent, message):
        self.progress.setValue(percent)
        self.status.setText(message)
        self.app.processEvents()
    
    def _on_finished(self, success, message):
        self.btn_start.setEnabled(True)
        
        if success:
            self.status.setText("✓ " + message)
            self.status.setStyleSheet("color: #88ff88;")
            self._log("=" * 40)
            self._log("SUCCESS!")
            
            filter_type = FILTER_CONFIGS[self.combo_filter.currentText()]["type"]
            if filter_type == "dualband":
                self._log("Created: Ha_result.fit, OIII_result.fit, HOO_result.fit")
            else:
                self._log("Created: result_XXXXs.fit")
            
            self._log("Next: Stretch with GHS, Asinh, or VeraLux")
            self._log("=" * 40)
            
            try:
                self.siril.log("Vespera Pro: Complete!", color=LogColor.GREEN)
            except:
                pass
        else:
            self.status.setText("✗ " + message)
            self.status.setStyleSheet("color: #ff8888;")
            self._log(f"FAILED: {message}")


##############################################
# MAIN
##############################################

def main():
    try:
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        siril = s.SirilInterface()
        
        try:
            siril.connect()
        except Exception as e:
            QMessageBox.critical(None, "Connection Error",
                               f"Could not connect to Siril.\n{e}")
            return
        
        gui = VesperaProGUI(siril, app)
        gui.show()
        app.exec()
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
