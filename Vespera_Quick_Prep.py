##############################################
# Vespera Quick Prep
# One-Click Image Preparation Pipeline
# For Vespera Pro Smart Telescope
##############################################

# SPDX-License-Identifier: Apache-2.0
# Version 1.0.1

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
import threading

try:
    import sirilpy as s
    from sirilpy import SirilInterface, SirilError, LogColor
except ImportError:
    print("Error: sirilpy module not found. This script must be run within Siril.")
    sys.exit(1)

s.ensure_installed("PyQt6", "numpy")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QGroupBox, QRadioButton, QButtonGroup,
    QCheckBox, QSlider, QProgressBar, QMessageBox, QFrame,
    QLineEdit, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

VERSION = "1.0.1"

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


class VesperaPlateSolver:
    """Advanced plate solving for Vespera Pro with astrometry.net integration."""

    def __init__(self, siril_interface, filename=None):
        self.siril = siril_interface
        self.filename = filename
        self.dso_name = None
        self.applied_coordinates = None
        self.focal_length_mm = 249.47
        self.pixel_size_um = 2.00

        # Extract DSO name immediately
        if filename:
            self._extract_dso_name()

    def _extract_dso_name(self):
        """Extract and validate DSO name from filename."""
        try:
            import os

            filename = os.path.basename(str(self.filename))
            filename_without_ext = os.path.splitext(filename)[0]

            # Split on first underscore or dash
            if '_' in filename_without_ext:
                dso_name = filename_without_ext.split('_', 1)[0].strip()
            elif '-' in filename_without_ext:
                dso_name = filename_without_ext.split('-', 1)[0].strip()
            else:
                dso_name = filename_without_ext.strip()

            # Validate the DSO name
            if not dso_name or not dso_name.strip():
                self.dso_name = None
                return

            # Check if DSO name contains only valid characters
            valid_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -')
            if all(c in valid_chars for c in dso_name):
                self.dso_name = dso_name
            else:
                self.dso_name = None

        except Exception as e:
            self.siril.log(f"DSO extraction error: {e}", LogColor.SALMON)
            self.dso_name = None

    def siril_plate_solve(self):
        """Execute plate solving with siril command."""
        try:
            command = "platesolve"
            
            if self.applied_coordinates:
                ra, dec = self.applied_coordinates
                command += f' "{ra}, {dec}"'

            command += f" -focal={self.focal_length_mm} -pixelsize={self.pixel_size_um}"
            
            self.siril.cmd(command)
            return True

        except Exception as e:
            self.siril.log(f"Plate solve error: {e}", LogColor.SALMON)
            return False



    def _query_simbad_coordinates(self, dso_name):
        """Query SIMBAD database to get RA/DEC coordinates."""
        import urllib.parse
        import urllib.request

        try:
            base_url = "https://simbad.cds.unistra.fr/simbad/sim-id"

            params = {
                'output.format': 'ASCII',
                'Ident': dso_name
            }

            url = f"{base_url}?{urllib.parse.urlencode(params)}"

            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read().decode('utf-8')

                ra = None
                dec = None

                for line in data.split('\n'):
                    if line.startswith('RA(J2000)'):
                        parts = line.split()
                        if len(parts) >= 2:
                            ra = parts[1]
                    elif line.startswith('DE(J2000)'):
                        parts = line.split()
                        if len(parts) >= 2:
                            dec = parts[1]
                    elif 'Coordinates(' in line and ':' in line:
                        coord_part = line.split(':', 1)[1].strip()
                        coord_parts = coord_part.split()
                        if len(coord_parts) >= 3:
                            ra_h, ra_m, ra_s = coord_parts[0], coord_parts[1], coord_parts[2]
                            ra = f"{ra_h}:{ra_m}:{ra_s}"
                            
                            dec_d, dec_m = coord_parts[3], coord_parts[4]
                            dec_s = coord_parts[5] if len(coord_parts) > 5 else "0"
                            dec = f"{dec_d}:{dec_m}:{dec_s}"

                if ra and dec:
                    self.siril.log(f"SIMBAD coordinates found: RA={ra}, DEC={dec}", LogColor.GREEN)
                    return ra, dec
                else:
                    self.siril.log("No coordinates found in SIMBAD response", LogColor.SALMON)
                    return None

        except Exception as e:
            self.siril.log(f"SIMBAD query error: {e}", LogColor.SALMON)
            return None

