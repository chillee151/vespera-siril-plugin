##############################################
# Vespera Quick Prep
# One-Click Image Preparation Pipeline
# For Vespera Pro Smart Telescope
##############################################

# SPDX-License-Identifier: Apache-2.0
# Version 1.2.0

"""
Overview
--------
A streamlined preparation plugin for Vespera Pro 16-bit TIFF images that
automates the tedious pre-stretch workflow:

1. Background Extraction (GraXpert AI or Siril RBF)
2. Plate Solving (for coordinate metadata)
3. Photometric Color Calibration (accurate star colors)
4. Optional Denoising (multiple engine choices)
5. Optional auto-launch of VeraLux HMS for stretching

This plugin bridges the gap between Vespera's output and the final stretch,
eliminating repetitive manual steps while preserving full control over each stage.

Usage
-----
1. Load your Vespera Pro TIFF in Siril
2. Open Vespera Quick Prep from Scripts menu
3. Select your preferred options
4. Click "Prep Image"
5. Image is ready for stretching (or HMS auto-launches)

Requirements
------------
- Siril 1.3+ with sirilpy
- PyQt6
- GraXpert-AI.py (for AI background extraction)
- Optional: VeraLux Silentium, Cosmic Clarity for denoise options
"""

import sys
import os

try:
    import sirilpy as s
    from sirilpy import LogColor
except ImportError:
    print("Error: sirilpy module not found. This script must be run within Siril.")
    sys.exit(1)

s.ensure_installed("PyQt6", "numpy", "astroquery")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QGroupBox, QRadioButton, QButtonGroup,
    QCheckBox, QSlider, QProgressBar, QMessageBox, QFrame,
    QLineEdit, QCompleter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

VERSION = "1.2.0"

