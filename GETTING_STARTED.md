# Getting Started with RealmScape

Welcome to RealmScape! This guide will walk you through everything you need to get the app running — no technical experience required.

---

## What is RealmScape?

RealmScape is a virtual tabletop for TTRPGs. It runs on your computer and shows a map on screen that you and your players can interact with. It includes:

- A map display with a scrolling grid and fog of war
- Tokens for your player characters and monsters
- An initiative tracker and HP / condition tracking
- Area-of-effect templates and a distance measuring tool
- A **GM panel** — a webpage that opens in any browser (phone, tablet, or second monitor) so you can control the game without touching the main screen
- Background music via Spotify or Tabletop Audio
- Scene portals, hidden items, traps, and dungeon generation

---

## Before You Begin — What You'll Need

### 1. A Computer Running Windows or Linux
RealmScape works on both. Mac is not currently supported because I don't have one to test on.

### 2. Python 3.10, 3.11, or 3.12
Python is the programming language RealmScape is built with. You need a specific version:

> ⚠️ **Important:** Python **3.13 will not work due to a recently added feature**. You must install version **3.10, 3.11, or 3.12**.

**To check if you already have Python installed:**
- On Windows: open the Start menu, search for **Command Prompt**, open it, and type `python --version` then press Enter.
- On Linux: open a Terminal and type `python3 --version` then press Enter.

If it shows a version between 3.10 and 3.12 (e.g. `Python 3.12.4`), you're all set. If it shows 3.13 or higher, or Python isn't found, follow the steps below.

**To install Python 3.12:**
1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Look for the latest **3.12.x** release and click its download link
3. Run the installer
4. **On Windows:** on the first screen of the installer, check the box that says **"Add Python to PATH"** — this is important!
5. Click Install Now and wait for it to finish

---

## Step 1 — Download RealmScape

1. Go to [github.com/coolfuton8/RealmScape](https://github.com/coolfuton8/RealmScape)
2. Click the green **Code** button near the top right
3. Click **Download ZIP**
4. Once downloaded, find the ZIP file (usually in your Downloads folder), right-click it, and choose **Extract All** (Windows) or double-click to unzip (Linux)
5. Move the extracted `RealmScape` folder somewhere convenient — your Desktop or Documents folder works fine

---

## Step 2 — Install Dependencies (semi-automated)

Dependencies are the extra software packages RealmScape needs to run. There is an installer script that handles all of this automatically.

### On Windows

1. Open the `RealmScape` folder
2. Double-click **`install.bat`**
3. A black window will appear and you'll see text scrolling by — this is normal
4. Wait until you see **"Installation complete!"**
5. Press any key to close the window

### On Linux

1. Open a Terminal
2. Navigate to the RealmScape folder. For example, if you put it on your Desktop:
   ```
   cd ~/Desktop/RealmScape
   ```
3. Make the installer executable and run it:
   ```
   chmod +x install.sh
   ./install.sh
   ```
4. Wait until you see **"Installation complete!"**

> If you see any red error messages during installation, the most common cause is having Python 3.13 installed. Install Python 3.12 from python.org and try again.

---

## Step 3 — Start RealmScape

### On Windows

Double-click **`run.bat`** in the RealmScape folder.

### On Linux

Open a Terminal in the RealmScape folder and run:
```
./run.sh
```

A window will open showing a map with some starter tokens on it. You'll also see a message in the title bar like:

```
RealmScape — default  |  GM Panel: http://192.168.1.10:5000
```

That address is your **DM Panel** — more on that below.

---

## Step 4 — Open the DM Panel (Optional but Recommended)

The DM Panel is a webpage you can open on any device connected to the same Wi-Fi network — a phone, tablet, laptop, or a second monitor. It lets you control the game without reaching over to the main screen.

1. Look at the title bar of the RealmScape window — it shows an address like `http://192.168.1.10:5000`
2. On any device on the same Wi-Fi, open a web browser and go to that address
3. You'll see the DM Panel where you can control initiative, HP, scenes, music, and more

By default there's no login — anyone on your network who opens that address gets straight in. A
campaign is only PIN-protected once you set a PIN for it via the panel's "Save" (export) feature;
see the full manual's "Campaign PINs" section for details.

> If you're only using one computer and don't need a second device, you can also open the DM Panel on the same machine at `http://localhost:5000`.

---

## Your First Session

When RealmScape opens you'll see:

- **Three starter tokens** on the map (Fighter, Wizard, Rogue) — you can rename, recolour, and customize these to match your party
- **A toolbar** across the top with buttons for adding enemies, rolling initiative, toggling fog of war, and more
- **Right-click anywhere on the map** to open a menu for adding enemies, placing scene markers, and more

### Loading a Map Image

RealmScape starts with a plain grey background. To load your own map:

1. Right-click the map area
2. Choose **Scene → Set Background Image** from the toolbar (the image icon)
3. Browse to any `.jpg` or `.png` map file on your computer and select it

---

## Optional — Spotify Integration

If you want background music to play automatically through Spotify when players enter different areas of the map:

1. You need a **Spotify Premium** account (the Spotify Web API requires Premium for playback control)
2. Open the DM Panel in your browser and go to `http://localhost:5000/spotify-setup`
3. Follow the on-screen instructions — you'll need to create a free app at the Spotify Developer Dashboard to get a Client ID and Secret
4. Once connected, you can assign Spotify playlist or track links to sound zones on your map

---

## Optional — Hotspot Mode (for Tablets Without Wi-Fi)

If you want to use a tablet as a player view or DM panel but don't have a local Wi-Fi network, RealmScape can create its own private hotspot on your computer.

### On Windows (requires Administrator)

Double-click **`run_hotspot.bat`** — it will ask for Administrator permission, which is required to create a network hotspot. Once running, the SSID, password, and URL will appear on screen so players can connect.

### On Linux

```
chmod +x run_hotspot.sh
sudo ./run_hotspot.sh
```

---

## Privacy

Each time RealmScape starts, it sends a small anonymous "app launched" event (a random per-install id, the app version, and your OS) so the developer can see aggregate usage across installs. No campaign data, names, or other personal content is ever sent. To disable this entirely, set the environment variable `REALMSCAPE_TELEMETRY=0` before launching.

---

## Troubleshooting

**"Python was not found" or the installer closes immediately**
Make sure Python 3.10–3.12 is installed and that you checked "Add Python to PATH" during installation. Then try running `install.bat` again.

**The app opens but the window is blank or black**
This can happen on Linux with certain graphics drivers. The app automatically uses a software renderer on Linux — try restarting. If the problem persists, make sure your SDL2 system libraries are installed: `sudo apt install libsdl2-2.0-0`.

**The DM Panel says "Not authenticated" or won't load**
Make sure your other device is on the same Wi-Fi network as the computer running RealmScape. Also check that your firewall isn't blocking port 5000.

**Port 5000 is already in use**
Another app on your computer is using port 5000. On Linux, `run.sh` automatically clears this. On Windows, restart your computer and try again, or close any other apps that might use port 5000 (other local web servers, for example).

---

## Getting Help

The full user manual is available inside the app at `http://localhost:5000/manual` once RealmScape is running.