class PrepWorker(QThread):
    """Background thread for running the preparation pipeline."""
    progress = pyqtSignal(int, str)  # percent, status message
    finished = pyqtSignal(bool, str)  # success, message
    manual_dso_request = pyqtSignal()  # Request manual DSO entry
    manual_dso_provided = pyqtSignal(str)  # Manual DSO name provided
    update_dso_input_visibility = pyqtSignal()  # Update DSO input visibility

    def __init__(self, siril, options, dso_name=None):
        super().__init__()
        self.siril = siril
        self.options = options
        self.manual_dso_name = dso_name
        self.manual_dso_event = threading.Event()
        self.provided_dso_name = None

    def run(self):
        try:
            # Count total processing steps
            total_steps = (
                1 if self.options['bge_method'] != 'none' else 0 +
                1 if self.options['plate_solve'] else 0 +
                1 if self.options['pcc'] else 0 +
                1 if self.options['denoise_method'] != 'none' else 0
            )
            total_steps = max(total_steps, 1)
            current_step = 0

            # Step 1: Background Extraction
            if self.options['bge_method'] != 'none':
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Extracting background...")
                self._run_background_extraction()

            # Step 2: Plate Solve
            plate_solve_success = False
            if self.options['plate_solve']:
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Plate solving...")
                
                plate_solve_success = self._run_plate_solve()
                if not plate_solve_success:
                    self.siril.log("Plate solving failed, continuing with other processing...", LogColor.SALMON)
 
            # Step 3: Photometric Color Calibration (only if plate solving succeeded)
            if self.options['pcc'] and plate_solve_success:
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, "Color calibrating...")
                self.siril.log("Running Photometric Color Calibration...", LogColor.BLUE)
                self.siril.cmd("pcc", "-limitmag=12")
            elif self.options['pcc'] and not plate_solve_success:
                self.siril.log("Skipping PCC - requires plate solved image", LogColor.SALMON)

            # Step 4: Denoise (optional)
            if self.options['denoise_method'] != 'none':
                current_step += 1
                pct = int(current_step / total_steps * 100)
                self.progress.emit(pct, f"Denoising ({self.options['denoise_method']})...")
                
                method = self.options['denoise_method']
                if method == 'silentium':
                    self.siril.cmd("pyscript", "VeraLux_Silentium.py")
                elif method == 'graxpert':
                    self.siril.cmd("pyscript", "GraXpert-AI.py", "-denoise", f"-strength={self.options.get('denoise_strength', 0.5)}")
                elif method == 'cosmic':
                    self.siril.cmd("pyscript", "CosmicClarity_Denoise.py")

            self.progress.emit(100, "Complete!")
            self.finished.emit(True, "Image prepared successfully!")

        except Exception as e:
            self.finished.emit(False, str(e))

    def _wait_for_manual_dso_entry(self):
        """Wait for manual DSO entry from the main thread."""
        try:
            # Wait for the main thread to provide the DSO name
            self.manual_dso_event.wait(timeout=30.0)  # 30 second timeout
            
            # Return the provided DSO name (or None if timeout/cancelled)
            return self.provided_dso_name
                 
        except Exception as e:
            self.siril.log(f"Waiting for manual DSO entry failed: {e}", LogColor.SALMON)
            return None

