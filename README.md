# 🎯 Snapmaker U1 Spool Tracker

[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Snapmaker](https://img.shields.io/badge/printer-Snapmaker%20U1-orange.svg)](https://snapmaker.com)

**Intelligent 4-toolhead filament inventory management and automatic runout protection for Snapmaker U1 & OrcaSlicer / Snapmaker Orca.**

---

## 🛑 The Problem

When running large multi-color or multi-material prints on the Snapmaker U1:
1. **Unattended Mid-Print Runout**: If a spool runs out while you are away, the printer pauses.
2. **Bed Cooling Failure**: On prolonged pauses, heated beds often cool down. Once the bed temperature drops, print adhesion fails and the model detaches from the plate — ruining hours of print time.
3. **Complex Math**: Keeping track of remaining filament across 4 independent toolheads (T0–T3) plus purge tower volumes is tedious to calculate manually.

---

## ✨ The Solution

**Snapmaker U1 Spool Tracker** acts as a background menu bar service and an OrcaSlicer post-processing hook:

- 🔍 **Pre-Flight Runout Interception**: Analyzes sliced G-code before export. If any assigned spool lacks enough filament, it halts the export and triggers a native alert dialog.
- 🎛 **4-Toolhead Slot Mapping**: Intuitive web UI to assign physical spools to Toolheads T0 through T3.
- 📉 **Automatic Spool Deduction**: Automatically subtracts used grams from your inventory upon successful export.
- 🌐 **Multi-Language Support**: English, Deutsch, Русский, Українська, Español.
- 🍏 **Zero Terminal Needed**: Runs quietly in the macOS menu bar as a standalone `.app`.

---

## 🚀 Quick Start (for macOS Users)

### 1. Download & Install
1. Go to [Releases](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases) and download `SnapmakerSpoolTracker-macOS.zip`.
2. Extract the archive and drag **`SnapmakerSpoolTracker.app`** into your `/Applications` folder.
3. Launch the app from `/Applications`. A color toolhead icon will appear in your top macOS menu bar.

### 2. Configure OrcaSlicer
1. Open **Snapmaker Orca** (or standard OrcaSlicer).
2. Go to **Print Settings (Process)** → **Others** tab.
3. Scroll down to **Post-processing scripts**.
4. Add the following path:
   ```text
   /Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
