##############################################
# Vespera FTP Browser
# Browse and Preview Images on Vespera Pro
# Via FTP Connection
##############################################

# SPDX-License-Identifier: Apache-2.0
# Version 1.0.0

"""
Overview
--------
A FTP browser plugin for Vespera Pro smart telescope that allows you to:
- Browse observation sessions stored on the telescope
- Preview FITS/TIFF images with auto-stretch
- See statistics: stackable subs count, dark frame availability
- Download selected sessions to local folder for processing

The telescope exposes its storage via FTP at ftp://10.0.0.1

Directory Structure on Vespera:
- /system/ - System files (captures, dark, history, logs, plan, reports, temp)
- /user/   - User observation data
  - YYYY-MM-DD_HH-MM-SS_observation_TARGET
  - YYYY-MM-DD_HH-MM-SS_plan_NAME
    - XX-observation-target/
      - 01-images-initial/ (raw FITS subs)
      - process/ (Siril processed .fit files)
      - masters/ (stacked calibration frames)
      - reference/
      - img-XXXX-dark.fits (dark frame)

Usage
-----
1. Ensure Vespera Pro is powered on and connected to your network
2. Open this plugin from Siril's Scripts menu
3. Click "Connect" to browse telescope storage
4. Select sessions to preview or download
5. Download and set as Siril working directory

Requirements
------------
- Siril 1.3+ with sirilpy
- PyQt6
- numpy, astropy (for FITS handling)
- Network connection to Vespera Pro (default: 10.0.0.1)
"""

import sys
import os
import re
import io
import tempfile
from datetime import datetime
from ftplib import FTP
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

try:
    import sirilpy as s
    from sirilpy import LogColor
except ImportError:
    print("Error: sirilpy module not found. This script must be run within Siril.")
    sys.exit(1)

s.ensure_installed("PyQt6", "numpy", "astropy", "Pillow")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
    QGroupBox, QProgressBar, QLineEdit, QFileDialog, QMessageBox,
    QScrollArea, QGridLayout, QFrame, QCheckBox, QComboBox,
    QStatusBar, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QSize, QTimer, QPoint, QPointF
from PyQt6.QtGui import QFont, QPixmap, QImage, QPainter, QColor, QIcon, QWheelEvent, QMouseEvent, QTransform

import numpy as np
from astropy.io import fits

VERSION = "1.1.0"
DEFAULT_FTP_HOST = "10.0.0.1"
DEFAULT_FTP_PORT = 21

# Vespera Pro specifications (for reference)
VESPERA_PRO_SPECS = {
    "sensor": "Sony IMX676 Starvis 2",
    "resolution": "3536x3536 (12.5 MP)",
    "pixel_size": "2.0 µm",
    "focal_length": "200mm",  # Updated from skill - 50mm f/4 = 200mm effective
    "image_scale": "1.6 arcsec/pixel",
    "max_exposure": "10 seconds",
    "bayer_pattern": "RGGB",
}

