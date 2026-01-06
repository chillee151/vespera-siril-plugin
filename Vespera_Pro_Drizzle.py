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

try:
    import sirilpy as s
    from sirilpy import LogColor
except ImportError:
    print("Error: sirilpy module not found. This script must be run within Siril.")
    sys.exit(1)

# Ensure dependencies
s.ensure_installed("PyQt6")

from PyQt6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QProgressBar, QMessageBox,
                             QTextEdit, QGroupBox, QComboBox, QCheckBox,
                             QSpinBox, QDoubleSpinBox, QTabWidget, QWidget,
                             QGridLayout, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

VERSION = "2.0.0"

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

        if stack_method["use_drizzle"]:
            # Drizzle path - no debayer yet
            self.siril.cmd("calibrate", seq_name,
                          "-dark=../masters/dark_stacked",
                          "-cc=dark", "-cfa", "-equalize_cfa")

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
            
            self.progress.emit(50, "Registering...")
            self._log("Standard registration...")
            self.siril.cmd("register", f"pp_{seq_name}")

        self.progress.emit(75, "Stacking...")
        self._log("Stacking with sigma rejection...")
        self.siril.cmd("stack", f"r_pp_{seq_name}",
                      "rej", str(sigma_low), str(sigma_high),
                      "-norm=addscale", "-output_norm", "-32b", "-out=result")

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
        
        self.setWindowTitle(f"Vespera Pro — Drizzle Preprocessing v{VERSION}")
        self.setMinimumWidth(550)
        self.setMinimumHeight(750)
        self.resize(550, 800)
        self.setStyleSheet(DARK_STYLESHEET)
        
        self._setup_ui()
        self._load_settings()
        self._check_folders()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Header
        header = QVBoxLayout()
        title = QLabel("Vespera Pro — Drizzle Preprocessing")
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

        <p><b>Folder Structure Required:</b></p>
        <pre style="color: #88ff88;">
observation_folder/
├── darks/    (1+ dark frames)
├── lights/   (light frames)
├── process/  (auto-created)
└── masters/  (auto-created)
        </pre>

        <p><b>Filter Options:</b></p>
        <ul>
        <li><b>No Filter:</b> Standard RGB processing</li>
        <li><b>SVBONY SV220:</b> Extracts Ha and OIII channels, creates HOO composite</li>
        <li><b>L-Pro/CLS:</b> Standard RGB (filter reduces LP optically)</li>
        <li><b>Ha/OIII Narrowband:</b> Single channel extraction</li>
        </ul>

        <p><b>Sky Quality:</b></p>
        <p>Adjusts sigma rejection and gradient handling based on light pollution levels.</p>

        <hr style="border-color: #444;">
        <h4 style="color: #88aaff;">Understanding Drizzle & Pattern Artifacts</h4>

        <p><b>Why Bayer Drizzle?</b></p>
        <p>The Vespera Pro uses an alt-az mount, causing field rotation during imaging sessions
        (typically 10-15° per hour). Bayer Drizzle handles this rotation while preserving the
        CFA (Bayer) pattern data, avoiding debayering artifacts.</p>

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