# ---------------------
#  COMMON DSO CATALOG
# ---------------------
# Popular deep sky objects for autocomplete suggestions
COMMON_DSO_NAMES = [
    # All 110 Messier objects
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10",
    "M11", "M12", "M13", "M14", "M15", "M16", "M17", "M18", "M19", "M20",
    "M21", "M22", "M23", "M24", "M25", "M26", "M27", "M28", "M29", "M30",
    "M31", "M32", "M33", "M34", "M35", "M36", "M37", "M38", "M39", "M40",
    "M41", "M42", "M43", "M44", "M45", "M46", "M47", "M48", "M49", "M50",
    "M51", "M52", "M53", "M54", "M55", "M56", "M57", "M58", "M59", "M60",
    "M61", "M62", "M63", "M64", "M65", "M66", "M67", "M68", "M69", "M70",
    "M71", "M72", "M73", "M74", "M75", "M76", "M77", "M78", "M79", "M80",
    "M81", "M82", "M83", "M84", "M85", "M86", "M87", "M88", "M89", "M90",
    "M91", "M92", "M93", "M94", "M95", "M96", "M97", "M98", "M99", "M100",
    "M101", "M102", "M103", "M104", "M105", "M106", "M107", "M108", "M109", "M110",
    # Popular NGC objects
    "NGC 224", "NGC 253", "NGC 281", "NGC 457", "NGC 663", "NGC 869", "NGC 884",
    "NGC 1333", "NGC 1499", "NGC 1501", "NGC 1502", "NGC 1528", "NGC 1931",
    "NGC 1952", "NGC 1977", "NGC 2024", "NGC 2070", "NGC 2146", "NGC 2174",
    "NGC 2237", "NGC 2244", "NGC 2264", "NGC 2359", "NGC 2392", "NGC 2403",
    "NGC 2438", "NGC 2683", "NGC 2841", "NGC 2903", "NGC 2976", "NGC 3077",
    "NGC 3184", "NGC 3190", "NGC 3344", "NGC 3372", "NGC 3521", "NGC 3628",
    "NGC 4244", "NGC 4258", "NGC 4449", "NGC 4490", "NGC 4559", "NGC 4565",
    "NGC 4631", "NGC 4656", "NGC 4725", "NGC 4736", "NGC 5005", "NGC 5033",
    "NGC 5128", "NGC 5139", "NGC 5195", "NGC 5457", "NGC 5866", "NGC 5907",
    "NGC 6210", "NGC 6302", "NGC 6334", "NGC 6357", "NGC 6369", "NGC 6503",
    "NGC 6543", "NGC 6559", "NGC 6572", "NGC 6633", "NGC 6712", "NGC 6720",
    "NGC 6781", "NGC 6818", "NGC 6819", "NGC 6826", "NGC 6888", "NGC 6894",
    "NGC 6905", "NGC 6914", "NGC 6934", "NGC 6939", "NGC 6940", "NGC 6946",
    "NGC 6960", "NGC 6974", "NGC 6979", "NGC 6992", "NGC 6995", "NGC 7000",
    "NGC 7008", "NGC 7009", "NGC 7023", "NGC 7027", "NGC 7129", "NGC 7139",
    "NGC 7293", "NGC 7331", "NGC 7380", "NGC 7479", "NGC 7510", "NGC 7538",
    "NGC 7606", "NGC 7635", "NGC 7640", "NGC 7662", "NGC 7789", "NGC 7822",
    # Popular IC objects
    "IC 59", "IC 63", "IC 342", "IC 405", "IC 410", "IC 417", "IC 434",
    "IC 443", "IC 447", "IC 1274", "IC 1283", "IC 1284", "IC 1318", "IC 1396",
    "IC 1613", "IC 1805", "IC 1848", "IC 1871", "IC 2118", "IC 2177", "IC 2574",
    "IC 2944", "IC 4592", "IC 4603", "IC 4604", "IC 4628", "IC 4665", "IC 4756",
    "IC 5067", "IC 5068", "IC 5070", "IC 5146",
    # Sharpless catalog (popular emission nebulae)
    "Sh2-101", "Sh2-106", "Sh2-129", "Sh2-132", "Sh2-155", "Sh2-157", "Sh2-171",
    "Sh2-173", "Sh2-174", "Sh2-188", "Sh2-223", "Sh2-224", "Sh2-232", "Sh2-235",
    "Sh2-240", "Sh2-245", "Sh2-252", "Sh2-254", "Sh2-261", "Sh2-276", "Sh2-279",
    # Popular named objects
    "Andromeda Galaxy", "Triangulum Galaxy", "Bode's Galaxy", "Cigar Galaxy",
    "Whirlpool Galaxy", "Pinwheel Galaxy", "Sunflower Galaxy", "Sombrero Galaxy",
    "Black Eye Galaxy", "Needle Galaxy", "Whale Galaxy", "Hockey Stick Galaxy",
    "Sculptor Galaxy", "Centaurus A", "Fireworks Galaxy",
    "Orion Nebula", "Running Man Nebula", "Horsehead Nebula", "Flame Nebula",
    "Crab Nebula", "Ring Nebula", "Dumbbell Nebula", "Owl Nebula",
    "Little Dumbbell Nebula", "Blue Snowball Nebula", "Cat's Eye Nebula",
    "Blinking Planetary Nebula", "Saturn Nebula", "Helix Nebula", "Ghost of Jupiter",
    "Eagle Nebula", "Pillars of Creation", "Lagoon Nebula", "Trifid Nebula",
    "Omega Nebula", "Swan Nebula", "Lobster Nebula", "War and Peace Nebula",
    "North America Nebula", "Pelican Nebula", "California Nebula",
    "Rosette Nebula", "Cone Nebula", "Christmas Tree Cluster",
    "Heart Nebula", "Soul Nebula", "Pacman Nebula", "Bubble Nebula",
    "Wizard Nebula", "Cave Nebula", "Cocoon Nebula", "Iris Nebula",
    "Elephant Trunk Nebula", "Flying Bat Nebula", "Squid Nebula",
    "Veil Nebula", "Eastern Veil", "Western Veil", "Pickering's Triangle",
    "Crescent Nebula", "Tulip Nebula", "Sadr Region", "Butterfly Nebula",
    "Carina Nebula", "Eta Carinae Nebula", "Running Chicken Nebula",
    "Tarantula Nebula", "Witch Head Nebula", "Seagull Nebula",
    "Jellyfish Nebula", "Medusa Nebula", "Thor's Helmet",
    "Monkey Head Nebula", "Flaming Star Nebula", "Tadpole Nebula",
    "Spider Nebula", "Starfish Cluster", "Gamma Cygni Nebula",
    "Double Cluster", "Pleiades", "Hyades", "Beehive Cluster", "Wild Duck Cluster",
    "Omega Centauri", "47 Tucanae", "Great Globular Cluster",
]


