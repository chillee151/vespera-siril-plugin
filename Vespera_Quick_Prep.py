##############################################
# Vespera Quick Prep
# One-Click Image Preparation Pipeline
# For Vespera Pro Smart Telescope
##############################################

# SPDX-License-Identifier: Apache-2.0
# Version 1.0.0

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
    from sirilpy import Siril, SirilError, LogColor
except ImportError:
    print("Error: sirilpy module not found. This script must be run within Siril.")
    sys.exit(1)

s.ensure_installed("PyQt6", "numpy")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QGroupBox, QRadioButton, QButtonGroup,
    QCheckBox, QSlider, QProgressBar, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

VERSION = "1.0.0"

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
        """Run plate solving."""
        try:
            self.siril.cmd("platesolve")
        except SirilError as e:
            # Plate solve can fail if already solved or no stars found
            s.log(f"Plate solve note: {e}", LogColor.SALMON)

    def _run_pcc(self):
        """Run photometric color calibration."""
        self.siril.cmd("pcc", "-limitmag=12")

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

    def _load_settings(self):
        """Load saved settings."""
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

    def _save_settings(self):
        """Save current settings."""
        self.settings.setValue("bge_method", self.bge_button_group.checkedId())
        self.settings.setValue("smoothing", self.smoothing_slider.value())
        self.settings.setValue("plate_solve", self.plate_solve_cb.isChecked())
        self.settings.setValue("pcc", self.pcc_cb.isChecked())
        self.settings.setValue("denoise_method", self.denoise_button_group.checkedId())
        self.settings.setValue("launch_hms", self.launch_hms_cb.isChecked())

    def _get_options(self):
        """Collect current options into a dictionary."""
        bge_id = self.bge_button_group.checkedId()
        bge_methods = {0: 'graxpert', 1: 'siril_rbf', 2: 'none'}

        denoise_id = self.denoise_button_group.checkedId()
        denoise_methods = {0: 'none', 1: 'silentium', 2: 'graxpert', 3: 'cosmic'}

        return {
            'bge_method': bge_methods.get(bge_id, 'graxpert'),
            'bge_smoothing': self.smoothing_slider.value() / 100.0,
            'plate_solve': self.plate_solve_cb.isChecked(),
            'pcc': self.pcc_cb.isChecked(),
            'denoise_method': denoise_methods.get(denoise_id, 'none'),
            'denoise_strength': 0.5,
            'launch_hms': self.launch_hms_cb.isChecked()
        }

    def _on_prep_clicked(self):
        """Handle Prep button click."""
        # Check if an image is loaded
        try:
            img_info = self.siril.get_image_info()
            if img_info is None:
                QMessageBox.warning(self, "No Image",
                    "Please load a Vespera TIFF image first.")
                return
        except:
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
                except Exception as e:
                    s.log(f"Could not launch HMS: {e}", LogColor.SALMON)
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
    siril = Siril()

    try:
        siril.connect()
        s.log("Vespera Quick Prep started", LogColor.GREEN)

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        window = VesperaQuickPrepWindow(siril)
        window.show()

        app.exec()

    except Exception as e:
        s.log(f"Error: {e}", LogColor.RED)
        raise
    finally:
        siril.disconnect()


if __name__ == "__main__":
    main()
