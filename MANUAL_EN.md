# 📖 Snapmaker U1 Spool Tracker — Beginner's Manual

A clear, non-technical guide to setting up and using **Snapmaker U1 Spool Tracker** with your Snapmaker U1 4-toolhead 3D printer.

---

## 🎯 What Problem Does This Solve?

The Snapmaker U1 features 4 independent toolheads. During long multi-color or multi-material prints:
1. If a spool runs out while you are away, the printer enters an indefinite pause.
2. The heated bed automatically cools down after a timeout for safety.
3. As the bed cools, the print contracts, detaches from the plate, and ruins hours of work and material.

**This utility checks filament requirements BEFORE exporting from OrcaSlicer.** If any active spool doesn't have enough material, it stops the export and pops up a clear desktop alert.

---

## 📥 Step 1: Install on macOS

1. Head to the project Releases page and download `SnapmakerSpoolTracker-macOS.zip`.
2. Double-click the downloaded zip to reveal `SnapmakerSpoolTracker.app`.
3. Drag `SnapmakerSpoolTracker.app` into your Mac's **Applications** folder.
4. Launch the application from **Applications**.
5. A four-dot colored icon will appear in the top macOS menu bar next to your clock.

> **💡 Tip:** To automatically launch at system startup:  
> Open *System Settings* → *General* → *Login Items* → click **«+»** and add `SnapmakerSpoolTracker`.

---

## ⚙️ Step 2: Configure Slicer (Snapmaker Orca)

This step only needs to be performed once:

1. Open **Snapmaker Orca** (or standard OrcaSlicer).
2. On the left side under **Process**, turn on the **Advanced** toggle.
3. Switch to the **Others** tab.
4. Scroll all the way down to **Post-processing scripts**.
5. Paste the following line (including the trailing semicolon `;`):
   `/Applications/SnapmakerSpoolTracker.app/Contents/MacOS/SnapmakerSpoolTracker;`
6. Click the small disk icon (Save) next to your process profile and save it under a clear name (e.g. `0.20mm Standard (Spool Tracker)`).

---

## 🎛️ Step 3: Manage Your Spools

1. Click the colored four-dot icon in your top menu bar.
2. Select **"Configure Spools & Slots..."** (or visit `http://127.0.0.1:8765` directly in any web browser).
3. Select your preferred language in the top right corner.

### Adding New Spools:
- Under **"Add New Spool"**, enter Name, Material, and remaining grams.
- Click **"+ Add Spool"**.

### Mapping to Toolheads:
- Under **"Active Slots Configuration"**, select which spool is loaded into each head:
  - **Slot 1** = Toolhead **T0**
  - **Slot 2** = Toolhead **T1**
  - **Slot 3** = Toolhead **T2**
  - **Slot 4** = Toolhead **T3**
- Click **"Save Slot Assignments"**.

---

## 🚀 Step 4: Daily Printing & Alerts

Use OrcaSlicer exactly as you normally do:
1. Slice your 3D model.
2. Click **Export G-code** (or Print).

- **Sufficient filament:** The G-code exports instantly and consumed grams are automatically deducted.
- **Insufficient filament:** The export halts immediately and a native modal pops up on screen showing exact shortfalls and preventing bed cooling failures.

   