def resolve_object_coordinates(object_name):
    """
    Resolve an astronomical object name to RA/Dec coordinates using SIMBAD.

    Args:
        object_name: String like "M31", "NGC 7000", "Orion Nebula"

    Returns:
        tuple: (ra_decimal_degrees, dec_decimal_degrees) or None if not found
    """
    try:
        from astroquery.simbad import Simbad

        # Query SIMBAD
        result = Simbad.query_object(object_name)

        if result is None or len(result) == 0:
            return None

        # New astroquery (2024+) returns 'ra' and 'dec' in decimal degrees directly
        # Old versions used 'RA' and 'DEC' in sexagesimal format
        if 'ra' in result.colnames:
            # New format - already in decimal degrees
            ra_degrees = float(result['ra'][0])
            dec_degrees = float(result['dec'][0])
        elif 'RA' in result.colnames:
            # Old format - sexagesimal strings, need conversion
            ra_str = result['RA'][0]   # Format: "HH MM SS.ss"
            dec_str = result['DEC'][0]  # Format: "+DD MM SS.s"

            # Convert RA from hours to degrees
            ra_parts = ra_str.split()
            ra_hours = float(ra_parts[0])
            ra_mins = float(ra_parts[1])
            ra_secs = float(ra_parts[2]) if len(ra_parts) > 2 else 0.0
            ra_degrees = (ra_hours + ra_mins/60 + ra_secs/3600) * 15  # 15 deg per hour

            # Convert Dec to degrees
            dec_parts = dec_str.split()
            dec_sign = -1 if dec_parts[0].startswith('-') else 1
            dec_deg = abs(float(dec_parts[0]))
            dec_mins = float(dec_parts[1])
            dec_secs = float(dec_parts[2]) if len(dec_parts) > 2 else 0.0
            dec_degrees = dec_sign * (dec_deg + dec_mins/60 + dec_secs/3600)
        else:
            print(f"SIMBAD returned unexpected columns: {result.colnames}")
            return None

        return (ra_degrees, dec_degrees)

    except Exception as e:
        print(f"SIMBAD lookup error: {e}")
        return None


# ---------------------
#  DARK THEME
# ---------------------
DARK_STYLESHEET = """
QWidget { background-color: #2b2b2b; color: #e0e0e0; font-size: 10pt; }
QToolTip { background-color: #333333; color: #ffffff; border: 1px solid #88aaff; }
QGroupBox {
    border: 1px solid #444444;
    margin-top: 10px;
    font-weight: bold;
    border-radius: 4px;
    padding-top: 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #88aaff;
}
QLabel { color: #cccccc; }
QRadioButton, QCheckBox { color: #cccccc; spacing: 5px; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #666666;
    background: #3c3c3c;
    border-radius: 7px;
}
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator:checked {
    background: qradialgradient(cx:0.5, cy:0.5, radius: 0.4,
        fx:0.5, fy:0.5, stop:0 #ffffff, stop:1 #285299);
    border: 1px solid #88aaff;
}
QCheckBox::indicator:checked {
    background-color: #285299;
    border: 1px solid #88aaff;
}
QSlider::groove:horizontal {
    background: #444444;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #aaaaaa;
    width: 14px; height: 14px;
    margin: -4px 0;
    border-radius: 7px;
    border: 1px solid #555555;
}
QSlider::handle:horizontal:hover { background-color: #ffffff; }
QPushButton {
    background-color: #444444;
    color: #dddddd;
    border: 1px solid #666666;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover { background-color: #555555; border-color: #777777; }
QPushButton:disabled { background-color: #333333; color: #666666; }
QLineEdit {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 4px 8px;
    color: #e0e0e0;
}
QLineEdit:focus {
    border: 1px solid #88aaff;
}
QLineEdit::placeholder {
    color: #666666;
}
QPushButton#PrepButton {
    background-color: #285299;
    border: 1px solid #1e3f7a;
    font-size: 12pt;
    padding: 12px;
}
QPushButton#PrepButton:hover { background-color: #355ea1; }
QProgressBar {
    border: 1px solid #555555;
    border-radius: 3px;
    text-align: center;
    background-color: #333333;
}
QProgressBar::chunk { background-color: #285299; }
QFrame#Separator { background-color: #444444; }
"""


