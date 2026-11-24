# Getting started (no technical knowledge needed)

This guide is for you if you've never programmed, never used git and never typed a command into a black window.
You'll do that a few times during setup, but every step tells you exactly what to click or copy. It takes about 20 minutes, plus waiting time.

After setup you don't need any of this again: you start the dashboard with a double-click.

> **What is this?** A training dashboard that runs on **your own computer** and shows your Garmin data with orienteering in mind (time, heart rate, zones and load first). Nothing is uploaded anywhere: your data stays on your computer.

The steps below are for **Windows**. On a Mac, see [On a Mac](#on-a-mac) at the end.

---

## Step 1: Install Python (once)

Python is the free program the dashboard is written in. Your computer needs it to run the dashboard.

1. Go to **https://www.python.org/downloads/** and click the big yellow **Download Python** button.
2. Open the file you downloaded (usually in your *Downloads* folder).
3. **Important**: if the first screen has a checkbox **"Add python.exe to PATH"** at the bottom, **tick it**. Then click **Install Now**.
   If the installer asks other questions, the suggested answer (just press Enter or click the default button) is fine.
4. Wait until it says the installation was successful, then close it.

Already have Python? It must be version 3.12 or newer. The setup in step 3 checks this for you and tells you if it's too old.

---

## Step 2: Download the dashboard

1. Open the GitHub link you got from the person who shared this project.
2. Click the green **Code** button, then **Download ZIP**.
3. Go to your *Downloads* folder, right-click the ZIP file and choose **Extract All...**.
4. Pick a place you'll find again, for example your *Documents* folder, and click **Extract**.

You now have a folder, for example `Documents\garmin-overview-main`. Everything happens in this folder; you can rename it, but **don't move it after setup** (if you do, run step 3 again).

> Inside you might find another folder with the same name. Use the folder that directly contains files like `setup.ps1` and `start_dashboard.bat`.

---

## Step 3: Run the setup (once)

The setup installs what the dashboard needs, connects it to your Garmin account and fetches your first data.

### 3a. Open a command window in the folder

1. Open the dashboard folder in File Explorer (the one with `setup.ps1` in it).
2. Click once in the **address bar** at the top (where the folder path is shown), so the path turns blue.
3. Type `powershell` and press **Enter**.

A blue or black window opens. This is **PowerShell**, a window where you type commands. Don't worry: you only need to paste one line.

### 3b. Start the setup

Copy this line, click in the PowerShell window, paste it with **right-click** (or **Ctrl+V**) and press **Enter**:

```
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

### 3c. Answer the questions

The setup shows what it's doing. Installing takes a few minutes; just wait. Then it asks you a few things:

| It asks | What to do |
|---|---|
| **Garmin email** | Type the email address you use for Garmin Connect and press Enter. |
| **Garmin password** | Type your Garmin password and press Enter. **You won't see anything while you type**, not even dots. That's normal and on purpose. Your password is only sent to Garmin and is **not saved**. |
| **Verification code (MFA)** | Only if you use two-step verification: Garmin emails or texts you a code. Type it in and press Enter. |
| **Fetch the last 30 days now?** | Press **Enter** (= yes). This takes a few minutes. |
| **Connect to the Claude Desktop app?** | Only if you use the Claude app and want to ask it questions about your training. Otherwise type `n` and press Enter. See [Asking Claude](#optional-ask-claude-about-your-training). |
| **Add a 'garmin' command?** | Type `n` and press Enter, unless you like typing commands. You don't need it. |

When you see **Done**, close the window.

**Something went wrong?** Read the red text: it usually says what to do. See also [Problems](#problems). You can always run the setup again; it skips what's already done.

---

## Step 4: Open the dashboard

Double-click **`start_dashboard.bat`** in the dashboard folder.

- A black window opens and, after a few seconds, your web browser shows the dashboard on the **Today** page.
- **Keep the black window open** while you use the dashboard. It *is* the dashboard. Close it when you're done.
- The dashboard is only visible on your own computer (the address is `http://localhost:8501`). Nobody else can open it.

**Tip**: right-click `start_dashboard.bat` → **Send to** → **Desktop (create shortcut)** to start it from your desktop.

The first time, Windows may show a blue warning "Windows protected your PC". Click **More info** → **Run anyway**. This happens because the file came from the internet.

---

## Step 5: Fetch your full history

Setup only fetched the last 30 days. To get all your older training:

1. Open the dashboard (step 4).
2. Click **Sync now** at the bottom of the menu on the left.

Fetching years of data can take **a few hours**, because Garmin only allows a limited number of requests. You can stop any time by closing the black window; the next **Sync now** continues where it stopped.

---

## Daily use

1. Double-click **`start_dashboard.bat`** (or your desktop shortcut).
2. Click **Sync now** in the menu on the left to fetch your latest trainings.
3. Close the black window when you're done.

Things worth doing in the first week:
- **Rename activities** that Garmin called "<City> Running" (Activity page, Name box), e.g. "Middle distance training".
- **Teach it to recognise orienteering**: on the **Tags** page, set the correct tag on at least 8 orienteering sessions and 8 normal runs, then click **Retrain** under *Orienteering detection*. After that it tags new orienteering sessions automatically.
- **Add your races** on the **Plan** page to get a countdown and a taper suggestion.
- **Click the boxes** on the **Today** page: each one explains what the number means.

The [README](README.md) explains every page and feature in detail. You can skip the parts with code in them.

---

## Updating to a new version

When the person who shared this tells you there's a new version:

1. Close the dashboard (close the black window).
2. Download the ZIP again (step 2) and extract it to a temporary place.
3. Copy **everything inside** the new folder into your existing dashboard folder. When Windows asks, choose **Replace the files in the destination**.
   Your data, tags, notes and settings are kept: they're in files that aren't in the download.
4. Run the setup again (step 3). It installs anything new and skips the rest. If it asks for your Garmin login again, that's fine.

---

## Optional: ask Claude about your training

If you use the **Claude Desktop** app (https://claude.ai/download), you can let it read your training data and ask questions like *"How was my last month and what can I do better?"*.

1. Answer **yes** to the Claude question during setup (or run the setup again and answer yes this time).
2. **Fully quit** Claude Desktop: right-click the Claude icon at the bottom right of your screen (near the clock) → **Quit**. Closing the window isn't enough.
3. Start Claude Desktop again. In a new chat, the tools menu below the message box should list **garmin-training**.

Claude can only *read* your training data; it can't change anything and never sees your Garmin password. It only sees data up to your last **Sync now**.

---

## Problems

**"Python 3.12 or newer is required"**
Python isn't installed, or "Add python.exe to PATH" wasn't ticked. Install it again (step 1), **close the PowerShell window**, open a new one (step 3a) and run the setup again.

**"Garmin rejected the login"**
Check your email and password (remember: you don't see the password while typing, so type carefully). Run the setup again to retry.

**"rate-limiting" or "429"**
Garmin is asking you to slow down. Wait an hour and click **Sync now** again; it continues where it stopped.

**"No valid cached login" or "Garmin asks for an MFA code" after clicking Sync now**
Your Garmin login has expired (this happens after a few months). Run the setup again (step 3); it asks for your login once more.

**Double-clicking `start_dashboard.bat` shows an error and the window closes**
The setup hasn't finished successfully yet. Run step 3 again and look for red text.

**The browser doesn't open**
Open your browser yourself and go to **http://localhost:8501** while the black window is open.

**"This site can't be reached" on localhost:8501**
The black window is closed. Start the dashboard again (step 4).

**The numbers look old**
Click **Sync now**, then reload the page (F5).

**A box on the Today page stays empty**
Not every watch measures everything (for example HRV or training readiness). Nothing is wrong.

**Still stuck?** Take a screenshot of the window with the error and send it to the person who shared this project.

---

## On a Mac

1. Install Python from **https://www.python.org/downloads/** (step 1, there's no PATH checkbox on a Mac).
2. Download and extract the ZIP (step 2; double-clicking the ZIP extracts it).
3. Open the **Terminal** app (press **Cmd+Space**, type `Terminal`, press Enter).
4. Type `cd ` (with a space after it), drag the dashboard folder from Finder into the Terminal window, and press Enter.
5. Paste this line and press Enter, then answer the questions as in step 3c:
   ```
   bash setup.sh
   ```
6. To open the dashboard later, do steps 3 and 4 again and paste this line:
   ```
   .venv/bin/python -m streamlit run app/Dashboard.py
   ```
   Keep the Terminal window open while you use the dashboard.

---

## Is my data safe?

- Everything runs on your own computer. The dashboard isn't on the internet.
- Your Garmin password is only used to log in and is **not saved**. Only a login "key" from Garmin is kept, in a hidden folder in your user folder.
- Your training data is in the `data` folder inside the dashboard folder. Delete the dashboard folder and it's gone.
- If you share the dashboard folder with someone, **remove the `data` folder and the `settings.toml` file first**, because they contain your personal data.
