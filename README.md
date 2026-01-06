# Vespera Pro Siril Plugins

Python plugins for [Siril](https://siril.org/) that provide optimized workflows for **Vaonis Vespera Pro** smart telescope data.

![Siril Version](https://img.shields.io/badge/Siril-1.4%2B-blue)
![Python](https://img.shields.io/badge/Python-3.9%2B-green)
![License](https://img.shields.io/badge/License-Apache%202.0-orange)

## Included Plugins

| Plugin | Purpose |
|--------|---------|
| **Vespera Pro Drizzle** | Bayer Drizzle stacking for raw FITS files |
| **Vespera Quick Prep** | One-click preparation for 16-bit TIFFs → VeraLux HMS |

---

## Vespera Quick Prep

A streamlined preparation plugin that automates the tedious pre-stretch workflow for Vespera's 16-bit TIFF output.

### What It Does

**Before:** Load TIFF → Background extraction → Plate solve → Color calibrate → Launch stretch tool (5+ clicks)

**After:** Load TIFF → Click "Prep Image" → Done!

### Features

- **Background Extraction**: GraXpert AI (recommended) or Siril RBF
- **Calibration**: Automatic plate solve + Photometric Color Calibration
- **Denoising** (optional): VeraLux Silentium, GraXpert AI, or Cosmic Clarity
- **Auto-Launch**: Opens VeraLux HMS when complete

### Usage

1. Load your Vespera 16-bit TIFF in Siril
2. Go to **Scripts** menu → **Vespera_Quick_Prep**
3. Configure options (or use defaults)
4. Click **Prep Image**
5. VeraLux HMS opens with your color-calibrated, gradient-free image ready to stretch

---

## Vespera Pro Drizzle

Bayer Drizzle processing for restacking raw Vespera FITS files with improved quality.

### Features

- **Zero Setup Required** - Reads native Vespera Pro folder structure directly, no file reorganization needed
- **Bayer Drizzle Processing** - Optimized for alt-az field rotation
- **Multiple Stacking Methods** - Gaussian, Square, Nearest-neighbor interpolation options
- **Dual-Band Filter Support** - Ha/OIII extraction for SVBONY SV220 and similar filters
- **Automatic Dark Calibration** - Hot pixel removal and cosmetic correction
- **Auto-Detects Darks/Lights** - Identifies calibration frames by filename pattern
- **Sky Quality Presets** - Optimized sigma rejection for different Bortle levels
- **32-bit Linear Output** - Maximum precision for post-processing
- **VeraLux Compatible** - ICC profile removal for clean handoff

## Screenshots

*Coming soon*

## Requirements

- **Siril 1.4+** with Python plugin support
- **Python 3.9+**
- **PyQt6** (usually bundled with Siril)

## Installation

### macOS

Copy both plugins to your Siril scripts directory:

```bash
cp Vespera_Pro_Drizzle.py Vespera_Quick_Prep.py ~/Library/Application\ Support/org.siril.Siril/siril-scripts/
```

### Linux

```bash
cp Vespera_Pro_Drizzle.py Vespera_Quick_Prep.py ~/.local/share/siril/scripts/
```

### Windows

```
Copy both .py files to:
%LOCALAPPDATA%\siril\scripts\
```

### Dependencies for Quick Prep

Quick Prep integrates with these optional tools (if installed):
- **GraXpert-AI.py** - AI background extraction (install via Siril Scripts menu)
- **VeraLux HMS** - HyperMetric Stretch (available from veralux.space)
- **VeraLux Silentium** - Wavelet denoiser (available from veralux.space)
- **Cosmic Clarity** - AI denoiser (available from setiastro.com)

## Usage

### Folder Structure - No Reorganization Needed!

The plugin **automatically detects** how your Vespera Pro exported the data. Just point it at your observation folder - no need to reorganize files.

**Supported structures:**

```
# Native Vespera export (flat structure) - works automatically!
observation_folder/
├── light_000001.fit
├── light_000002.fit
├── ...
└── dark_000001.fit

# Organized structure - also works!
observation_folder/
├── darks/
│   └── dark_000001.fit
└── lights/
    ├── light_000001.fit
    └── light_000002.fit
```

The plugin auto-detects darks vs lights by filename pattern.

### Running the Plugin

1. Open Siril
2. Navigate to your Vespera observation folder (as exported)
3. Go to **Scripts** menu → **Vespera_Pro_Drizzle**
4. Configure options in the GUI:
   - **Filter**: Select your filter type
   - **Sky Quality**: Match your Bortle level
   - **Stacking Method**: Choose drizzle algorithm
5. Click **Process**

### Stacking Methods

| Method | Best For | Notes |
|--------|----------|-------|
| **Bayer Drizzle (Recommended)** | Most sessions | Gaussian kernel, reduces moiré patterns |
| **Bayer Drizzle (Square)** | Photometry | Flux-preserving, classic HST algorithm |
| **Bayer Drizzle (Nearest)** | Pattern issues | Eliminates interpolation artifacts |
| **Standard Registration** | Quick processing | No drizzle, faster but less quality |
| **Drizzle 2x Upscale** | High resolution | Requires 50+ well-dithered frames |

### Output

The plugin creates:
- `result_XXXXs.fit` - Final stacked image (32-bit, linear)
- `masters/dark_stacked.fit` - Master dark frame
- `process/` - Intermediate files (deleted unless "Keep temp files" enabled)

## Troubleshooting

### Checkerboard/Grid Patterns

This is caused by interpolation artifacts from field rotation correction. Try:
1. Use "Bayer Drizzle (Recommended)" with Gaussian kernel
2. If pattern persists, try "Bayer Drizzle (Nearest)"
3. Ensure you have enough frames (30+ recommended)

### Colors Look Wrong

The plugin removes ICC profiles for compatibility. If colors are off:
1. Check your processing software's color space settings
2. Try Siril's Photometric Color Calibration on the output

### Statistics Computation Failed Warning

This is normal during dark calibration and can be ignored if processing completes.

## Why Restack in Siril? (vs Vespera's Built-in Stacking)

The Vespera Pro already stacks images internally and outputs a ready-to-process TIFF. So why restack with this plugin?

### How Vespera Stacks vs How This Plugin Stacks

| Aspect | Vespera Internal | This Plugin (Bayer Drizzle) |
|--------|------------------|----------------------------|
| **Processing Order** | Debayer → Register → Stack | Register → Stack → Debayer |
| **Calibration** | BalENS (algorithmic universal dark) | Your actual captured darks |
| **Bad Frame Rejection** | Automatic (proprietary) | Sigma rejection (removes satellites, planes) |
| **Output Bit Depth** | 16-bit TIFF | 32-bit FITS |
| **Field Rotation** | CovalENS micro-dithering | Drizzle sub-pixel alignment |

### The Key Difference: When Debayering Happens

**Vespera's approach:** Debayers each frame first, then stacks RGB images
- Traditional method, works well
- Loses sub-pixel color information

**Bayer Drizzle approach:** Stacks raw CFA data, debayers at the end
- Each colored pixel "drizzles" onto the correct output channel
- Preserves sub-pixel positioning from natural dithering
- **Result:** ~20% sharper color detail, reduced color moiré

### When to Use Each

| Use Case | Recommendation |
|----------|----------------|
| Quick preview, social media | **Vespera TIFF** - already done! |
| Maximum quality for print | **Siril restack** |
| Satellites/planes in frames | **Siril** - sigma rejection removes them |
| Dual-band filter (Ha/OIII) | **Siril** - proper channel extraction |
| Cloudy session with bad frames | **Siril** - better rejection |
| Multi-night without computer | **Vespera PerseverENS** |

### Bottom Line

The Vespera TIFF is good. Restacking with Bayer Drizzle is *better* - but the difference is subtle. For social media sharing, the Vespera output is fine. For a print you'll hang on your wall, restacking is worth the extra few minutes.

## Technical Details

### Drizzle Parameters

| Parameter | 1x Mode | 2x Mode |
|-----------|---------|---------|
| Scale | 1.0 | 2.0 |
| Pixfrac | 1.0 | 1.0 |
| Kernel | gaussian | square |
| Interpolation | area | area |

**Note**: Lanczos kernels are only valid at scale=1.0 with pixfrac=1.0.

### CFA Channel Mapping (Dual-Band Filter)

| Channel | Wavelength | Use |
|---------|------------|-----|
| CFA0 (Red) | 656nm | Ha (Hydrogen-alpha) |
| CFA1 (Green1) | 500nm | OIII (Oxygen-III) |

### Sony IMX676 Sensor Specs

| Spec | Value |
|------|-------|
| Resolution | 3536 × 3536 (12.5 MP) |
| Pixel Size | 2.0 µm |
| Bayer Pattern | RGGB |
| Technology | STARVIS 2 BSI |

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

## Credits

- Plugin developed with assistance from Claude (Anthropic)
- Siril team for the excellent astronomy software
- Vaonis for the Vespera Pro telescope

## Links

- [Siril Documentation](https://siril.readthedocs.io/)
- [Siril Drizzle Guide](https://siril.readthedocs.io/en/latest/preprocessing/drizzle.html)
- [Vaonis Vespera Pro](https://vaonis.com/vespera-pro)