class PrepWorker(QThread):
    """Background thread for running the preparation pipeline."""
    progress = pyqtSignal(int, str)  # percent, status message
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, siril, options):
        super().__init__()
        self.siril = siril
        self.options = options

    def run(self):
        try:
            total_steps = self._count_steps()
            current_step = 0

            # Track plate solve status for PCC dependency
            self.plate_solve_succeeded = True  # Assume success unless plate solve runs and fails

            # Step 1: Background Extraction
            if self.options['bge_method'] != 'none':
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Extracting background...")
                self._run_background_extraction()

            # Step 2: Plate Solve
            if self.options['plate_solve']:
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Plate solving...")
                self._run_plate_solve()

            # Step 3: Photometric Color Calibration
            if self.options['pcc']:
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Color calibrating...")
                self._run_pcc()

            # Step 4: Denoise (optional)
            if self.options['denoise_method'] != 'none':
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, f"Denoising ({self.options['denoise_method']})...")
                self._run_denoise()

            # Step 5: Sharpen (optional) - after denoise to avoid amplifying noise
            if self.options['sharpen_method'] != 'none':
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, f"Sharpening ({self.options['sharpen_method']})...")
                self._run_sharpen()

            # Step 6: Super-Resolution (optional) - last step, applied to final image
            if self.options['superres']:
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Super-resolution (2x upscale)...")
                self._run_superres()

            self.progress.emit(100, "Complete!")
            self.finished.emit(True, "Image prepared successfully!")

        except Exception as e:
            self.finished.emit(False, str(e))

    def _count_steps(self):
        """Count total processing steps."""
        steps = 0
        if self.options['bge_method'] != 'none':
            steps += 1
        if self.options['plate_solve']:
            steps += 1
        if self.options['pcc']:
            steps += 1
        if self.options['denoise_method'] != 'none':
            steps += 1
        if self.options['sharpen_method'] != 'none':
            steps += 1
        if self.options['superres']:
            steps += 1
        return max(steps, 1)

    def _run_background_extraction(self):
        """Run background extraction based on selected method."""
        method = self.options['bge_method']

        if method == 'graxpert':
            smoothing = self.options['bge_smoothing']
            # Call GraXpert-AI.py via pyscript
            self.siril.cmd("pyscript", "GraXpert-AI.py",
                          "-bge", f"-smoothing={smoothing}")
        elif method == 'siril_rbf':
            # Use Siril's built-in RBF background extraction
            self.siril.cmd("subsky", "-rbf", "-samples=20",
                          "-tolerance=1.0", "-smooth=0.5")

    def _run_plate_solve(self):
        """Run plate solving with Vespera Pro optical parameters and target coordinates."""
        # Vespera Pro specs: 250.3mm focal length, 2.0µm pixel size (Sony IMX676)
        try:
            target_ra = self.options.get('target_ra')
            target_dec = self.options.get('target_dec')

            if target_ra is not None and target_dec is not None:
                # Use provided coordinates - Siril accepts decimal degrees separated by comma
                coord_str = f"{target_ra:.6f},{target_dec:.6f}"
                self.siril.log(f"Plate solving with center coordinates: RA={target_ra:.4f}°, Dec={target_dec:.4f}°",
                              color=LogColor.SALMON)
                self.siril.cmd("platesolve", coord_str, "-focal=250.3", "-pixelsize=2.0")
            else:
                # Attempt blind solve without coordinates
                self.siril.log("Plate solving without target coordinates (blind solve)...",
                              color=LogColor.SALMON)
                self.siril.cmd("platesolve", "-focal=250.3", "-pixelsize=2.0", "-blindpos")
        except s.CommandError as e:
            # Plate solve can fail if no stars found or other issues
            self.siril.log(f"Plate solve failed: {e}", color=LogColor.SALMON)
            # Set flag so PCC knows to skip
            self.plate_solve_succeeded = False
            return
        self.plate_solve_succeeded = True

    def _run_pcc(self):
        """Run photometric color calibration (requires successful plate solve)."""
        # PCC requires plate solved image - check if plate solve succeeded
        if hasattr(self, 'plate_solve_succeeded') and not self.plate_solve_succeeded:
            self.siril.log("Skipping PCC: plate solve did not succeed", color=LogColor.SALMON)
            return

        try:
            self.siril.cmd("pcc", "-limitmag=12")
        except s.CommandError as e:
            self.siril.log(f"PCC failed: {e}", color=LogColor.SALMON)

    def _run_denoise(self):
        """Run denoising based on selected method."""
        method = self.options['denoise_method']

        if method == 'silentium':
            self.siril.cmd("pyscript", "VeraLux_Silentium.py")
        elif method == 'graxpert':
            strength = self.options.get('denoise_strength', 0.5)
            self.siril.cmd("pyscript", "GraXpert-AI.py",
                          "-denoise", f"-strength={strength}")
        elif method == 'cosmic':
            self.siril.cmd("pyscript", "CosmicClarity_Denoise.py")

    def _run_sharpen(self):
        """Run sharpening based on selected method."""
        method = self.options['sharpen_method']

        if method == 'cosmic':
            # Cosmic Clarity sharpening - uses both stellar and non-stellar modes
            self.siril.cmd("pyscript", "CosmicClarity_Sharpen.py")
        elif method == 'unsharp':
            # Siril's built-in unsharp mask
            # Parameters: sigma (blur radius), amount (strength)
            # sigma=1.5 and amount=1.0 are good defaults for astro images
            self.siril.cmd("unsharp", "1.5", "1.0")

    def _run_superres(self):
        """Run AI super-resolution (2x upscale)."""
        self.siril.log("Running Cosmic Clarity Super-Resolution (2x)...", color=LogColor.SALMON)
        self.siril.log("This may take several minutes...", color=LogColor.SALMON)
        # Cosmic Clarity Superres - 2x upscale
        self.siril.cmd("pyscript", "CosmicClarity_Superres.py")


