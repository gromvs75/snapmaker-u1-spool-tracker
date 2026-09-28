# Snapmaker U1 Spool Tracker 🎯

![macOS Version](https://img.shields.io/badge/platform-macOS%2012%2B-blue)
![Architecture](https://img.shields.io/badge/arch-Apple%20Silicon%20%7C%20Intel-lightgrey)
![OrcaSlicer Compatibility](https://img.shields.io/badge/OrcaSlicer-v2.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-informational)
![Languages](https://img.shields.io/badge/i18n-EN%20%7C%20RU%20%7C%20DE%20%7C%20UK%20%7C%20ES-orange)

An intelligent filament inventory management suite and print runout prevention hook engineered specifically for the **Snapmaker U1 Toolchanger 3D printer** and **OrcaSlicer / Snapmaker Orca**.

---

## 💡 The Problem

The **Snapmaker U1** is an advanced multi-toolhead 3D printer featuring 4 discrete toolchangers (T0–T3). When running long, multi-material, or multi-color prints, running out of filament mid-job causes the printer to pause indefinitely.

When a print pauses unattended:
1. The heated print bed turns off or times out to prevent thermal runaway.
2. The model cools, contracts, and detaches from the build plate (PEI/textured bed).
3. Resuming the print causes layer shifts, print head collisions, or total job failure.

**Snapmaker U1 Spool Tracker** eliminates this risk by performing pre-export G-code inspection directly within your slicing workflow.

---

## ✨ Key Features

- **Automated G-code Interception**: Hooks into OrcaSlicer post-processing pipeline. It calculates required filament weight (including purge tower and tool change waste) across all 4 toolheads before saving or sending the job.
- **Bed-Cooling Runout Protection**: If any assigned spool lacks sufficient filament, an immediate, native macOS alert dialog pops up, preventing silent job failures.
- **Single-Click Export Cancellation**: Users can cleanly abort the export directly from the OS-level alert (`Cancel Export`) to swap spools, or choose `Proceed Anyway`.
- **4-Toolhead Slot Mapping**: Intuitive local web dashboard (`http://127.0.0.1:8765`) to dynamically link physical spools to Toolheads T0 through T3.
- **Native macOS Menu Bar Integration**: Displays current filament levels and active slots from your menu bar using a low-footprint background daemon.
- **Zero-Dependency Standalone Bundle**: Packaged into a standalone `.app` bundle—no manual Python runtime or virtual environment setup required for end users.
- **Internationalization (i18n)**: Full native localization across the web interface, menu bar, and macOS warning dialogues:
  - 🇬🇧 English (`EN`)
  - 🇷🇺 Русский (`RU`)
  - 🇩🇪 Deutsch (`DE`)
  - 🇺🇦 Українська (`UK`)
  - 🇪🇸 Español (`ES`)

---

## 🏗️ Architecture & How It Works

```
┌─────────────────┐       Slices & Exports      ┌───────────────────────────┐
│   OrcaSlicer    │ ──────────────────────────> │   SnapmakerSpoolTracker   │
│ (Snapmaker U1)  │                             │      (CLI Hook Mode)      │
└─────────────────┘                             └─────────────┬─────────────┘
                                                              │
                    Parses `; filament used [g] = w0, w1, w2, w3`
                                                              │
                                                              ▼
                                                ┌───────────────────────────┐
                                                │    Check Inventory DB     │
                                                │     (spools_u1.json)      │
                                                └─────────────┬─────────────┘
                                                              │
                     ┌────────────────────────────────────────┴────────────────────────────────────────┐
                     ▼                                                                                 ▼
             [Sufficient Weight]                                                              [Deficit Detected]
                     │                                                                                 │
       Deducts weight from slots                                                         Native macOS Dialog (Applescript)
                     │                                                                                 │
          Exports cleanly (Exit 0)                                                    ┌────────────────┴────────────────┐
                                                                                      ▼                                 ▼
                                                                             [Cancel Export]                   [Proceed Anyway]
                                                                                      │                                 │
                                                                           Aborts Slicer Export               Deducts & Continues
```

---

## 🚀 Installation

### Option 1: Standalone macOS App (Recommended)

1. Download the latest `SnapmakerSpoolTracker-macOS.zip` from the [Releases](../../releases) section.
2. Unzip and drag `SnapmakerSpoolTracker.app` into your `/Applications` folder.
3. Open `SnapmakerSpoolTracker.app`. The spool icon will appear in your top menu bar.
4. *(Optional)* Add the app to **System Settings > General > Login Items** to have it run quietly in the background on startup.

### Option 2: Run from Source / Developer Setup

```bash
git clone https://github.com/your-username/snapmaker-u1-spool-tracker.git
cd snapmaker-u1-spool-tracker

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the background daemon and tray app
python spool_tracker.py
```

---

## ⚙️ OrcaSlicer Configuration

To connect OrcaSlicer with the tracker:

1. Open **Snapmaker Orca** (or standard **OrcaSlicer**).
2. Under **Process Profile** (Профиль процесса), enable the **Advanced** (Расширенный) toggle.
3. Navigate to the **Others** (Прочее) tab.
4. Scroll down to the **Post-processing scripts** (Скрипты постобработки) field.
5. Enter the path to the tracker executable followed by a semicolon:

   **For Standalone `.app` Users:**
   ```text
   /Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;
   ```

   **For Source / Development Users:**
   ```text
   /Users/<your_username>/snapmaker-tracker/run_hook.sh;
   ```

6. Click the **Save preset icon (floppy disk)** next to the Process Profile name and save it as:
   ```text
   0.24mm Standard @Snapmaker U1 (Spool Tracker)
   ```

> **Note**: Whenever you slice models with this profile selected, filament usage across T0–T3 will be automatically monitored on export.

---

## 🖥️ Web Management Dashboard

Access the inventory dashboard anytime at **`http://127.0.0.1:8765`** (or select **"Configure Spools & Slots..."** from the macOS menu bar icon).

### Management Capabilities:
- **Slot Assignment**: Map any spool in your database to Toolhead 1 (T0), Toolhead 2 (T1), Toolhead 3 (T2), or Toolhead 4 (T3).
- **Spool Library**: Create custom spools with material designations (PLA, PETG, ABS, TPU, Support PVA) and initial net weights.
- **Real-Time Corrections**: Modify remaining weights manually after spool rewinds or partial print recoveries.
- **Language Switcher**: Dynamically toggle between English, Russian, German, Ukrainian, and Spanish.

---

## 📦 Building from Source (PyInstaller)

To compile the standalone macOS application bundle yourself:

```bash
# Generate the multi-resolution macOS .icns icon
python3 generate_icon.py

# Build the bundle
pyinstaller --noconfirm --onedir --windowed \
  --name "SnapmakerSpoolTracker" \
  --icon "AppIcon.icns" \
  --osx-bundle-identifier "com.community.snapmaker-u1-tracker" \
  spool_tracker.py

# Move to Applications
cp -r dist/SnapmakerSpoolTracker.app /Applications/
```

---

## 🤝 Contributing & Community

Contributions are warmly welcomed! If you are interested in expanding support:
- Adding native support for Windows / Linux notifications.
- Adding additional language localizations.
- Integrating direct Moonraker / Klipper API queries for real-time print telemetry.

Feel free to open an **Issue** or submit a **Pull Request**.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.