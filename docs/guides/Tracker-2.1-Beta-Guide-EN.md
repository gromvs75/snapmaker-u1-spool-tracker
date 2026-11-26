# Snapmaker U1 Spool Tracker 2.1.1 beta setup

Tracker keeps balances for the spools on T0–T3 and records usage in History. For a print started from Snapmaker Space on your phone, Tracker can read the job file from the U1, show estimates by toolhead while it prints, and record verified usage when the job finishes. **Connect Tracker to the U1 before starting the print. Keep the computer on and awake and leave Tracker running and connected until the print finishes.**

## 1. Install the beta

1. On the [release page](https://github.com/gromvs75/snapmaker-u1-spool-tracker/releases/tag/v2.1.1-beta.1), download the ZIP for Windows x64 or macOS Apple Silicon (M1 and later).
2. If you already use Tracker, export a backup in your current version and quit it from the tray or menu bar. Extract the beta to a separate folder and use one instance of Tracker per printer. The beta uses a separate data folder from 1.x and shares its data folder with earlier 2.1 previews.
3. On Windows, extract the whole archive, keep `_internal` next to the EXE, and run `Snapmaker-Tracker-2.1-Candidate.exe`. The window requires Microsoft Edge WebView2 Runtime. On Mac, open the extracted `Snapmaker-Tracker-2.1-Candidate.app`. Both packages show `2.1.1-beta.1` in the title.

The Windows interface and accounting were checked in WebView2 on a simulator. A physical U1 test on Windows is pending.

## 2. Connect the U1 and assign spools

1. Put the computer and U1 on the same local network. Find the U1's IP address in its network settings.
2. In Tracker, click **Add printer**. Enter a name and the U1's IP in **Moonraker address**. Use port `7125` unless you changed it. Save, then click **Connect printers**. Check the connection status in **Overview**. After restarting Tracker, connect again.
3. With the printer idle, go to **Spools → Library** and add your spools with their remaining filament in grams. Under **Overview → Assignments**, choose the spool physically installed on each used toolhead, then click **Confirm positions**. Manual assignments work on stock U1 firmware without RFID tags or a printer add-on.
4. When you move or replace spools, or Tracker asks you to check the assignments again, confirm the physical positions with the printer idle.

## 3. Try a print from Snapmaker Space

1. Note the spool balances in **Overview**. Keep Tracker running and connected. Start a short print on the same U1 from Snapmaker Space on your phone. You can leave Snapmaker Orca closed. This workflow requires no desktop slicing or post-processing script.
2. Once Tracker gets the G-code and verifies the toolhead mapping, the used cards show a **G-code estimate** and the expected balance after the job. Check **Details** on the current print if the estimate does not appear.
3. After the print finishes, check **History** and compare the accounted grams with the change in the spool balances. The recorded usage can differ slightly from the G-code estimate. An interrupted connection or missing evidence can send a job to manual review. If usage has already been recorded, avoid entering it again.

## 4. Add plate numbers to your Snapmaker Orca printer preset

Do this once in each printer preset you use for local slicing previews.

1. In Snapmaker Orca, click the edit icon next to the selected **printer preset**.
2. Open **Machine G-code → Machine start G-code**. Paste this line **at the very top**, above the existing code.

   ```gcode
   ; TRACKER_BED_V1 = {plate_number}
   ```

3. Keep the leading semicolon, braces and existing code. Add the comment once. Orca fills in the plate number when it slices. The process preset's **Post-processing scripts** field is separate.
4. Save a separate printer preset, for example **Snapmaker U1 · Tracker**. **Select that preset in the open project**, then slice the plates again. Check the selected preset whenever you open a 3MF, since the project may provide its own printer settings.
5. In Tracker, open **Overview → Slice forecast** and compare the plate number and grams with Orca. A finished slice is enough for this check. You can leave the print unstarted.

If the plate is unknown, verify the comment in the preset actually selected in the project and slice again. Existing G-code keeps its original metadata. For diagnosis, export the file and look for a line such as `; TRACKER_BED_V1 = 02` near the start of the G-code body.

### If you already use an export script

Normal slicing previews and phone-started accounting work without an export script. If you use Tracker's optional export check, go to **Process → Others → Post-processing scripts** and replace the existing Tracker command with one pointing to this beta. Use the actual path and keep the trailing semicolon.

```text
"C:\Tools\Snapmaker-Tracker-2.1-Candidate\Snapmaker-Tracker-2.1-Candidate.exe";
```

```text
"/Applications/Snapmaker-Tracker-2.1-Candidate.app/Contents/MacOS/Snapmaker-Tracker-2.1-Candidate";
```

## 5. Check the forecast before printing

On Windows and macOS, open **Overview → Slice forecast** after slicing. Compare the plate and grams with Orca. When Tracker estimates the spool by color and material type, treat that assignment as provisional. Choose the actual toolheads in Orca's **Print Preprocessing** window. The forecast helps you check whether there is enough filament with the reserve. Check **History** for recorded usage after the print.

### Forecast from selected toolheads on Mac

The Mac beta `2.1.1-beta.1` can read live **Print Preprocessing** assignments in Snapmaker Orca 2.4.1. On Windows, use the regular slice forecast and check the selected toolheads in Orca before starting. Once printing begins, Tracker uses the mapping verified by the printer for the current-print estimate and accounting.

1. On Mac, open **System Settings → Privacy & Security**. On macOS 27.2.1, choose **Device Control and Data Access**. If your version shows **Accessibility** in the list, open that panel.
2. Click **+**, choose the installed `Snapmaker-Tracker-2.1-Candidate.app`, usually in **Applications**, and turn on access. Tracker uses this permission to read the selected toolheads in the Orca window. [Apple's accessibility permission guide](https://support.apple.com/guide/mac-help/allow-accessibility-apps-to-access-your-mac-mh43185/mac)
3. Check that the printer has the same name in Tracker and Orca. Slice a model and open **Print Preprocessing**. With Orca in front, change the toolhead for one of the materials. The Tracker menu opens with the Orca assignment forecast, and the estimated grams move to the selected toolhead card without comparing colors. For a mix, Tracker shows the usage of each component. For example, if the second component needs 21.44 g, choosing toolhead 4 moves that estimate to T3. You can check this before starting the print.

If access is missing, Slice forecast and the Tracker menu show a macOS permission reminder.

#### If the forecast still shows the previous toolhead after an update

Even when the switch is on, macOS may still associate the permission with the previous test build's signature. After you choose a new toolhead in Orca, Tracker may still show its color-and-type forecast and the estimated usage on the previous spool.

1. In the same System Settings panel, select the old permission entry for `Snapmaker-Tracker-2.1-Candidate` and click **−**.
2. Click **+**, add the exact copy of `Snapmaker-Tracker-2.1-Candidate.app` you are running, and turn on its switch.
3. Return to **Print Preprocessing** and change the toolhead again. Check the forecast source and the grams on the selected toolhead. If Tracker still shows the color-and-type forecast, quit it from the menu bar and reopen that same copy of the app.

## If you use Spoolman

Spoolman runs separately. In **Settings → Spoolman**, enter your server address, start with catalog read mode and verify the linked physical spools. Enable usage delivery only if this instance is the sole sender for that printer. After a print, refresh the catalog and compare the balances in Overview with Spoolman. [Integration guide](https://github.com/gromvs75/snapmaker-u1-spool-tracker/blob/v2.1.1-beta.1/docs/guides/spoolman-preview-en.md)

When reporting an issue, include your Tracker version, OS, U1 firmware, how you started the print, a screenshot of the cards during the job and the History entry after it finished. For slicer issues, include the Orca version and plate number. [Report an issue on GitHub](https://github.com/gromvs75/snapmaker-u1-spool-tracker/issues/new)