class VesperaQuickPrepWindow(QMainWindow):
    """Main window for Vespera Quick Prep plugin."""

    def __init__(self, siril):
        super().__init__()
        self.siril = siril
        self.worker = None
        self.settings = QSettings("VesperaSiril", "QuickPrep")

        self.setWindowTitle(f"Vespera Quick Prep v{VERSION}")
        self.setMinimumWidth(400)
        self.setStyleSheet(DARK_STYLESHEET)

        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        """Build the user interface."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel("Vespera Quick Prep")
        header.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header.setStyleSheet("color: #88aaff;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        subtitle = QLabel("One-click preparation for VeraLux HMS")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888888; font-size: 9pt;")
        layout.addWidget(subtitle)

        # Separator
        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # Background Extraction Group
        bge_group = QGroupBox("Background Extraction")
        bge_layout = QVBoxLayout(bge_group)

        self.bge_button_group = QButtonGroup(self)

        self.bge_graxpert = QRadioButton("GraXpert AI (Recommended)")
        self.bge_graxpert.setToolTip(
            "AI-based background extraction.\n"
            "Best for complex gradients and light pollution."
        )
        self.bge_graxpert.setChecked(True)
        self.bge_button_group.addButton(self.bge_graxpert, 0)
        bge_layout.addWidget(self.bge_graxpert)

        # Smoothing slider for GraXpert
        smooth_layout = QHBoxLayout()
        smooth_layout.setContentsMargins(20, 0, 0, 0)
        smooth_label = QLabel("Smoothing:")
        smooth_label.setStyleSheet("color: #888888;")
        smooth_layout.addWidget(smooth_label)

        self.smoothing_slider = QSlider(Qt.Orientation.Horizontal)
        self.smoothing_slider.setRange(0, 100)
        self.smoothing_slider.setValue(50)
        self.smoothing_slider.setFixedWidth(120)
        smooth_layout.addWidget(self.smoothing_slider)

        self.smoothing_value = QLabel("0.50")
        self.smoothing_value.setFixedWidth(35)
        smooth_layout.addWidget(self.smoothing_value)
        smooth_layout.addStretch()
        bge_layout.addLayout(smooth_layout)

        self.smoothing_slider.valueChanged.connect(
            lambda v: self.smoothing_value.setText(f"{v/100:.2f}")
        )

        self.bge_rbf = QRadioButton("Siril RBF (Fast fallback)")
        self.bge_rbf.setToolTip(
            "Radial Basis Function interpolation.\n"
            "Faster, good for simpler gradients."
        )
        self.bge_button_group.addButton(self.bge_rbf, 1)
        bge_layout.addWidget(self.bge_rbf)

        self.bge_none = QRadioButton("Skip (already extracted)")
        self.bge_button_group.addButton(self.bge_none, 2)
        bge_layout.addWidget(self.bge_none)

        layout.addWidget(bge_group)

        # Calibration Group
        cal_group = QGroupBox("Calibration")
        cal_layout = QVBoxLayout(cal_group)

        self.plate_solve_cb = QCheckBox("Plate Solve")
        self.plate_solve_cb.setChecked(True)
        self.plate_solve_cb.setToolTip(
            "Determine image coordinates from star patterns.\n"
            "Required for Photometric Color Calibration."
        )
        cal_layout.addWidget(self.plate_solve_cb)

        # Object name input for plate solving
        object_layout = QHBoxLayout()
        object_layout.setContentsMargins(20, 0, 0, 0)  # Indent under checkbox

        object_label = QLabel("Target:")
        object_label.setStyleSheet("color: #888888;")
        object_layout.addWidget(object_label)

        self.object_input = QLineEdit()
        self.object_input.setPlaceholderText("e.g., M31, NGC 7000, Orion Nebula")
        self.object_input.setToolTip(
            "Enter the target object name for plate solving.\n"
            "Examples: M31, NGC 7000, Orion Nebula\n"
            "Coordinates will be looked up from SIMBAD."
        )
        # Add autocomplete for common DSO names
        completer = QCompleter(COMMON_DSO_NAMES)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.object_input.setCompleter(completer)
        object_layout.addWidget(self.object_input, 1)

        self.lookup_btn = QPushButton("Lookup")
        self.lookup_btn.setFixedWidth(70)
        self.lookup_btn.setToolTip("Look up coordinates from SIMBAD database")
        self.lookup_btn.clicked.connect(self._on_lookup_clicked)
        object_layout.addWidget(self.lookup_btn)

        cal_layout.addLayout(object_layout)

        # Coordinate display label
        self.coord_label = QLabel("")
        self.coord_label.setStyleSheet("color: #888888; font-size: 9pt; margin-left: 20px;")
        cal_layout.addWidget(self.coord_label)

        # Store resolved coordinates
        self.resolved_ra = None
        self.resolved_dec = None

        self.pcc_cb = QCheckBox("Photometric Color Calibration (PCC)")
        self.pcc_cb.setChecked(True)
        self.pcc_cb.setToolTip(
            "Calibrate colors using Gaia star catalog.\n"
            "Produces accurate, natural star colors."
        )
        cal_layout.addWidget(self.pcc_cb)

        layout.addWidget(cal_group)

        # Denoise Group
        denoise_group = QGroupBox("Denoise (Optional)")
        denoise_layout = QVBoxLayout(denoise_group)

        self.denoise_button_group = QButtonGroup(self)

        self.denoise_none = QRadioButton("None")
        self.denoise_none.setChecked(True)
        self.denoise_button_group.addButton(self.denoise_none, 0)
        denoise_layout.addWidget(self.denoise_none)

        self.denoise_silentium = QRadioButton("VeraLux Silentium (wavelet, PSF-aware)")
        self.denoise_silentium.setToolTip(
            "Physics-based wavelet denoiser.\n"
            "Uses actual star geometry for protection.\n"
            "Deterministic and precise."
        )
        self.denoise_button_group.addButton(self.denoise_silentium, 1)
        denoise_layout.addWidget(self.denoise_silentium)

        self.denoise_graxpert = QRadioButton("GraXpert AI")
        self.denoise_graxpert.setToolTip(
            "AI neural network denoiser.\n"
            "Good general-purpose option.\n"
            "May occasionally add artifacts."
        )
        self.denoise_button_group.addButton(self.denoise_graxpert, 2)
        denoise_layout.addWidget(self.denoise_graxpert)

        self.denoise_cosmic = QRadioButton("Cosmic Clarity")
        self.denoise_cosmic.setToolTip(
            "Alternative AI denoiser with different training.\n"
            "Try if GraXpert produces artifacts."
        )
        self.denoise_button_group.addButton(self.denoise_cosmic, 3)
        denoise_layout.addWidget(self.denoise_cosmic)

        layout.addWidget(denoise_group)

        # Sharpen Group
        sharpen_group = QGroupBox("Sharpen (Optional)")
        sharpen_layout = QVBoxLayout(sharpen_group)

        self.sharpen_button_group = QButtonGroup(self)

        self.sharpen_none = QRadioButton("None")
        self.sharpen_none.setChecked(True)
        self.sharpen_button_group.addButton(self.sharpen_none, 0)
        sharpen_layout.addWidget(self.sharpen_none)

        self.sharpen_cosmic = QRadioButton("Cosmic Clarity (AI stellar + non-stellar)")
        self.sharpen_cosmic.setToolTip(
            "AI-based sharpening with separate\n"
            "stellar and non-stellar modes.\n"
            "Best overall quality."
        )
        self.sharpen_button_group.addButton(self.sharpen_cosmic, 1)
        sharpen_layout.addWidget(self.sharpen_cosmic)

        self.sharpen_unsharp = QRadioButton("Siril Unsharp Mask (fast)")
        self.sharpen_unsharp.setToolTip(
            "Classic unsharp mask algorithm.\n"
            "Fast but less sophisticated.\n"
            "Good for quick results."
        )
        self.sharpen_button_group.addButton(self.sharpen_unsharp, 2)
        sharpen_layout.addWidget(self.sharpen_unsharp)

        layout.addWidget(sharpen_group)

        # Super-Resolution Group
        superres_group = QGroupBox("Super-Resolution (Optional)")
        superres_layout = QVBoxLayout(superres_group)

        self.superres_cb = QCheckBox("Cosmic Clarity 2x Upscale")
        self.superres_cb.setChecked(False)
        self.superres_cb.setToolTip(
            "AI-powered 2x resolution enhancement.\n"
            "Great for printing and display.\n"
            "⚠️ SLOW: Best applied after stretching.\n"
            "Consider using post-HMS instead."
        )
        superres_layout.addWidget(self.superres_cb)

        # Warning label for super-res
        superres_warning = QLabel("⚠️ Super-res is slow and typically applied post-stretch")
        superres_warning.setStyleSheet("color: #ffaa44; font-size: 8pt; margin-left: 20px;")
        superres_layout.addWidget(superres_warning)

        layout.addWidget(superres_group)

        # Launch HMS option
        self.launch_hms_cb = QCheckBox("Launch VeraLux HMS when complete")
        self.launch_hms_cb.setChecked(True)
        self.launch_hms_cb.setToolTip(
            "Automatically open HyperMetric Stretch\n"
            "after preparation is complete."
        )
        layout.addWidget(self.launch_hms_cb)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #888888;")
        layout.addWidget(self.status_label)

        # Prep button
        self.prep_button = QPushButton("Prep Image")
        self.prep_button.setObjectName("PrepButton")
        self.prep_button.clicked.connect(self._on_prep_clicked)
        layout.addWidget(self.prep_button)

        # Footer
        footer = QLabel("For Vespera Pro 16-bit TIFFs")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color: #555555; font-size: 8pt;")
        layout.addWidget(footer)

    def _on_lookup_clicked(self):
        """Handle Lookup button click - resolve object name to coordinates."""
        object_name = self.object_input.text().strip()

        if not object_name:
            self.coord_label.setText("Enter an object name first")
            self.coord_label.setStyleSheet("color: #ff8888; font-size: 9pt; margin-left: 20px;")
            return

        # Show searching status
        self.coord_label.setText("Searching SIMBAD...")
        self.coord_label.setStyleSheet("color: #888888; font-size: 9pt; margin-left: 20px;")
        self.lookup_btn.setEnabled(False)
        QApplication.processEvents()  # Update UI

        # Resolve coordinates
        coords = resolve_object_coordinates(object_name)

        self.lookup_btn.setEnabled(True)

        if coords:
            self.resolved_ra, self.resolved_dec = coords
            # Format for display
            ra_h = self.resolved_ra / 15  # Convert degrees to hours
            ra_h_int = int(ra_h)
            ra_m = (ra_h - ra_h_int) * 60
            ra_m_int = int(ra_m)
            ra_s = (ra_m - ra_m_int) * 60

            dec_sign = "+" if self.resolved_dec >= 0 else "-"
            dec_abs = abs(self.resolved_dec)
            dec_d_int = int(dec_abs)
            dec_m = (dec_abs - dec_d_int) * 60
            dec_m_int = int(dec_m)
            dec_s = (dec_m - dec_m_int) * 60

            coord_text = f"RA: {ra_h_int:02d}h {ra_m_int:02d}m {ra_s:.1f}s  Dec: {dec_sign}{dec_d_int}° {dec_m_int}' {dec_s:.1f}\""
            self.coord_label.setText(f"✓ {coord_text}")
            self.coord_label.setStyleSheet("color: #88ff88; font-size: 9pt; margin-left: 20px;")
            self.siril.log(f"Resolved '{object_name}' → RA: {self.resolved_ra:.4f}°, Dec: {self.resolved_dec:.4f}°",
                          color=LogColor.GREEN)
        else:
            self.resolved_ra = None
            self.resolved_dec = None
            self.coord_label.setText(f"✗ Object '{object_name}' not found")
            self.coord_label.setStyleSheet("color: #ff8888; font-size: 9pt; margin-left: 20px;")

    def _load_settings(self):
        """Load saved settings."""
        bge = self.settings.value("bge_method", 0, type=int)
        self.bge_button_group.button(bge).setChecked(True)

        smoothing = self.settings.value("smoothing", 50, type=int)
        self.smoothing_slider.setValue(smoothing)

        self.plate_solve_cb.setChecked(
            self.settings.value("plate_solve", True, type=bool))

        # Load saved object name
        object_name = self.settings.value("object_name", "", type=str)
        self.object_input.setText(object_name)

        self.pcc_cb.setChecked(
            self.settings.value("pcc", True, type=bool))

        denoise = self.settings.value("denoise_method", 0, type=int)
        self.denoise_button_group.button(denoise).setChecked(True)

        sharpen = self.settings.value("sharpen_method", 0, type=int)
        self.sharpen_button_group.button(sharpen).setChecked(True)

        self.superres_cb.setChecked(
            self.settings.value("superres", False, type=bool))

        self.launch_hms_cb.setChecked(
            self.settings.value("launch_hms", True, type=bool))

    def _save_settings(self):
        """Save current settings."""
        self.settings.setValue("bge_method", self.bge_button_group.checkedId())
        self.settings.setValue("smoothing", self.smoothing_slider.value())
        self.settings.setValue("plate_solve", self.plate_solve_cb.isChecked())
        self.settings.setValue("object_name", self.object_input.text())
        self.settings.setValue("pcc", self.pcc_cb.isChecked())
        self.settings.setValue("denoise_method", self.denoise_button_group.checkedId())
        self.settings.setValue("sharpen_method", self.sharpen_button_group.checkedId())
        self.settings.setValue("superres", self.superres_cb.isChecked())
        self.settings.setValue("launch_hms", self.launch_hms_cb.isChecked())

    def _get_options(self):
        """Collect current options into a dictionary."""
        bge_id = self.bge_button_group.checkedId()
        bge_methods = {0: 'graxpert', 1: 'siril_rbf', 2: 'none'}

        denoise_id = self.denoise_button_group.checkedId()
        denoise_methods = {0: 'none', 1: 'silentium', 2: 'graxpert', 3: 'cosmic'}

        sharpen_id = self.sharpen_button_group.checkedId()
        sharpen_methods = {0: 'none', 1: 'cosmic', 2: 'unsharp'}

        return {
            'bge_method': bge_methods.get(bge_id, 'graxpert'),
            'bge_smoothing': self.smoothing_slider.value() / 100.0,
            'plate_solve': self.plate_solve_cb.isChecked(),
            'object_name': self.object_input.text().strip(),
            'target_ra': self.resolved_ra,
            'target_dec': self.resolved_dec,
            'pcc': self.pcc_cb.isChecked(),
            'denoise_method': denoise_methods.get(denoise_id, 'none'),
            'denoise_strength': 0.5,
            'sharpen_method': sharpen_methods.get(sharpen_id, 'none'),
            'superres': self.superres_cb.isChecked(),
            'launch_hms': self.launch_hms_cb.isChecked()
        }

    def _on_prep_clicked(self):
        """Handle Prep button click."""
        # Check if an image is loaded using correct API method
        if not self.siril.is_image_loaded():
            QMessageBox.warning(self, "No Image",
                "Please load a Vespera TIFF image first.")
            return

        self._save_settings()
        options = self._get_options()

        # Validate at least one operation selected
        if (options['bge_method'] == 'none' and
            not options['plate_solve'] and
            not options['pcc'] and
            options['denoise_method'] == 'none'):
            QMessageBox.information(self, "Nothing to do",
                "Please select at least one operation.")
            return

        # If plate solve is enabled and we have an object name but no coordinates, try to resolve
        if options['plate_solve'] and options['object_name'] and options['target_ra'] is None:
            # Auto-lookup coordinates
            self.siril.log(f"Auto-resolving coordinates for '{options['object_name']}'...",
                          color=LogColor.SALMON)
            coords = resolve_object_coordinates(options['object_name'])
            if coords:
                self.resolved_ra, self.resolved_dec = coords
                options['target_ra'] = self.resolved_ra
                options['target_dec'] = self.resolved_dec
                self.coord_label.setText(f"✓ Auto-resolved")
                self.coord_label.setStyleSheet("color: #88ff88; font-size: 9pt; margin-left: 20px;")
                self.siril.log(f"Resolved '{options['object_name']}' → RA: {self.resolved_ra:.4f}°, Dec: {self.resolved_dec:.4f}°",
                              color=LogColor.GREEN)
            else:
                QMessageBox.warning(self, "Object Not Found",
                    f"Could not resolve '{options['object_name']}' to coordinates.\n\n"
                    "Please check the object name or enter a different target.")
                return

        # Disable UI during processing
        self.prep_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Start worker thread
        self.worker = PrepWorker(self.siril, options)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, percent, message):
        """Handle progress updates."""
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_finished(self, success, message):
        """Handle completion."""
        self.prep_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        if success:
            self.status_label.setText(message)
            self.status_label.setStyleSheet("color: #88ff88;")

            # Launch HMS if requested
            if self.launch_hms_cb.isChecked():
                try:
                    self.siril.cmd("pyscript", "VeraLux_HyperMetric_Stretch.py")
                    self.close()  # Close Quick Prep window
                except s.CommandError as e:
                    self.siril.log(f"Could not launch HMS: {e}", color=LogColor.SALMON)
        else:
            self.status_label.setText(f"Error: {message}")
            self.status_label.setStyleSheet("color: #ff8888;")
            QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        """Handle window close."""
        self._save_settings()
        event.accept()


def main():
    """Main entry point."""
    try:
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)

        siril = s.SirilInterface()

        # Connect to Siril with specific exception handling
        try:
            siril.connect()
        except s.SirilConnectionError:
            QMessageBox.critical(None, "Connection Error",
                               "Could not connect to Siril.\n"
                               "Make sure Siril is running.")
            return

        # Check Siril version requirement
        try:
            siril.cmd("requires", "1.3.0")
        except s.CommandError:
            QMessageBox.critical(None, "Version Error",
                               "This plugin requires Siril 1.3.0 or later.")
            return

        siril.log("Vespera Quick Prep started", color=LogColor.GREEN)

        window = VesperaQuickPrepWindow(siril)
        window.show()

        app.exec()

    except Exception as e:
        # Can't use siril.log here since siril may not be connected
        print(f"Vespera Quick Prep error: {e}")
        raise


if __name__ == "__main__":
    main()
