# Vespera Pro Siril Plugin - Claude Code Handoff

## Project Overview

I'm building a **Python plugin for Siril** (astrophotography software) specifically designed for the **Vaonis Vespera Pro** smart telescope. The plugin automates the preprocessing/stacking workflow with features tailored to this telescope's characteristics.

**There are TWO plugins:**
1. `Vespera_Pro_Drizzle.py` - Full preprocessing pipeline (dark calibration, registration, stacking, etc.)
2. `Vespera_Quick_Prep.py` - Quick one-click preparation for already-stacked TIFFs

## Key Context

### The Telescope
- **Vaonis Vespera Pro** - a smart, alt-azimuth mounted telescope
- **Sony IMX676 sensor** - 3536x3536, 2.0µm pixels, GBRG Bayer pattern
- **Alt-az mount causes field rotation** during long observations (can be 10-15°+)
- **Expert Mode** captures raw FITS files but often only captures 1 dark frame
- I have a **SVBONY SV220 dual-band filter** (Ha/OIII) for narrowband imaging

### The Problem We're Solving
1. Standard Siril scripts don't handle single dark frames (they expect multiple to stack)
2. Field rotation from alt-az mount causes grid/checkerboard artifacts if not handled properly
3. Dual-band filter requires special Ha/OIII channel extraction
4. Manual cleanup of temp files is tedious (Siril scripts can't delete files)
5. Different sky conditions (Bortle scale) need different processing parameters
6. Native Vespera folder structure needs auto-detection (not pre-organized folders)

### Current Solution
Python plugins (`.py` files) that run inside Siril 1.4+ using the `sirilpy` API. Python gives us:
- File system access for cleanup
- Conditional logic for single vs multiple darks
- GUI via PyQt6
- Settings persistence via QSettings

## CRITICAL: sirilpy API

### Correct Import Pattern
```python
import sirilpy as s
from sirilpy import LogColor

s.ensure_installed("PyQt6", "numpy")  # Auto-install dependencies

siril = s.SirilInterface()  # NOT Siril() - that class doesn't exist!
siril.connect()
siril.cmd("command", "arg1", "arg2")  # Execute Siril commands
siril.log("message", color=LogColor.GREEN)  # Log to console - NOT s.log()!
siril.get_siril_wd()  # Get working directory - NOT get_cwd()!
```

**AVOID:**
- `from sirilpy import Siril` - doesn't exist
- `from sirilpy import SirilError` - doesn't exist, use `Exception` instead
- `siril.get_cwd()` - wrong method name, use `siril.get_siril_wd()`
- `s.log()` - doesn't exist, use `siril.log(msg, color=LogColor.GREEN)` instead

## Recent Session History (January 2026)

### Session 1: Initial Development
- Built Vespera_Pro_Drizzle.py with PyQt6 GUI
- Added filter presets, sky quality options, stacking methods
- Implemented single dark frame handling
- Created cleanup functions for temp files

### Session 2: Bug Fixes and VeraLux Compatibility
**Major bugs fixed:**
1. `get_cwd()` → `get_siril_wd()` (API method name)
2. Script loading location - symlinked to `~/Library/Application Support/org.siril.Siril/scripts/`

**VeraLux stretch overexposure issue:**
- Discovered that after running Photometric Color Calibration (PCC), images would appear overexposed in VeraLux
- Root cause: **ICC profiles embedded by PCC** were confusing VeraLux's pixel data retrieval
- Solution: Added `icc_remove` command before saving all outputs

**Stack command evolution:**
- Removed `-rgb_equal` (was causing brightness issues)
- Kept `-output_norm` for proper normalization
- Added `-32b` for 32-bit precision (works fine now with ICC removal)
- Current stack: `"-norm=addscale", "-output_norm", "-32b", "-out=result"`

### Session 3: Native Folder Structure Support
**Added auto-detection of Vespera's native folder structure:**
- Dark frame(s): `img-*-dark.fits` in root directory
- Light frames: `01-images-initial/*.fits` subfolder

**The plugin now works with EITHER:**
1. Native Vespera structure (no reorganization needed)
2. Pre-organized structure (darks/, lights/ folders)

**Work in progress:**
- Convert command pattern issues with native structure
- Sequence naming after convert

### Session 4: Quick Prep Plugin Fix (Current Session)
**Fixed Vespera_Quick_Prep.py:**
- Changed `from sirilpy import Siril, SirilError, LogColor` to `from sirilpy import LogColor`
- Changed `siril = Siril()` to `siril = s.SirilInterface()`
- Changed `except SirilError` to `except Exception`

## Siril Script Installation

### CRITICAL: Script Location for macOS
Python scripts MUST be placed in this exact directory for Siril to find them:
```
~/Library/Application Support/org.siril.Siril/scripts/
```

**Full expanded path:**
```
/Users/dannyortega/Library/Application Support/org.siril.Siril/scripts/
```

**NOT these locations (common mistakes):**
- `~/Library/Application Support/siril/scripts/` - wrong folder name
- `~/Library/Application Support/org.siril.Siril/siril-scripts/` - this is for OTHER plugins like VeraLux
- `/Applications/Siril.app/Contents/Resources/scripts/` - system scripts, don't modify

### Script Loading in Siril
1. Place `.py` file in the scripts folder (or symlink to it)
2. In Siril: **Scripts → Refresh Scripts** (or restart Siril)
3. Access via: **Scripts → Python Scripts → [Your Script Name]**

### Our Setup (Using Symlinks)
We develop in a git repo and symlink to Siril's scripts folder:

```bash
# Create symlinks (already done)
ln -s ~/claude-projects/vespera-siril-plugin/Vespera_Pro_Drizzle.py \
      ~/Library/Application\ Support/org.siril.Siril/scripts/
ln -s ~/claude-projects/vespera-siril-plugin/Vespera_Quick_Prep.py \
      ~/Library/Application\ Support/org.siril.Siril/scripts/
```

## File Structure

```
~/claude-projects/vespera-siril-plugin/     # Git repo (development)
├── .git/
├── .claude/                    # Project settings
├── CLAUDE_CODE_HANDOFF.md      # This file
├── README.md
├── LICENSE
├── Vespera_Pro_Drizzle.py      # Main preprocessing plugin
└── Vespera_Quick_Prep.py       # Quick TIFF prep plugin

~/Library/Application Support/org.siril.Siril/scripts/   # Siril reads from here
├── Vespera_Pro_Drizzle.py → ../../claude-projects/.../Vespera_Pro_Drizzle.py
└── Vespera_Quick_Prep.py  → ../../claude-projects/.../Vespera_Quick_Prep.py
```

### Vespera Native Folder Structure
```
observation_folder/
├── img-0001-dark.fits          # Dark frame(s) in root
├── 01-images-initial/          # Light frames subfolder
│   ├── img-0025.fits
│   ├── img-0026.fits
│   └── ... (many light frames)
├── process/                    # Created by plugin (temp)
├── masters/                    # Created by plugin (temp)
└── result_*.fit                # Output
```

## Reference Material

### IMPORTANT: Read the Vespera Pro Skill First
```
/mnt/skills/user/vespera-pro-astrophotography/SKILL.md
```

### VeraLux Plugin Examples (in same scripts folder)
- `VeraLux_HyperMetric_Stretch.py` - complex GUI patterns
- `VeraLux_Silentium.py` - file cleanup patterns

## Current Plugin Features

### Vespera_Pro_Drizzle.py (v2.0.0)

**Main Tab:**
- Filter Selection: Stock, SVBONY SV220 dual-band, L-Pro/CLS, Ha/OIII narrowband
- Sky Quality: Bortle 1-2 through 7-8 (adjusts sigma rejection)
- Stacking Method: Bayer Drizzle (recommended), Standard, Drizzle 2x

**Options Tab:**
- Auto Background Extraction after stacking
- Auto Photometric Color Calibration
- Keep temp files option

**Processing Pipelines:**
1. Standard RGB - calibrate → register → stack → flip → icc_remove → save
2. Dual-band Ha/OIII - calibrate → register → stack → split_cfa → extract channels → HOO composite
3. Narrowband - single channel extraction

### Vespera_Quick_Prep.py

**Purpose:** Quick one-click preparation for already-stacked TIFFs from Vespera's internal stacking

**Steps:** Background extraction → Plate solve → PCC → Optional denoise

## Known Issues / TODO

1. **Native folder structure** - Convert command patterns need work for single-file darks
2. **Dual-band extraction** - CFA split logic needs verification with actual SV220 data
3. **Ha/OIII channel mapping** - Which CFA indices are correct for GBRG pattern?
4. **GUI window sizing** - Min height set to 750px but may need adjustment
5. **Error recovery** - Needs better handling of failed steps

## Siril Command Reference

Key commands used:
- `convert` - convert files to .fit sequence
- `calibrate` - apply dark/flat/bias calibration
- `register` - align frames (with `-drizzle` option)
- `stack` - combine registered frames (with `-norm=addscale -output_norm -32b`)
- `load/save` - file operations
- `mirrorx -bottomup` - correct orientation
- `split_cfa` - separate Bayer channels
- `subsky` - background extraction
- `pcc` - photometric color calibration
- `icc_remove` - **CRITICAL** - remove ICC profile before VeraLux processing

## Development Notes

### Testing Workflow
1. Edit files in repo (changes auto-sync via symlink)
2. In Siril: Scripts → Refresh Scripts (or restart)
3. Set working directory to observation folder
4. Scripts → Python Scripts → select plugin
5. Check Siril console for errors

### Siril Config Notes
- `force_16bit=true` in config - forces 16-bit output
- `fits_save_icc=true` - embeds ICC profiles (causes VeraLux issues without icc_remove)

---

**Start by reading the SKILL.md file, then review the current plugin code. The main focus areas are:**
1. Complete native folder structure support in Vespera_Pro_Drizzle.py
2. Test both plugins end-to-end with real observation data
3. Verify VeraLux compatibility after processing