class VesperaQuickPrepWindow(QMainWindow):
    """Main window for Vespera Quick Prep plugin."""

    def __init__(self, siril):
        super().__init__()
        self.siril = siril
        self.worker = None
        self.settings = QSettings("VesperaSiril", "QuickPrep")
        self.simbad_query_failed = False

        self.setWindowTitle(f"Vespera Quick Prep v{VERSION}")
        self.setMinimumWidth(400)
        self.setStyleSheet(DARK_STYLESHEET)

        self._build_ui()
        
        # Load saved settings
        bge = self.settings.value("bge_method", 0, type=int)
        self.bge_button_group.button(bge).setChecked(True)

        smoothing = self.settings.value("smoothing", 50, type=int)
        self.smoothing_slider.setValue(smoothing)

        self.plate_solve_cb.setChecked(
            self.settings.value("plate_solve", True, type=bool))
        self.pcc_cb.setChecked(
            self.settings.value("pcc", True, type=bool))

        denoise = self.settings.value("denoise_method", 0, type=int)
        self.denoise_button_group.button(denoise).setChecked(True)

        self.launch_hms_cb.setChecked(
            self.settings.value("launch_hms", True, type=bool))
        
        self._update_dso_input_visibility()  # Initialize visibility

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
            "Attempt plate solving based on file name.\n"
            "Manual entry fallback option.\n"
            "Processing continues even if plate solving fails."
        )
        cal_layout.addWidget(self.plate_solve_cb)

        # Add DSO name input field
        self.dso_input = QLineEdit()
        self.dso_input.setPlaceholderText("Enter DSO name (e.g., M42, IC 342)")
        self.dso_input.setToolTip(
            "Manually enter DSO name for plate solving if automatic extraction fails.\n"
            "Examples: M42, IC 342, NGC 7000"
        )
        self.dso_input.setVisible(False)  # Only show when needed
        cal_layout.addWidget(self.dso_input)

        # Connect plate solve checkbox to visibility control
        self.plate_solve_cb.stateChanged.connect(self._update_dso_input_visibility)

        self.pcc_cb = QCheckBox("Photometric Color Calibration (PCC)")
        self.pcc_cb.setChecked(True)
        
        # Force plate solve when PCC is enabled (PCC requires plate solving)
        self.pcc_cb.stateChanged.connect(lambda state: (
            self.plate_solve_cb.setChecked(True) if state == Qt.CheckState.Checked.value and not self.plate_solve_cb.isChecked() else None,
            self.siril.log("Plate solving enabled (required for PCC)", LogColor.BLUE) if state == Qt.CheckState.Checked.value and not self.plate_solve_cb.isChecked() else None
        )[0])
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

    def _update_dso_input_visibility(self):
        """Show DSO input when needed for plate solving."""
        try:
            current_filename = self.siril.get_image_filename()
            current_filename = current_filename if current_filename and len(current_filename.strip()) > 0 else None
        except Exception:
            current_filename = None
        
        show_input = (self.plate_solve_cb.isChecked() and
                      (not current_filename or 
                       getattr(self, 'simbad_query_failed', False)))
        
        self.dso_input.setVisible(show_input)
        
        if show_input:
            self.siril.log("Please enter DSO name for plate solving", LogColor.BLUE)

    def _on_prep_clicked(self):
        """Handle Prep button click."""
        # Check if an image is loaded
        try:
            img_shape = self.siril.get_image_shape()
            if img_shape is None:
                QMessageBox.warning(self, "No Image",
                    "Please load a Vespera TIFF image first.")
                return
        except Exception as e:
            QMessageBox.warning(self, "No Image",
                "Please load a Vespera TIFF image first.")
            return

        # Save current settings
        self.settings.setValue("bge_method", self.bge_button_group.checkedId())
        self.settings.setValue("smoothing", self.smoothing_slider.value())
        self.settings.setValue("plate_solve", self.plate_solve_cb.isChecked())
        self.settings.setValue("pcc", self.pcc_cb.isChecked())
        self.settings.setValue("denoise_method", self.denoise_button_group.checkedId())
        self.settings.setValue("launch_hms", self.launch_hms_cb.isChecked())
        
        # Collect current options
        bge_methods = ['graxpert', 'siril_rbf', 'none']
        denoise_methods = ['none', 'silentium', 'graxpert', 'cosmic']
        
        options = {
            'bge_method': bge_methods[self.bge_button_group.checkedId()],
            'bge_smoothing': self.smoothing_slider.value() / 100.0,
            'plate_solve': self.plate_solve_cb.isChecked(),
            'pcc': self.pcc_cb.isChecked(),
            'denoise_method': denoise_methods[self.denoise_button_group.checkedId()],
            'denoise_strength': 0.5,
            'launch_hms': self.launch_hms_cb.isChecked(),
            'optimize_format': True,
            'continue_on_failure': True
        }

        # Validate at least one operation selected
        if (options['bge_method'] == 'none' and
            not options['plate_solve'] and
            not options['pcc'] and
            options['denoise_method'] == 'none'):
            QMessageBox.information(self, "Nothing to do",
                "Please select at least one operation.")
            return

        # Disable UI during processing
        self.prep_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Start worker thread
        dso_name = self.dso_input.text().strip() if self.dso_input.isVisible() else None
        self.worker = PrepWorker(self.siril, options, dso_name)
        self.worker.progress.connect(lambda percent, message: (
            self.progress_bar.setValue(percent),
            self.status_label.setText(message)
        ))
        self.worker.finished.connect(lambda success, message: (
            self.prep_button.setEnabled(True),
            self.progress_bar.setVisible(False),
            (self.status_label.setText(message), self.status_label.setStyleSheet("color: #88ff88;")) if success else (
                self.status_label.setText(f"Error: {message}"),
                self.status_label.setStyleSheet("color: #ff8888;"),
                QMessageBox.critical(self, "Error", message)
            ),
            self.siril.cmd("pyscript", "VeraLux_HyperMetric_Stretch.py") if success and self.launch_hms_cb.isChecked() else None,
            self.close() if success and self.launch_hms_cb.isChecked() else None
        ))
        self.worker.manual_dso_request.connect(self._on_manual_dso_request)
        self.worker.update_dso_input_visibility.connect(self._update_dso_input_visibility)
        self.worker.start()

    def _on_manual_dso_request(self):
        """Handle manual DSO request from worker thread."""
        try:
            # Show input dialog in main thread
            dso_name, ok = QInputDialog.getText(
                self,
                "Manual DSO Entry Required",
                "SIMBAD query failed. Please enter DSO name (e.g., M42, IC 342):",
                QLineEdit.EchoMode.Normal,
                ""
            )
            
            if ok and dso_name.strip():
                self.siril.log(f"Using manual DSO entry: {dso_name}", LogColor.BLUE)
                # Store the manual DSO name and signal the worker
                if self.worker:
                    self.worker.provided_dso_name = dso_name.strip()
            else:
                self.siril.log("Manual DSO entry cancelled", LogColor.SALMON)
                # Signal the worker that no DSO name was provided
                if self.worker:
                    self.worker.provided_dso_name = None
                
            # Always signal the worker to continue
            if self.worker:
                self.worker.manual_dso_event.set()

        except Exception as e:
            self.siril.log(f"Manual DSO entry failed: {e}", LogColor.SALMON)
            # Signal the worker that an error occurred
            if self.worker:
                self.worker.provided_dso_name = None
                self.worker.manual_dso_event.set()

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
                except Exception as e:
                    self.siril.log(f"Could not launch HMS: {e}", LogColor.SALMON)
        else:
            self.status_label.setText(f"Error: {message}")
            self.status_label.setStyleSheet("color: #ff8888;")
            QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        """Handle window close."""
        # Save current settings
        self.settings.setValue("bge_method", self.bge_button_group.checkedId())
        self.settings.setValue("smoothing", self.smoothing_slider.value())
        self.settings.setValue("plate_solve", self.plate_solve_cb.isChecked())
        self.settings.setValue("pcc", self.pcc_cb.isChecked())
        self.settings.setValue("denoise_method", self.denoise_button_group.checkedId())
        self.settings.setValue("launch_hms", self.launch_hms_cb.isChecked())
        
        event.accept()


def main():
    """Main entry point."""
    siril = SirilInterface()
    app = QApplication.instance() or QApplication(sys.argv)

    try:
        siril.connect()
        siril.log("Vespera Quick Prep started", LogColor.GREEN)
        
        window = VesperaQuickPrepWindow(siril)
        window.show()
        app.exec()
    except Exception as e:
        siril.log(f"Error: {e}", LogColor.RED)
        raise
    finally:
        siril.disconnect()


if __name__ == "__main__":
    main()