# Thumbnail settings
THUMBNAIL_SIZE = 150
THUMBNAIL_COLUMNS = 4

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
QLabel#title { color: #88aaff; font-size: 14pt; font-weight: bold; }
QLabel#stats { color: #88ff88; }
QLabel#warning { color: #ffaa44; }
QLabel#error { color: #ff8888; }
QTreeWidget {
    background-color: #333333;
    border: 1px solid #444444;
    border-radius: 4px;
}
QTreeWidget::item { padding: 4px; }
QTreeWidget::item:selected { background-color: #285299; }
QTreeWidget::item:hover { background-color: #3a3a3a; }
QLineEdit {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 6px 8px;
    color: #e0e0e0;
}
QLineEdit:focus { border: 1px solid #88aaff; }
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
QPushButton#connect { background-color: #285299; border: 1px solid #1e3f7a; }
QPushButton#connect:hover { background-color: #355ea1; }
QPushButton#download { background-color: #2a7d2a; border: 1px solid #1e5a1e; }
QPushButton#download:hover { background-color: #359935; }
QProgressBar {
    border: 1px solid #555555;
    border-radius: 3px;
    text-align: center;
    background-color: #333333;
}
QProgressBar::chunk { background-color: #285299; }
QScrollArea { border: none; background-color: transparent; }
QFrame#preview {
    background-color: #1e1e1e;
    border: 1px solid #444444;
    border-radius: 4px;
}
QFrame#thumbnail {
    background-color: #333333;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 4px;
}
QFrame#thumbnail:hover { border-color: #88aaff; }
QStatusBar { background-color: #222222; color: #888888; }
QCheckBox { color: #cccccc; spacing: 5px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #666666;
    background: #3c3c3c;
    border-radius: 3px;
}
QCheckBox::indicator:checked {
    background-color: #285299;
    border: 1px solid #88aaff;
}
"""


@dataclass
class SessionInfo:
    """Information about an observation session."""
    path: str
    name: str
    date: Optional[datetime]
    session_type: str  # 'observation', 'plan', 'dark', 'mosaic'
    target: str
    sub_count: int = 0
    has_dark: bool = False
    has_masters: bool = False
    has_preview: bool = False  # Whether a TIFF/JPEG preview exists
    total_size_mb: float = 0.0
    observations: List[Dict] = None  # For plan sessions with multiple observations
    exposure_time: float = 10.0  # Default Vespera Pro exposure

    def __post_init__(self):
        if self.observations is None:
            self.observations = []

    @property
    def integration_time_seconds(self) -> float:
        """Calculate total integration time in seconds."""
        return self.sub_count * self.exposure_time

    @property
    def integration_time_str(self) -> str:
        """Format integration time as human-readable string."""
        total_sec = self.integration_time_seconds
        if total_sec < 60:
            return f"{total_sec:.0f}s"
        elif total_sec < 3600:
            minutes = total_sec / 60
            return f"{minutes:.1f} min"
        else:
            hours = total_sec / 3600
            minutes = (total_sec % 3600) / 60
            return f"{hours:.0f}h {minutes:.0f}m"


class FTPWorker(QThread):
    """Background thread for FTP operations."""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str, object)  # success, message, result_data
    error = pyqtSignal(str)

    def __init__(self, host: str, port: int, operation: str, **kwargs):
        super().__init__()
        self.host = host
        self.port = port
        self.operation = operation
        self.kwargs = kwargs
        self.ftp = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.ftp = FTP()
            self.progress.emit(0, f"Connecting to {self.host}...")
            self.ftp.connect(self.host, self.port, timeout=10)
            self.ftp.login()  # Anonymous login
            self.progress.emit(10, "Connected, scanning...")

            if self.operation == "list_sessions":
                result = self._list_sessions()
                self.finished.emit(True, "Sessions loaded", result)

            elif self.operation == "get_session_details":
                result = self._get_session_details(self.kwargs['path'])
                self.finished.emit(True, "Details loaded", result)

            elif self.operation == "download_preview":
                result = self._download_preview(self.kwargs['path'])
                self.finished.emit(True, "Preview loaded", result)

            elif self.operation == "download_session":
                self._download_session(
                    self.kwargs['remote_path'],
                    self.kwargs['local_path']
                )
                self.finished.emit(True, "Download complete", None)

            elif self.operation == "list_subs":
                result = self._list_subs(self.kwargs['path'])
                self.finished.emit(True, "Subs listed", result)

            elif self.operation == "get_fits_header":
                result = self._get_fits_header(self.kwargs['path'])
                self.finished.emit(True, "Header loaded", result)

            elif self.operation == "find_preview":
                result = self._find_preview(self.kwargs['path'])
                self.finished.emit(True, "Preview found", result)

            elif self.operation == "download_preview_file":
                result = self._download_preview_file(
                    self.kwargs['path'],
                    self.kwargs.get('file_type', 'tiff')
                )
                self.finished.emit(True, "Preview loaded", result)

        except Exception as e:
            self.finished.emit(False, str(e), None)
        finally:
            if self.ftp:
                try:
                    self.ftp.quit()
                except:
                    pass

    def _list_sessions(self) -> List[SessionInfo]:
        """List all observation sessions on the telescope."""
        sessions = []

        # Navigate to user directory
        try:
            self.ftp.cwd("/user")
        except:
            self.progress.emit(20, "No /user directory found")
            return sessions

        # List all directories
        items = []
        self.ftp.retrlines('LIST', items.append)

        total = len(items)
        for idx, item in enumerate(items):
            if self._cancelled:
                break

            # Parse FTP list output
            parts = item.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            name = parts[8]

            # Skip if not a directory
            if not permissions.startswith('d'):
                continue

            # Parse session info from folder name
            session = self._parse_session_name(name, f"/user/{name}")
            if session:
                sessions.append(session)

            pct = 10 + int((idx + 1) / total * 40)
            self.progress.emit(pct, f"Found {name}...")

        # Now scan each session for details (subs count, dark frames, preview)
        total_sessions = len(sessions)
        for idx, session in enumerate(sessions):
            if self._cancelled:
                break

            pct = 50 + int((idx + 1) / total_sessions * 45)
            self.progress.emit(pct, f"Scanning {session.target}...")

            # Get detailed info
            detailed = self._get_session_details(session.path)
            session.sub_count = detailed.sub_count
            session.has_dark = detailed.has_dark
            session.has_masters = detailed.has_masters
            session.observations = detailed.observations

        self.progress.emit(98, "Organizing sessions...")
        # Sort by date, newest first
        sessions.sort(key=lambda s: s.date or datetime.min, reverse=True)

        self.progress.emit(100, f"Found {len(sessions)} sessions")
        return sessions

    def _parse_session_name(self, name: str, path: str) -> Optional[SessionInfo]:
        """Parse session folder name to extract info."""
        # Pattern: YYYY-MM-DD_HH-MM-SS_type_target
        # Examples:
        #   2026-01-09_06-30-40_observation_NGC2359
        #   2026-01-07_07-29-48_plan_My_plan_1_6-1_7
        #   2026-01-03_16-32-12_dark
        # Note: type is letters only (observation, plan, dark, mosaic)
        # \w+ would incorrectly match underscores and consume the target

        pattern = r'^(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})_([a-zA-Z]+)(?:_(.+))?$'
        match = re.match(pattern, name)

        if not match:
            return None

        date_str, time_str, session_type, target = match.groups()

        try:
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            dt = None

        target = target or session_type
        target = target.replace('_', ' ')

        # Clean up common target patterns
        if session_type.lower() == 'observation':
            # NGC2359 -> NGC 2359
            target = re.sub(r'([A-Za-z]+)(\d+)', r'\1 \2', target)
            target = target.upper()

        return SessionInfo(
            path=path,
            name=name,
            date=dt,
            session_type=session_type,
            target=target
        )

    def _get_session_details(self, path: str) -> SessionInfo:
        """Get detailed info about a session (sub count, dark frame, etc.)."""
        # Parse basic info from path
        name = path.split('/')[-1]
        session = self._parse_session_name(name, path)
        if not session:
            session = SessionInfo(path=path, name=name, date=None,
                                  session_type='unknown', target=name)

        try:
            self.ftp.cwd(path)
        except:
            return session

        # Check for observation subdirectories (for plan sessions)
        items = []
        self.ftp.retrlines('LIST', items.append)

        for item in items:
            parts = item.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            name = parts[8]
            name_lower = name.lower()

            # Check for dark frame at root
            if name_lower.endswith('-dark.fits') and permissions.startswith('-'):
                session.has_dark = True
                continue

            # Check for preview files (TIFF or JPEG)
            if permissions.startswith('-'):
                if name_lower.endswith('.tif') or name_lower.endswith('.tiff') or name_lower.endswith('.jpg') or name_lower.endswith('.jpeg'):
                    session.has_preview = True
                continue

            # Check for masters directory
            if name == 'masters' and permissions.startswith('d'):
                session.has_masters = True
                continue

            # Count observation subdirectories
            if permissions.startswith('d') and 'observation' in name_lower:
                obs_info = self._scan_observation_dir(f"{path}/{name}")
                session.observations.append(obs_info)
                # Check if observation has preview
                if obs_info.get('has_preview', False):
                    session.has_preview = True

            # For direct observation sessions, check for images-initial
            if permissions.startswith('d') and 'images-initial' in name_lower:
                sub_count = self._count_fits_files(f"{path}/{name}")
                session.sub_count = sub_count

        # Sum up subs from all observations
        if session.observations:
            session.sub_count = sum(o.get('sub_count', 0) for o in session.observations)
            session.has_dark = any(o.get('has_dark', False) for o in session.observations)
            session.has_preview = session.has_preview or any(o.get('has_preview', False) for o in session.observations)

        return session

    def _scan_observation_dir(self, path: str) -> Dict:
        """Scan an observation subdirectory."""
        obs_info = {
            'path': path,
            'name': path.split('/')[-1],
            'sub_count': 0,
            'has_dark': False,
            'has_preview': False
        }

        try:
            self.ftp.cwd(path)
        except:
            return obs_info

        items = []
        self.ftp.retrlines('LIST', items.append)

        for item in items:
            parts = item.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            name = parts[8]
            name_lower = name.lower()

            if name_lower.endswith('-dark.fits') and permissions.startswith('-'):
                obs_info['has_dark'] = True

            # Check for preview files
            if permissions.startswith('-'):
                if name_lower.endswith('.tif') or name_lower.endswith('.tiff') or name_lower.endswith('.jpg') or name_lower.endswith('.jpeg'):
                    obs_info['has_preview'] = True

            if 'images-initial' in name_lower and permissions.startswith('d'):
                obs_info['sub_count'] = self._count_fits_files(f"{path}/{name}")

        return obs_info

    def _count_fits_files(self, path: str) -> int:
        """Count FITS files in a directory."""
        try:
            self.ftp.cwd(path)
        except:
            return 0

        count = 0
        items = []
        self.ftp.retrlines('NLST', items.append)

        for item in items:
            if item.endswith('.fits') or item.endswith('.fit'):
                # Exclude dark frames from count
                if 'dark' not in item.lower():
                    count += 1

        return count

    def _download_preview(self, path: str) -> Optional[np.ndarray]:
        """Download a FITS file and return the image data."""
        try:
            data = io.BytesIO()
            self.ftp.retrbinary(f'RETR {path}', data.write)
            data.seek(0)

            with fits.open(data) as hdul:
                img_data = hdul[0].data
                return img_data

        except Exception as e:
            print(f"Preview error: {e}")
            return None

    def _list_subs(self, path: str) -> List[Dict]:
        """List all FITS sub files in a directory with their info."""
        subs = []

        # Find the images-initial folder
        images_path = None

        try:
            self.ftp.cwd(path)
        except:
            return subs

        items = []
        self.ftp.retrlines('LIST', items.append)

        # Look for images-initial or similar folder
        for item in items:
            parts = item.split(None, 8)
            if len(parts) < 9:
                continue
            permissions = parts[0]
            name = parts[8]

            if permissions.startswith('d') and 'images-initial' in name.lower():
                images_path = f"{path}/{name}"
                break

            # Also check for observation subdirectories
            if permissions.startswith('d') and 'observation' in name.lower():
                # Recursively look in observation folders
                sub_items = []
                try:
                    self.ftp.cwd(f"{path}/{name}")
                    self.ftp.retrlines('LIST', sub_items.append)
                    for sub_item in sub_items:
                        sub_parts = sub_item.split(None, 8)
                        if len(sub_parts) >= 9:
                            sub_name = sub_parts[8]
                            if 'images-initial' in sub_name.lower():
                                images_path = f"{path}/{name}/{sub_name}"
                                break
                except:
                    pass
                if images_path:
                    break

        if not images_path:
            return subs

        # List FITS files in images folder
        try:
            self.ftp.cwd(images_path)
        except:
            return subs

        file_items = []
        self.ftp.retrlines('LIST', file_items.append)

        for idx, item in enumerate(file_items):
            if self._cancelled:
                break

            parts = item.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            size = int(parts[4]) if parts[4].isdigit() else 0
            name = parts[8]

            if permissions.startswith('-') and (name.endswith('.fits') or name.endswith('.fit')):
                is_dark = 'dark' in name.lower()

                subs.append({
                    'name': name,
                    'path': f"{images_path}/{name}",
                    'size': size,
                    'size_mb': size / (1024 * 1024),
                    'is_dark': is_dark,
                    'index': idx
                })

            if idx % 50 == 0:
                self.progress.emit(20 + int(idx / len(file_items) * 70),
                                  f"Scanning {name}...")

        # Sort by name (which typically includes sequence number)
        subs.sort(key=lambda x: x['name'])

        self.progress.emit(95, f"Found {len(subs)} subs")
        return subs

    def _get_fits_header(self, path: str) -> Optional[Dict]:
        """Download just the FITS header without the full image."""
        try:
            # Download first 64KB which should contain the header
            data = io.BytesIO()
            bytes_received = [0]

            def callback(chunk):
                if bytes_received[0] < 65536:  # 64KB
                    data.write(chunk)
                    bytes_received[0] += len(chunk)

            self.ftp.retrbinary(f'RETR {path}', callback)
            data.seek(0)

            # Try to parse the header
            with fits.open(data, ignore_missing_simple=True) as hdul:
                header = dict(hdul[0].header)
                return {
                    'exptime': header.get('EXPTIME', 10.0),
                    'gain': header.get('GAIN', 20),
                    'date_obs': header.get('DATE-OBS', ''),
                    'instrume': header.get('INSTRUME', 'Unknown'),
                    'filter': header.get('FILTER', 'None'),
                    'bayerpat': header.get('BAYERPAT', 'RGGB'),
                    'naxis1': header.get('NAXIS1', 0),
                    'naxis2': header.get('NAXIS2', 0),
                }

        except Exception as e:
            print(f"Header error: {e}")
            return None

    def _find_preview(self, path: str) -> Optional[Dict]:
        """Find a preview TIFF or stacked image in the session folder.

        Vespera stores the stacked TIFF in:
        - 01-images-initial/ folder (alongside FITS subs)
        - reference/ folder
        - Or in observation subfolders for plan sessions
        """
        tiff_file = None
        fits_file = None

        try:
            self.ftp.cwd(path)
        except:
            return None

        # List files/folders in the session root
        items = []
        self.ftp.retrlines('LIST', items.append)

        # Folders to search for TIFF (in priority order)
        search_folders = ['01-images-initial', 'reference']

        # First check session root for any TIFF
        for item in items:
            parts = item.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            name = parts[8]

            if permissions.startswith('-'):
                name_lower = name.lower()
                if name_lower.endswith('.tif') or name_lower.endswith('.tiff'):
                    tiff_file = f"{path}/{name}"
                    break

        # Search in known folders
        if not tiff_file:
            for item in items:
                parts = item.split(None, 8)
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                name = parts[8]

                if permissions.startswith('d'):
                    # Check if this is one of our target folders
                    name_lower = name.lower()
                    is_target = any(sf in name_lower for sf in search_folders)

                    if is_target:
                        tiff_file = self._search_folder_for_tiff(f"{path}/{name}")
                        if tiff_file:
                            break

        # Check observation subdirectories for plan sessions
        if not tiff_file:
            for item in items:
                parts = item.split(None, 8)
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                name = parts[8]

                if permissions.startswith('d') and 'observation' in name.lower():
                    # Check inside this observation folder
                    obs_path = f"{path}/{name}"
                    try:
                        self.ftp.cwd(obs_path)
                        obs_items = []
                        self.ftp.retrlines('LIST', obs_items.append)

                        # Check observation root
                        for obs_item in obs_items:
                            obs_parts = obs_item.split(None, 8)
                            if len(obs_parts) < 9:
                                continue
                            obs_perm = obs_parts[0]
                            obs_name = obs_parts[8]

                            if obs_perm.startswith('-'):
                                obs_lower = obs_name.lower()
                                if obs_lower.endswith('.tif') or obs_lower.endswith('.tiff'):
                                    tiff_file = f"{obs_path}/{obs_name}"
                                    break

                        # Check subfolders in observation
                        if not tiff_file:
                            for obs_item in obs_items:
                                obs_parts = obs_item.split(None, 8)
                                if len(obs_parts) < 9:
                                    continue
                                obs_perm = obs_parts[0]
                                obs_name = obs_parts[8]

                                if obs_perm.startswith('d'):
                                    obs_lower = obs_name.lower()
                                    is_target = any(sf in obs_lower for sf in search_folders)
                                    if is_target:
                                        tiff_file = self._search_folder_for_tiff(f"{obs_path}/{obs_name}")
                                        if tiff_file:
                                            break
                    except:
                        pass

                    if tiff_file:
                        break

        # Return the best preview file found
        if tiff_file:
            return {'path': tiff_file, 'type': 'tiff'}
        else:
            return None

    def _search_folder_for_tiff(self, folder_path: str) -> Optional[str]:
        """Search a specific folder for TIFF files."""
        try:
            self.ftp.cwd(folder_path)
            items = []
            self.ftp.retrlines('LIST', items.append)

            for item in items:
                parts = item.split(None, 8)
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                name = parts[8]

                if permissions.startswith('-'):
                    name_lower = name.lower()
                    if name_lower.endswith('.tif') or name_lower.endswith('.tiff'):
                        return f"{folder_path}/{name}"

        except:
            pass

        return None

    def _download_preview_file(self, path: str, file_type: str = 'tiff') -> Optional[np.ndarray]:
        """Download and parse a preview file (TIFF or FITS)."""
        try:
            self.progress.emit(10, "Downloading preview file...")

            data = io.BytesIO()
            self.ftp.retrbinary(f'RETR {path}', data.write)
            data.seek(0)

            self.progress.emit(80, "Processing preview...")

            if file_type == 'tiff':
                # Use PIL/Pillow for TIFF
                from PIL import Image
                img = Image.open(data)
                img_array = np.array(img)

                # Handle different bit depths
                if img_array.dtype == np.uint16:
                    # 16-bit TIFF - normalize to float
                    img_array = img_array.astype(np.float32) / 65535.0
                elif img_array.dtype == np.uint8:
                    img_array = img_array.astype(np.float32) / 255.0
                else:
                    img_array = img_array.astype(np.float32)

                # If RGB, transpose to (channels, height, width) for consistency
                if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                    img_array = np.transpose(img_array, (2, 0, 1))

                self.progress.emit(100, "Preview ready")
                return img_array

            else:
                # FITS file
                with fits.open(data) as hdul:
                    img_data = hdul[0].data
                    self.progress.emit(100, "Preview ready")
                    return img_data

        except Exception as e:
            print(f"Preview download error: {e}")
            return None

    def _download_session(self, remote_path: str, local_path: str):
        """Download an entire session directory."""
        os.makedirs(local_path, exist_ok=True)

        try:
            self.ftp.cwd(remote_path)
        except:
            return

        self._download_directory_recursive(remote_path, local_path)

    def _download_directory_recursive(self, remote_path: str, local_path: str,
                                       total_files: int = 0, downloaded: int = 0):
        """Recursively download a directory."""
        if self._cancelled:
            return downloaded

        try:
            self.ftp.cwd(remote_path)
        except:
            return downloaded

        items = []
        self.ftp.retrlines('LIST', items.append)

        for item in items:
            if self._cancelled:
                break

            parts = item.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            size = int(parts[4]) if parts[4].isdigit() else 0
            name = parts[8]

            remote_item = f"{remote_path}/{name}"
            local_item = os.path.join(local_path, name)

            if permissions.startswith('d'):
                # Directory - recurse
                os.makedirs(local_item, exist_ok=True)
                downloaded = self._download_directory_recursive(
                    remote_item, local_item, total_files, downloaded
                )
                # Return to parent directory
                self.ftp.cwd(remote_path)
            else:
                # File - download
                self.progress.emit(
                    min(95, int(downloaded / max(total_files, 1) * 90)),
                    f"Downloading {name}..."
                )

                with open(local_item, 'wb') as f:
                    self.ftp.retrbinary(f'RETR {name}', f.write)

                downloaded += 1

        return downloaded


def auto_stretch(data: np.ndarray, shadows_clip: float = -2.8,
                 target_background: float = 0.25) -> np.ndarray:
    """
    Apply Screen Transfer Function (STF) auto-stretch to image data.

    This mimics the auto-stretch used in astrophotography software to make
    faint details visible in linear FITS images.
    """
    if data is None:
        return None

    # Handle 3D (color) or 2D (mono) data
    if len(data.shape) == 3:
        # Color image - process each channel
        stretched = np.zeros_like(data, dtype=np.float32)
        for i in range(data.shape[0]):
            stretched[i] = auto_stretch(data[i], shadows_clip, target_background)
        return stretched

    # Convert to float and normalize
    data = data.astype(np.float32)

    # Get statistics (use center region to avoid edge effects)
    h, w = data.shape
    margin = min(h, w) // 10
    center = data[margin:h-margin, margin:w-margin]

    median_val = np.median(center)
    mad = np.median(np.abs(center - median_val))
    std_est = mad * 1.4826  # Convert MAD to standard deviation estimate

    # Calculate shadows clip point
    shadows = median_val + shadows_clip * std_est
    shadows = max(shadows, np.min(data))

    # Calculate midtones transfer function
    # This is the key to the STF stretch
    data_min = shadows
    data_max = np.percentile(data, 99.9)

    if data_max <= data_min:
        return np.zeros_like(data)

    # Normalize to 0-1
    normalized = (data - data_min) / (data_max - data_min)
    normalized = np.clip(normalized, 0, 1)

    # Apply midtones transfer function (MTF)
    # The MTF is: MTF(x, m) = (m - 1) * x / ((2m - 1) * x - m)
    # where m is the midtones balance (0.5 = neutral)

    # Calculate midtones balance to achieve target background
    # We want the median to map to target_background
    norm_median = (median_val - data_min) / (data_max - data_min)
    norm_median = np.clip(norm_median, 0.0001, 0.9999)

    # Solve for m: target = MTF(norm_median, m)
    # This gives us the midtones balance
    m = (target_background * (norm_median - 1)) / \
        (norm_median * (target_background - 1) + target_background - 1)
    m = np.clip(m, 0.0001, 0.9999)

    # Apply MTF
    with np.errstate(divide='ignore', invalid='ignore'):
        stretched = (m - 1) * normalized / ((2 * m - 1) * normalized - m)
        stretched = np.nan_to_num(stretched, nan=0.0, posinf=1.0, neginf=0.0)

    stretched = np.clip(stretched, 0, 1)
    return stretched


def fits_to_qpixmap(data: np.ndarray, size: QSize = None) -> QPixmap:
    """Convert FITS image data to QPixmap for display."""
    if data is None:
        return QPixmap()

    # Auto-stretch the data
    stretched = auto_stretch(data)

    # Convert to 8-bit
    img_8bit = (stretched * 255).astype(np.uint8)

    # Handle color vs mono
    if len(img_8bit.shape) == 3:
        # Color image (channels, height, width) -> (height, width, channels)
        if img_8bit.shape[0] == 3:
            img_8bit = np.transpose(img_8bit, (1, 2, 0))
            h, w, c = img_8bit.shape
            bytes_per_line = 3 * w
            qimg = QImage(img_8bit.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
        else:
            # Take first channel
            img_8bit = img_8bit[0]
            h, w = img_8bit.shape
            qimg = QImage(img_8bit.tobytes(), w, h, w, QImage.Format.Format_Grayscale8)
    else:
        # Mono image
        h, w = img_8bit.shape
        qimg = QImage(img_8bit.tobytes(), w, h, w, QImage.Format.Format_Grayscale8)

    pixmap = QPixmap.fromImage(qimg)

    # Scale if size specified
    if size:
        pixmap = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)

    return pixmap


class ThumbnailWidget(QFrame):
    """Widget for displaying a thumbnail with info."""
    clicked = pyqtSignal(str)  # Emits the file path

    def __init__(self, path: str, pixmap: QPixmap, info: str):
        super().__init__()
        self.path = path
        self.setObjectName("thumbnail")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Image label
        self.img_label = QLabel()
        self.img_label.setPixmap(pixmap)
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.img_label)

        # Info label
        self.info_label = QLabel(info)
        self.info_label.setStyleSheet("color: #888888; font-size: 8pt;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)


class ZoomablePreviewWidget(QWidget):
    """Widget that displays an image with zoom and pan support.

    - Mouse wheel: Zoom in/out (centered on cursor)
    - Click and drag: Pan the image
    - Double-click: Reset to fit view
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: Optional[QPixmap] = None
        self.full_pixmap: Optional[QPixmap] = None  # Full resolution pixmap
        self.zoom_level: float = 1.0
        self.min_zoom: float = 0.1
        self.max_zoom: float = 10.0
        self.pan_offset: QPointF = QPointF(0, 0)
        self.last_mouse_pos: Optional[QPoint] = None
        self.is_panning: bool = False
        self.placeholder_text: str = "Select a session to preview"

        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def setPixmap(self, pixmap: QPixmap):
        """Set the image to display (full resolution)."""
        self.full_pixmap = pixmap
        self.pixmap = pixmap
        self._fit_to_view()
        self.update()

    def setPlaceholderText(self, text: str):
        """Set placeholder text shown when no image is loaded."""
        self.placeholder_text = text
        self.update()

    def clear(self):
        """Clear the displayed image."""
        self.pixmap = None
        self.full_pixmap = None
        self.zoom_level = 1.0
        self.pan_offset = QPointF(0, 0)
        self.update()

    def _fit_to_view(self):
        """Reset zoom to fit the image in the view."""
        if not self.full_pixmap or self.full_pixmap.isNull():
            return

        # Calculate zoom level to fit the image
        widget_size = self.size()
        img_size = self.full_pixmap.size()

        zoom_x = widget_size.width() / img_size.width()
        zoom_y = widget_size.height() / img_size.height()

        self.zoom_level = min(zoom_x, zoom_y, 1.0)  # Don't zoom in beyond 100%
        self.pan_offset = QPointF(0, 0)
        self.update()

    def _zoom_at_point(self, zoom_factor: float, center: QPoint):
        """Zoom centered on a specific point."""
        if not self.full_pixmap:
            return

        old_zoom = self.zoom_level
        new_zoom = self.zoom_level * zoom_factor
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        if new_zoom == old_zoom:
            return

        # Calculate the point in image coordinates before zoom
        widget_center = QPointF(self.width() / 2, self.height() / 2)
        mouse_offset = QPointF(center) - widget_center

        # Adjust pan to keep the point under the cursor stationary
        scale_change = new_zoom / old_zoom
        self.pan_offset = self.pan_offset * scale_change + mouse_offset * (1 - scale_change)

        self.zoom_level = new_zoom
        self.update()

    def paintEvent(self, event):
        """Draw the image with current zoom and pan."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Fill background
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        if not self.full_pixmap or self.full_pixmap.isNull():
            # Draw placeholder text
            painter.setPen(QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder_text)
            return

        # Calculate scaled image size
        img_size = self.full_pixmap.size()
        scaled_width = int(img_size.width() * self.zoom_level)
        scaled_height = int(img_size.height() * self.zoom_level)

        # Calculate position (centered with pan offset)
        x = int((self.width() - scaled_width) / 2 + self.pan_offset.x())
        y = int((self.height() - scaled_height) / 2 + self.pan_offset.y())

        # Draw the scaled image
        target_rect = QPixmap(scaled_width, scaled_height)
        scaled = self.full_pixmap.scaled(
            scaled_width, scaled_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        painter.drawPixmap(x, y, scaled)

        # Draw zoom indicator
        zoom_text = f"{self.zoom_level * 100:.0f}%"
        painter.setPen(QColor("#888888"))
        painter.drawText(10, self.height() - 10, zoom_text)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming."""
        if not self.full_pixmap:
            return

        # Zoom factor per wheel step
        delta = event.angleDelta().y()
        if delta > 0:
            zoom_factor = 1.15
        elif delta < 0:
            zoom_factor = 1 / 1.15
        else:
            return

        self._zoom_at_point(zoom_factor, event.position().toPoint())

    def mousePressEvent(self, event: QMouseEvent):
        """Start panning on mouse press."""
        if event.button() == Qt.MouseButton.LeftButton and self.full_pixmap:
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Stop panning on mouse release."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            self.last_mouse_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Pan the image while dragging."""
        if self.is_panning and self.last_mouse_pos and self.full_pixmap:
            delta = event.pos() - self.last_mouse_pos
            self.pan_offset += QPointF(delta)
            self.last_mouse_pos = event.pos()
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Reset view on double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.fit_to_view()

    def resizeEvent(self, event):
        """Handle widget resize."""
        super().resizeEvent(event)
        # Optionally re-fit the image when resizing
        # self.fit_to_view()

    # Public zoom control methods (for toolbar buttons)
    def fit_to_view(self):
        """Public method: Reset zoom to fit the image in the view."""
        self._fit_to_view()

    def zoom_1_1(self):
        """Set zoom to 100% (1:1 pixel view)."""
        if not self.full_pixmap or self.full_pixmap.isNull():
            return
        self.zoom_level = 1.0
        self.pan_offset = QPointF(0, 0)
        self.update()

    def zoom_in(self):
        """Zoom in by 20%."""
        if not self.full_pixmap:
            return
        center = QPoint(self.width() // 2, self.height() // 2)
        self._zoom_at_point(1.2, center)

    def zoom_out(self):
        """Zoom out by 20%."""
        if not self.full_pixmap:
            return
        center = QPoint(self.width() // 2, self.height() // 2)
        self._zoom_at_point(1 / 1.2, center)


class VesperaFTPBrowserWindow(QMainWindow):
    """Main window for Vespera FTP Browser plugin."""

    def __init__(self, siril):
        super().__init__()
        self.siril = siril
        self.settings = QSettings("VesperaSiril", "FTPBrowser")
        self.sessions: List[SessionInfo] = []
        self.current_session: Optional[SessionInfo] = None
        self.worker: Optional[FTPWorker] = None
        self.preview_worker: Optional[FTPWorker] = None
        self.browse_mode: str = "ftp"  # "ftp" or "local"
        self.local_root_path: Optional[str] = None
        # Preview navigation for sessions with multiple TIFFs
        self.preview_paths: List[str] = []
        self.preview_index: int = 0

        self.setWindowTitle(f"Vespera Browser v{VERSION}")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(DARK_STYLESHEET)

        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        """Build the user interface."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel("Vespera Browser")
        title.setObjectName("title")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Mode selector
        mode_label = QLabel("Source:")
        header_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["FTP (Telescope)", "Local Folder"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.setFixedWidth(130)
        header_layout.addWidget(self.mode_combo)

        # FTP controls
        self.ftp_controls = QWidget()
        ftp_layout = QHBoxLayout(self.ftp_controls)
        ftp_layout.setContentsMargins(0, 0, 0, 0)

        conn_label = QLabel("Host:")
        ftp_layout.addWidget(conn_label)

        self.host_input = QLineEdit(DEFAULT_FTP_HOST)
        self.host_input.setFixedWidth(120)
        ftp_layout.addWidget(self.host_input)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("connect")
        self.connect_btn.clicked.connect(self._on_connect)
        ftp_layout.addWidget(self.connect_btn)

        header_layout.addWidget(self.ftp_controls)

        # Local folder controls
        self.local_controls = QWidget()
        local_layout = QHBoxLayout(self.local_controls)
        local_layout.setContentsMargins(0, 0, 0, 0)

        self.local_path_label = QLabel("No folder selected")
        self.local_path_label.setStyleSheet("color: #888888;")
        self.local_path_label.setMaximumWidth(200)
        local_layout.addWidget(self.local_path_label)

        self.browse_local_btn = QPushButton("Browse...")
        self.browse_local_btn.clicked.connect(self._on_browse_local)
        local_layout.addWidget(self.browse_local_btn)

        self.local_controls.setVisible(False)
        header_layout.addWidget(self.local_controls)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._on_refresh)
        header_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(header_layout)

        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Session tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        sessions_group = QGroupBox("Sessions")
        sessions_layout = QVBoxLayout(sessions_group)

        self.sessions_tree = QTreeWidget()
        self.sessions_tree.setHeaderLabels(["Session", "Subs", "Dark", "Prev"])
        self.sessions_tree.setColumnWidth(0, 220)
        self.sessions_tree.setColumnWidth(1, 50)
        self.sessions_tree.setColumnWidth(2, 40)
        self.sessions_tree.setColumnWidth(3, 40)
        self.sessions_tree.itemClicked.connect(self._on_session_clicked)
        self.sessions_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sessions_tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        sessions_layout.addWidget(self.sessions_tree)

        left_layout.addWidget(sessions_group)
        left_panel.setMinimumWidth(350)

        splitter.addWidget(left_panel)

        # Right panel - Preview and details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Details group
        details_group = QGroupBox("Session Details")
        details_layout = QVBoxLayout(details_group)

        self.detail_labels = {}
        for key in ["Name", "Date", "Target", "Type", "Subs", "Integration", "Dark", "Masters"]:
            row = QHBoxLayout()
            label = QLabel(f"{key}:")
            label.setFixedWidth(60)
            label.setStyleSheet("color: #888888;")
            row.addWidget(label)

            value = QLabel("-")
            value.setObjectName("stats" if key in ["Subs", "Dark"] else "")
            self.detail_labels[key] = value
            row.addWidget(value)
            row.addStretch()

            details_layout.addLayout(row)

        right_layout.addWidget(details_group)

        # Preview area with zoom/pan support
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)

        # Create preview widget first so buttons can connect to it
        self.preview_widget = ZoomablePreviewWidget()
        self.preview_widget.setMinimumHeight(400)

        # Zoom toolbar
        zoom_toolbar = QHBoxLayout()
        zoom_toolbar.setSpacing(5)

        # Style for zoom buttons - larger font for visibility
        zoom_btn_style = "font-size: 14pt; font-weight: bold; padding: 2px;"

        btn_zoom_out = QPushButton("\u2212")  # Unicode minus sign
        btn_zoom_out.setFixedSize(32, 28)
        btn_zoom_out.setStyleSheet(zoom_btn_style)
        btn_zoom_out.setToolTip("Zoom Out")
        btn_zoom_out.clicked.connect(self.preview_widget.zoom_out)
        zoom_toolbar.addWidget(btn_zoom_out)

        btn_fit = QPushButton("Fit")
        btn_fit.setFixedSize(40, 28)
        btn_fit.setToolTip("Fit to Window (double-click also resets)")
        btn_fit.clicked.connect(self.preview_widget.fit_to_view)
        zoom_toolbar.addWidget(btn_fit)

        btn_1_1 = QPushButton("1:1")
        btn_1_1.setFixedSize(40, 28)
        btn_1_1.setToolTip("100% Zoom (1:1 pixel)")
        btn_1_1.clicked.connect(self.preview_widget.zoom_1_1)
        zoom_toolbar.addWidget(btn_1_1)

        btn_zoom_in = QPushButton("\u002B")  # Unicode plus sign
        btn_zoom_in.setFixedSize(32, 28)
        btn_zoom_in.setStyleSheet(zoom_btn_style)
        btn_zoom_in.setToolTip("Zoom In")
        btn_zoom_in.clicked.connect(self.preview_widget.zoom_in)
        zoom_toolbar.addWidget(btn_zoom_in)

        zoom_toolbar.addStretch()

        # Preview navigation for sessions with multiple observations
        nav_btn_style = "font-size: 12pt; font-weight: bold;"

        self.btn_prev_preview = QPushButton("\u25C0")  # Unicode left triangle
        self.btn_prev_preview.setFixedSize(32, 28)
        self.btn_prev_preview.setStyleSheet(nav_btn_style)
        self.btn_prev_preview.setToolTip("Previous observation")
        self.btn_prev_preview.clicked.connect(self._prev_preview)
        self.btn_prev_preview.setVisible(False)
        zoom_toolbar.addWidget(self.btn_prev_preview)

        self.lbl_preview_nav = QLabel("1 / 1")
        self.lbl_preview_nav.setStyleSheet("color: #88aaff; font-size: 10pt; min-width: 60px;")
        self.lbl_preview_nav.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview_nav.setVisible(False)
        zoom_toolbar.addWidget(self.lbl_preview_nav)

        self.btn_next_preview = QPushButton("\u25B6")  # Unicode right triangle
        self.btn_next_preview.setFixedSize(32, 28)
        self.btn_next_preview.setStyleSheet(nav_btn_style)
        self.btn_next_preview.setToolTip("Next observation")
        self.btn_next_preview.clicked.connect(self._next_preview)
        self.btn_next_preview.setVisible(False)
        zoom_toolbar.addWidget(self.btn_next_preview)

        zoom_toolbar.addSpacing(10)

        self.lbl_zoom_hint = QLabel("Scroll to zoom, drag to pan")
        self.lbl_zoom_hint.setStyleSheet("color: #888888; font-size: 9pt;")
        zoom_toolbar.addWidget(self.lbl_zoom_hint)

        preview_layout.addLayout(zoom_toolbar)
        preview_layout.addWidget(self.preview_widget)

        right_layout.addWidget(preview_group, 1)

        # Download controls
        download_group = QGroupBox("Download")
        download_layout = QVBoxLayout(download_group)

        path_row = QHBoxLayout()
        self.save_to_label = QLabel("Save to:")
        path_row.addWidget(self.save_to_label)

        self.download_path = QLineEdit()
        self.download_path.setPlaceholderText("Select download location...")
        path_row.addWidget(self.download_path, 1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse_download)
        path_row.addWidget(self.browse_btn)

        download_layout.addLayout(path_row)

        options_row = QHBoxLayout()
        self.set_workdir_cb = QCheckBox("Set as Siril working directory after download")
        self.set_workdir_cb.setChecked(True)
        options_row.addWidget(self.set_workdir_cb)
        options_row.addStretch()
        download_layout.addLayout(options_row)

        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("Download Session")
        self.download_btn.setObjectName("download")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download)
        btn_row.addWidget(self.download_btn)
        btn_row.addStretch()
        download_layout.addLayout(btn_row)

        right_layout.addWidget(download_group)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Not connected")

    def _load_settings(self):
        """Load saved settings."""
        host = self.settings.value("host", DEFAULT_FTP_HOST, type=str)
        self.host_input.setText(host)

        download_path = self.settings.value("download_path", "", type=str)
        self.download_path.setText(download_path)

        set_workdir = self.settings.value("set_workdir", True, type=bool)
        self.set_workdir_cb.setChecked(set_workdir)

        # Load saved local path
        local_path = self.settings.value("local_path", "", type=str)
        if local_path and os.path.isdir(local_path):
            self.local_root_path = local_path
            display_path = local_path
            if len(display_path) > 30:
                display_path = "..." + display_path[-27:]
            self.local_path_label.setText(display_path)
            self.local_path_label.setToolTip(local_path)

    def _save_settings(self):
        """Save current settings."""
        self.settings.setValue("host", self.host_input.text())
        self.settings.setValue("download_path", self.download_path.text())
        self.settings.setValue("set_workdir", self.set_workdir_cb.isChecked())
        if self.local_root_path:
            self.settings.setValue("local_path", self.local_root_path)

    def _on_mode_changed(self, index: int):
        """Handle mode selector change."""
        if index == 0:  # FTP mode
            self.browse_mode = "ftp"
            self.ftp_controls.setVisible(True)
            self.local_controls.setVisible(False)
            self.download_btn.setText("Download Session")
            self.download_btn.setVisible(True)
            # Show download path controls for FTP mode
            self.save_to_label.setVisible(True)
            self.download_path.setVisible(True)
            self.browse_btn.setVisible(True)
            self.set_workdir_cb.setVisible(True)
        else:  # Local mode
            self.browse_mode = "local"
            self.ftp_controls.setVisible(False)
            self.local_controls.setVisible(True)
            self.download_btn.setText("Open in Siril")
            self.download_btn.setVisible(True)
            # Hide download path controls for local mode (not needed)
            self.save_to_label.setVisible(False)
            self.download_path.setVisible(False)
            self.browse_btn.setVisible(False)
            self.set_workdir_cb.setVisible(False)

        # Clear current sessions
        self.sessions = []
        self.sessions_tree.clear()
        self.current_session = None
        self.preview_widget.setPlaceholderText("Select a session to preview")
        self.preview_widget.clear()
        self.refresh_btn.setEnabled(False)

    def _on_browse_local(self):
        """Browse for a local folder containing Vespera sessions."""
        start_path = self.local_root_path or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder with Vespera Sessions",
            start_path
        )
        if folder:
            self.local_root_path = folder
            # Truncate path for display
            display_path = folder
            if len(display_path) > 30:
                display_path = "..." + display_path[-27:]
            self.local_path_label.setText(display_path)
            self.local_path_label.setToolTip(folder)
            self._save_settings()
            self._scan_local_folder()

    def _scan_local_folder(self):
        """Scan local folder for Vespera session folders."""
        if not self.local_root_path or not os.path.isdir(self.local_root_path):
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_bar.showMessage("Scanning local folder...")

        self.sessions = []

        try:
            # First, check if the browsed folder itself IS a session folder
            root_name = os.path.basename(self.local_root_path)
            root_session = self._parse_local_session(root_name, self.local_root_path)
            if root_session:
                self.sessions.append(root_session)

            # Scan direct children
            entries = os.listdir(self.local_root_path)
            total = len(entries)

            for idx, entry in enumerate(entries):
                entry_path = os.path.join(self.local_root_path, entry)
                if os.path.isdir(entry_path):
                    session = self._parse_local_session(entry, entry_path)
                    if session:
                        self.sessions.append(session)
                    else:
                        # Look one level deeper for sessions (handles 'user/' subfolder)
                        try:
                            for subentry in os.listdir(entry_path):
                                subentry_path = os.path.join(entry_path, subentry)
                                if os.path.isdir(subentry_path):
                                    sub_session = self._parse_local_session(subentry, subentry_path)
                                    if sub_session:
                                        self.sessions.append(sub_session)
                        except PermissionError:
                            pass

                pct = int((idx + 1) / total * 100) if total > 0 else 100
                self.progress_bar.setValue(pct)

        except Exception as e:
            self.status_bar.showMessage(f"Error scanning: {e}")

        self.progress_bar.setVisible(False)

        # Remove duplicates (in case root was also found as child)
        seen_paths = set()
        unique_sessions = []
        for s in self.sessions:
            if s.path not in seen_paths:
                seen_paths.add(s.path)
                unique_sessions.append(s)
        self.sessions = unique_sessions

        # Sort by date, newest first
        self.sessions.sort(key=lambda s: s.date or datetime.min, reverse=True)

        self._populate_sessions_tree()
        self.refresh_btn.setEnabled(True)
        self.status_bar.showMessage(f"Found {len(self.sessions)} sessions")

    def _parse_local_session(self, name: str, path: str) -> Optional[SessionInfo]:
        """Parse a local session folder."""
        # Pattern: YYYY-MM-DD_HH-MM-SS_type_target
        # Note: type is letters only (observation, plan, dark, mosaic)
        pattern = r'^(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})_([a-zA-Z]+)(?:_(.+))?$'
        match = re.match(pattern, name)

        if not match:
            return None

        date_str, time_str, session_type, target = match.groups()

        try:
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            dt = None

        target = target or session_type
        target = target.replace('_', ' ')

        if session_type.lower() == 'observation':
            target = re.sub(r'([A-Za-z]+)(\d+)', r'\1 \2', target)
            target = target.upper()

        session = SessionInfo(
            path=path,
            name=name,
            date=dt,
            session_type=session_type,
            target=target
        )

        # Scan for details
        self._scan_local_session_details(session)

        return session

    def _scan_local_session_details(self, session: SessionInfo):
        """Scan a local session folder for details."""
        path = session.path
        images_paths = []

        try:
            root_files = os.listdir(path)
        except PermissionError:
            return

        # Check for dark frame and preview at root
        for f in root_files:
            f_lower = f.lower()
            if f_lower.endswith('-dark.fits') or f_lower.endswith('-dark.fit'):
                session.has_dark = True
            # Check for preview files (TIFF or JPEG)
            if f_lower.endswith('.tif') or f_lower.endswith('.tiff') or f_lower.endswith('.jpg') or f_lower.endswith('.jpeg'):
                session.has_preview = True

        # Check for masters folder
        masters_path = os.path.join(path, 'masters')
        if os.path.isdir(masters_path):
            session.has_masters = True

        # Scan for FITS subs and previews in subfolders
        for folder_name in root_files:
            folder_path = os.path.join(path, folder_name)
            if not os.path.isdir(folder_path):
                continue

            folder_lower = folder_name.lower()

            # Direct images-initial folder
            if 'images-initial' in folder_lower:
                images_paths.append(folder_path)
                continue

            # Check observation subfolders (for plan sessions)
            if 'observation' in folder_lower:
                try:
                    for sub_name in os.listdir(folder_path):
                        sub_path = os.path.join(folder_path, sub_name)
                        sub_lower = sub_name.lower()

                        if os.path.isdir(sub_path) and 'images-initial' in sub_lower:
                            images_paths.append(sub_path)

                        # Check for dark in observation folder
                        if sub_lower.endswith('-dark.fits') or sub_lower.endswith('-dark.fit'):
                            session.has_dark = True

                        # Check for preview files in observation folder
                        if sub_lower.endswith('.tif') or sub_lower.endswith('.tiff') or sub_lower.endswith('.jpg') or sub_lower.endswith('.jpeg'):
                            session.has_preview = True
                except PermissionError:
                    pass

        # Count FITS subs from all images-initial folders
        for images_path in images_paths:
            try:
                for f in os.listdir(images_path):
                    if (f.lower().endswith('.fits') or f.lower().endswith('.fit')) and 'dark' not in f.lower():
                        session.sub_count += 1
            except PermissionError:
                pass

    def _on_connect(self):
        """Handle connect button click."""
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Error", "Please enter a host address.")
            return

        self._save_settings()
        self.connect_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_bar.showMessage(f"Connecting to {host}...")

        self.worker = FTPWorker(host, DEFAULT_FTP_PORT, "list_sessions")
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_sessions_loaded)
        self.worker.start()

    def _on_refresh(self):
        """Refresh the session list."""
        if self.browse_mode == "local":
            self._scan_local_folder()
        else:
            self._on_connect()

    def _on_progress(self, percent: int, message: str):
        """Handle progress updates."""
        self.progress_bar.setValue(percent)
        self.status_bar.showMessage(message)

    def _on_sessions_loaded(self, success: bool, message: str, data):
        """Handle session list loaded."""
        self.connect_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        if not success:
            self.status_bar.showMessage(f"Connection failed: {message}")
            QMessageBox.critical(self, "Connection Error",
                                f"Failed to connect to Vespera:\n{message}")
            return

        self.sessions = data or []
        self.refresh_btn.setEnabled(True)
        self._populate_sessions_tree()
        self.status_bar.showMessage(f"Connected - {len(self.sessions)} sessions found")

        if self.siril:
            self.siril.log(f"Vespera FTP: Found {len(self.sessions)} sessions",
                          color=LogColor.GREEN)

    def _populate_sessions_tree(self):
        """Populate the sessions tree widget."""
        self.sessions_tree.clear()

        # Group sessions by type
        observations = []
        plans = []
        darks = []
        others = []

        for session in self.sessions:
            session_type_lower = session.session_type.lower() if session.session_type else ''
            if session_type_lower == 'observation':
                observations.append(session)
            elif session_type_lower == 'plan':
                plans.append(session)
            elif session_type_lower == 'dark':
                darks.append(session)
            else:
                others.append(session)

        # Add observations
        if observations:
            obs_root = QTreeWidgetItem(self.sessions_tree, ["Observations", "", "", ""])
            obs_root.setExpanded(True)
            for session in observations:
                self._add_session_item(obs_root, session)

        # Add plans
        if plans:
            plan_root = QTreeWidgetItem(self.sessions_tree, ["Observation Plans", "", "", ""])
            plan_root.setExpanded(True)
            for session in plans:
                self._add_session_item(plan_root, session)

        # Add darks
        if darks:
            dark_root = QTreeWidgetItem(self.sessions_tree, ["Dark Frames", "", "", ""])
            for session in darks:
                self._add_session_item(dark_root, session)

        # Add others
        if others:
            other_root = QTreeWidgetItem(self.sessions_tree, ["Other", "", "", ""])
            for session in others:
                self._add_session_item(other_root, session)

    def _add_session_item(self, parent: QTreeWidgetItem, session: SessionInfo):
        """Add a session item to the tree."""
        date_str = session.date.strftime("%Y-%m-%d %H:%M") if session.date else "Unknown"
        display_name = f"{session.target} ({date_str})"

        item = QTreeWidgetItem(parent, [
            display_name,
            str(session.sub_count) if session.sub_count else "-",
            "Yes" if session.has_dark else "-",
            "Yes" if session.has_preview else "-"
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, session)

        # Color code based on status
        if session.sub_count > 0:
            item.setForeground(1, QColor("#88ff88"))
        if session.has_dark:
            item.setForeground(2, QColor("#88ff88"))
        if session.has_preview:
            item.setForeground(3, QColor("#88ff88"))

    def _on_session_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle session tree item click."""
        session = item.data(0, Qt.ItemDataRole.UserRole)
        if not session:
            return

        self.current_session = session
        self.download_btn.setEnabled(True)
        self._update_details_panel(session)
        self._load_session_details(session)

    def _update_details_panel(self, session: SessionInfo):
        """Update the details panel with session info."""
        self.detail_labels["Name"].setText(session.name)
        self.detail_labels["Date"].setText(
            session.date.strftime("%Y-%m-%d %H:%M:%S") if session.date else "Unknown"
        )
        self.detail_labels["Target"].setText(session.target)
        self.detail_labels["Type"].setText(session.session_type.title())
        self.detail_labels["Subs"].setText(str(session.sub_count) if session.sub_count else "Scanning...")

        # Calculate and display integration time
        if session.sub_count > 0:
            integration_str = session.integration_time_str
            self.detail_labels["Integration"].setText(integration_str)
            self.detail_labels["Integration"].setStyleSheet("color: #88aaff;")
        else:
            self.detail_labels["Integration"].setText("-")
            self.detail_labels["Integration"].setStyleSheet("color: #888888;")

        self.detail_labels["Dark"].setText("Yes" if session.has_dark else "No")
        self.detail_labels["Masters"].setText("Yes" if session.has_masters else "No")

        # Color code
        if session.sub_count > 0:
            self.detail_labels["Subs"].setStyleSheet("color: #88ff88;")
        else:
            self.detail_labels["Subs"].setStyleSheet("color: #888888;")

        if session.has_dark:
            self.detail_labels["Dark"].setStyleSheet("color: #88ff88;")
        else:
            self.detail_labels["Dark"].setStyleSheet("color: #ffaa44;")

    def _load_session_details(self, session: SessionInfo):
        """Load detailed info for a session."""
        if self.browse_mode == "local":
            # For local, details are already loaded during scan
            # Just trigger preview load
            if session.sub_count > 0:
                self._load_preview(session)
            return

        # FTP mode - load details from telescope
        self.progress_bar.setVisible(True)
        self.status_bar.showMessage(f"Loading details for {session.target}...")

        host = self.host_input.text().strip()
        self.worker = FTPWorker(host, DEFAULT_FTP_PORT, "get_session_details",
                               path=session.path)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_details_loaded)
        self.worker.start()

    def _on_details_loaded(self, success: bool, message: str, data):
        """Handle session details loaded."""
        self.progress_bar.setVisible(False)

        if not success:
            self.status_bar.showMessage(f"Error: {message}")
            return

        if data and self.current_session:
            # Update session with new details
            self.current_session.sub_count = data.sub_count
            self.current_session.has_dark = data.has_dark
            self.current_session.has_masters = data.has_masters
            self.current_session.observations = data.observations

            self._update_details_panel(self.current_session)
            self.status_bar.showMessage(f"Loaded: {self.current_session.sub_count} subs")

            # Update tree item
            self._update_tree_item(self.current_session)

            # Load preview of first sub
            if self.current_session.sub_count > 0:
                self._load_preview(self.current_session)

    def _update_tree_item(self, session: SessionInfo):
        """Update tree item with new session data."""
        # Find and update the item in the tree
        for i in range(self.sessions_tree.topLevelItemCount()):
            root = self.sessions_tree.topLevelItem(i)
            for j in range(root.childCount()):
                item = root.child(j)
                item_session = item.data(0, Qt.ItemDataRole.UserRole)
                if item_session and item_session.path == session.path:
                    item.setText(1, str(session.sub_count) if session.sub_count else "-")
                    item.setText(2, "Yes" if session.has_dark else "-")
                    item.setText(3, "Yes" if session.has_preview else "-")
                    if session.sub_count > 0:
                        item.setForeground(1, QColor("#88ff88"))
                    if session.has_dark:
                        item.setForeground(2, QColor("#88ff88"))
                    if session.has_preview:
                        item.setForeground(3, QColor("#88ff88"))
                    return

    def _on_tree_context_menu(self, position):
        """Show context menu for tree items."""
        item = self.sessions_tree.itemAt(position)
        if not item:
            return

        session = item.data(0, Qt.ItemDataRole.UserRole)
        if not session:
            return

        menu = QMenu()
        download_action = menu.addAction("Download Session")
        preview_action = menu.addAction("Preview First Sub")

        action = menu.exec(self.sessions_tree.mapToGlobal(position))

        if action == download_action:
            self.current_session = session
            self._on_download()
        elif action == preview_action:
            self._preview_session(session)

    def _preview_session(self, session: SessionInfo):
        """Preview first sub from a session."""
        self._load_preview(session)

    def _load_preview(self, session: SessionInfo):
        """Load a preview image from the session.

        The Vespera stores a stacked TIFF in the same folder as the FITS subs.
        We look for this TIFF first as it's already stacked and shows the final result.
        """
        self.preview_widget.setPlaceholderText("Loading preview...")
        self.preview_widget.clear()
        self.status_bar.showMessage(f"Loading preview for {session.target}...")

        if self.browse_mode == "local":
            # Load preview from local folder
            self._load_local_preview(session)
        else:
            # Look for TIFF preview file via FTP
            host = self.host_input.text().strip()
            self.preview_worker = FTPWorker(host, DEFAULT_FTP_PORT, "find_preview",
                                            path=session.path)
            self.preview_worker.progress.connect(self._on_progress)
            self.preview_worker.finished.connect(self._on_preview_found)
            self.preview_worker.start()

    def _load_local_preview(self, session: SessionInfo):
        """Load preview from a local session folder."""
        # Find all preview files in the session
        self.preview_paths = self._find_all_local_previews(session.path)
        self.preview_index = 0

        if not self.preview_paths:
            self.preview_widget.setPlaceholderText("No preview TIFF found")
            self.preview_widget.clear()
            self._update_preview_nav_visibility()
            self.status_bar.showMessage("Could not find preview TIFF in session folder")
            return

        # Update navigation visibility
        self._update_preview_nav_visibility()

        # Load the first preview
        self._load_preview_at_index(0)

    def _update_preview_nav_visibility(self):
        """Show/hide preview navigation based on number of previews."""
        has_multiple = len(self.preview_paths) > 1
        self.btn_prev_preview.setVisible(has_multiple)
        self.lbl_preview_nav.setVisible(has_multiple)
        self.btn_next_preview.setVisible(has_multiple)
        if has_multiple:
            self.lbl_preview_nav.setText(f"{self.preview_index + 1} / {len(self.preview_paths)}")

    def _prev_preview(self):
        """Navigate to previous preview."""
        if self.preview_paths and self.preview_index > 0:
            self._load_preview_at_index(self.preview_index - 1)

    def _next_preview(self):
        """Navigate to next preview."""
        if self.preview_paths and self.preview_index < len(self.preview_paths) - 1:
            self._load_preview_at_index(self.preview_index + 1)

    def _load_preview_at_index(self, index: int):
        """Load preview at the specified index."""
        if not self.preview_paths or index < 0 or index >= len(self.preview_paths):
            return

        self.preview_index = index
        preview_path = self.preview_paths[index]

        # Update navigation label
        if len(self.preview_paths) > 1:
            self.lbl_preview_nav.setText(f"{index + 1} / {len(self.preview_paths)}")
            # Update button states
            self.btn_prev_preview.setEnabled(index > 0)
            self.btn_next_preview.setEnabled(index < len(self.preview_paths) - 1)

        # Get observation folder name for status
        parent_folder = os.path.basename(os.path.dirname(preview_path))
        self.status_bar.showMessage(f"Loading: {parent_folder}/{os.path.basename(preview_path)}...")

        try:
            # Determine file type
            ext = os.path.splitext(preview_path)[1].lower()

            if ext in ['.tif', '.tiff']:
                # Load TIFF with Pillow
                from PIL import Image
                img = Image.open(preview_path)
                img_array = np.array(img)

                # Handle different bit depths
                if img_array.dtype == np.uint16:
                    img_array = img_array.astype(np.float32) / 65535.0
                elif img_array.dtype == np.uint8:
                    img_array = img_array.astype(np.float32) / 255.0
                else:
                    img_array = img_array.astype(np.float32)

                # If RGB, transpose to (channels, height, width) for consistency
                if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                    img_array = np.transpose(img_array, (2, 0, 1))

            elif ext in ['.fits', '.fit']:
                # Load FITS with astropy
                with fits.open(preview_path) as hdul:
                    img_array = hdul[0].data.astype(np.float32)
            else:
                self.preview_widget.setPlaceholderText(f"Unsupported format: {ext}")
                self.preview_widget.clear()
                return

            # Convert to QPixmap with auto-stretch (full resolution for zooming)
            pixmap = fits_to_qpixmap(img_array)  # No size limit - full resolution

            if pixmap.isNull():
                self.preview_widget.setPlaceholderText("Failed to render preview")
                self.preview_widget.clear()
                return

            self.preview_widget.setPixmap(pixmap)
            self.status_bar.showMessage(f"Preview: {parent_folder} - scroll to zoom, drag to pan")

        except Exception as e:
            self.preview_widget.setPlaceholderText(f"Preview error: {e}")
            self.preview_widget.clear()
            self.status_bar.showMessage(f"Preview error: {e}")

    def _find_all_local_previews(self, session_path: str) -> List[str]:
        """Find ALL preview TIFFs in a local session folder.

        For plan sessions with multiple observations, returns all TIFFs.
        Results are sorted by folder name for consistent ordering.
        """
        previews = []

        # First check session root for TIFF
        try:
            for entry in sorted(os.listdir(session_path)):
                entry_lower = entry.lower()
                if entry_lower.endswith('.tif') or entry_lower.endswith('.tiff'):
                    previews.append(os.path.join(session_path, entry))
        except:
            pass

        # Check observation subdirectories for plan sessions (sorted)
        try:
            entries = sorted(os.listdir(session_path))
            for entry in entries:
                entry_path = os.path.join(session_path, entry)
                if os.path.isdir(entry_path) and 'observation' in entry.lower():
                    # Check observation root for TIFFs
                    try:
                        for obs_entry in sorted(os.listdir(entry_path)):
                            obs_lower = obs_entry.lower()
                            if obs_lower.endswith('.tif') or obs_lower.endswith('.tiff'):
                                previews.append(os.path.join(entry_path, obs_entry))
                    except:
                        pass
        except:
            pass

        return previews

    def _find_local_preview(self, session_path: str) -> Optional[str]:
        """Find a preview TIFF in a local session folder (returns first one)."""
        previews = self._find_all_local_previews(session_path)
        return previews[0] if previews else None

    def _search_local_folder_for_tiff(self, folder_path: str) -> Optional[str]:
        """Search a local folder for TIFF files."""
        try:
            for entry in os.listdir(folder_path):
                entry_lower = entry.lower()
                if entry_lower.endswith('.tif') or entry_lower.endswith('.tiff'):
                    return os.path.join(folder_path, entry)
        except:
            pass
        return None

    def _on_preview_found(self, success: bool, message: str, data):
        """Handle preview file found - now download it."""
        if not success or not data:
            self.preview_widget.setPlaceholderText("No preview TIFF found")
            self.preview_widget.clear()
            self.status_bar.showMessage("Could not find preview TIFF")
            return

        preview_path = data.get('path')
        preview_type = data.get('type', 'tiff')

        if not preview_path:
            self.preview_widget.setPlaceholderText("No preview file found")
            self.preview_widget.clear()
            return

        self.status_bar.showMessage(f"Downloading preview: {preview_path.split('/')[-1]}...")

        # Download the preview file
        host = self.host_input.text().strip()
        self.preview_worker = FTPWorker(host, DEFAULT_FTP_PORT, "download_preview_file",
                                        path=preview_path, file_type=preview_type)
        self.preview_worker.progress.connect(self._on_progress)
        self.preview_worker.finished.connect(self._on_preview_loaded)
        self.preview_worker.start()

    def _on_preview_loaded(self, success: bool, message: str, data):
        """Handle preview image loaded."""
        self.progress_bar.setVisible(False)

        if not success or data is None:
            self.preview_widget.clear()
            self.preview_widget.setPlaceholderText("Failed to load preview")
            self.status_bar.showMessage(f"Preview failed: {message}")
            return

        # Convert FITS data to QPixmap with auto-stretch
        try:
            # Use full resolution - the widget handles zooming
            pixmap = fits_to_qpixmap(data, None)

            if pixmap.isNull():
                self.preview_widget.clear()
                self.preview_widget.setPlaceholderText("Failed to render preview")
                return

            self.preview_widget.setPixmap(pixmap)
            self.status_bar.showMessage("Preview loaded (auto-stretched) - scroll to zoom, drag to pan")

        except Exception as e:
            self.preview_widget.clear()
            self.preview_widget.setPlaceholderText(f"Preview error: {e}")
            self.status_bar.showMessage(f"Preview error: {e}")

    def _on_browse_download(self):
        """Browse for download location."""
        path = QFileDialog.getExistingDirectory(
            self, "Select Download Location",
            self.download_path.text() or str(Path.home())
        )
        if path:
            self.download_path.setText(path)
            self._save_settings()

    def _on_download(self):
        """Download the current session or open in Siril (for local mode)."""
        if not self.current_session:
            QMessageBox.warning(self, "Error", "Please select a session first.")
            return

        if self.browse_mode == "local":
            # Local mode - open session folder in Siril
            self._open_local_session()
            return

        # FTP mode - download session
        download_path = self.download_path.text().strip()
        if not download_path:
            QMessageBox.warning(self, "Error", "Please select a download location.")
            return

        # Create session folder
        local_path = os.path.join(download_path, self.current_session.name)

        if os.path.exists(local_path):
            reply = QMessageBox.question(
                self, "Folder Exists",
                f"Folder '{self.current_session.name}' already exists.\nOverwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.download_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_bar.showMessage(f"Downloading {self.current_session.target}...")

        host = self.host_input.text().strip()
        self.worker = FTPWorker(host, DEFAULT_FTP_PORT, "download_session",
                               remote_path=self.current_session.path,
                               local_path=local_path)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(lambda s, m, d: self._on_download_finished(s, m, local_path))
        self.worker.start()

    def _open_local_session(self):
        """Open a local session folder in Siril."""
        if not self.current_session:
            return

        session_path = self.current_session.path

        if not os.path.isdir(session_path):
            QMessageBox.warning(self, "Error", f"Session folder not found:\n{session_path}")
            return

        # Set Siril working directory
        if self.siril:
            try:
                self.siril.cmd("cd", session_path)
                self.siril.log(f"Working directory set to: {session_path}", color=LogColor.GREEN)
                self.status_bar.showMessage(f"Opened: {session_path}")

                QMessageBox.information(self, "Session Opened",
                                       f"Siril working directory set to:\n\n{session_path}")
            except Exception as e:
                self.siril.log(f"Could not set working directory: {e}", color=LogColor.SALMON)
                QMessageBox.critical(self, "Error",
                                    f"Could not set Siril working directory:\n{e}")

    def _on_download_finished(self, success: bool, message: str, local_path: str):
        """Handle download completion."""
        self.download_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        if not success:
            self.status_bar.showMessage(f"Download failed: {message}")
            QMessageBox.critical(self, "Download Error", f"Download failed:\n{message}")
            return

        self.status_bar.showMessage(f"Downloaded to {local_path}")

        if self.siril:
            self.siril.log(f"Downloaded session to: {local_path}", color=LogColor.GREEN)

        # Set Siril working directory if requested
        if self.set_workdir_cb.isChecked() and self.siril:
            try:
                self.siril.cmd("cd", local_path)
                self.siril.log(f"Working directory set to: {local_path}", color=LogColor.GREEN)
            except Exception as e:
                self.siril.log(f"Could not set working directory: {e}", color=LogColor.SALMON)

        QMessageBox.information(self, "Download Complete",
                               f"Session downloaded successfully!\n\n{local_path}")

    def closeEvent(self, event):
        """Handle window close."""
        self._save_settings()
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        event.accept()


def main():
    """Main entry point."""
    try:
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)

        siril = s.SirilInterface()

        # Connect to Siril
        try:
            siril.connect()
        except s.SirilConnectionError:
            QMessageBox.critical(None, "Connection Error",
                               "Could not connect to Siril.\n"
                               "Make sure Siril is running.")
            return

        # Check Siril version
        try:
            siril.cmd("requires", "1.3.0")
        except s.CommandError:
            QMessageBox.critical(None, "Version Error",
                               "This plugin requires Siril 1.3.0 or later.")
            return

        siril.log("Vespera FTP Browser started", color=LogColor.GREEN)

        window = VesperaFTPBrowserWindow(siril)
        window.show()

        app.exec()

    except Exception as e:
        print(f"Vespera FTP Browser error: {e}")
        raise


if __name__ == "__main__":
    main()
