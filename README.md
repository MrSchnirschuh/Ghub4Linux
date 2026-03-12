# Ghub4Linux

Logitech Ghub on Linux with DPI Feature, Macros and App Profiles.

A GTK4/libadwaita application that lets you configure your Logitech mouse on Linux
(DPI settings, macro key bindings, and per-application profiles).

---

## Installation

### Quick install (all distributions)

The `install.sh` script installs the Python package **and** registers the
application so it appears in your desktop environment's application menu
(GNOME, KDE, XFCE, …).

```bash
git clone https://github.com/MrSchnirschuh/Ghub4Linux.git
cd Ghub4Linux
```

Install system dependencies first (see the distribution-specific sections below), then run **one** of the following:

```bash
bash install.sh          # installs for the current user (no root needed)
```

```bash
bash install.sh --system # installs system-wide (requires sudo)
```

After that you can start Ghub4Linux from your application launcher **or** from
a terminal:

```bash
ghub4linux
```

> **Note:** If the `ghub4linux` command is not found after installation, add
> `~/.local/bin` to your PATH by adding this line to your shell profile
> (`~/.bashrc`, `~/.zshrc`, `~/.config/fish/config.fish`, …):
>
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

---

### Step-by-step: Arch Linux / CachyOS

#### 1. Install system dependencies

```bash
sudo pacman -S python python-gobject python-pydantic gtk4 libadwaita hidapi
```

#### 2. Clone the repository

```bash
git clone https://github.com/MrSchnirschuh/Ghub4Linux.git
cd Ghub4Linux
```

#### 3. Install (package + desktop entry + icon)

```bash
bash install.sh
```

> `install.sh` automatically creates a virtual environment at
> `~/.local/share/ghub4linux/venv` and installs the package there, so no
> manual `python -m venv` step is needed.

---

### Step-by-step: Ubuntu / Debian

#### 1. Install system dependencies

```bash
sudo apt install \
    python3 python3-venv python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    libhidapi-hidraw0 python3-pydantic
```

#### 2. Clone the repository

```bash
git clone https://github.com/MrSchnirschuh/Ghub4Linux.git
cd Ghub4Linux
```

#### 3. Install (package + desktop entry + icon)

```bash
bash install.sh
```

> `install.sh` automatically creates a virtual environment at
> `~/.local/share/ghub4linux/venv` and installs the package there, so no
> manual `python3 -m venv` step is needed.

---

## udev rules (HID access without root)

By default, HID devices are only accessible by root.
Create the following udev rule to allow your user to access Logitech devices:

```bash
sudo tee /etc/udev/rules.d/99-logitech-hid.rules <<'EOF'
# Logitech HID devices
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0660", GROUP="input"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

Add your user to the `input` group if not already a member:

```bash
sudo usermod -aG input $USER
# Log out and back in for the group change to take effect
```

---

## Project structure

```
Ghub4Linux/
├── install.sh              # One-command install + desktop registration
├── pyproject.toml          # Project definition & dependencies
├── README.md
├── data/
│   ├── com.github.mrschnirschuh.ghub4linux.desktop  # Desktop entry
│   └── icons/hicolor/scalable/apps/
│       └── com.github.mrschnirschuh.ghub4linux.svg  # Application icon
└── src/
    └── ghub4linux/
        ├── __init__.py     # Package metadata
        ├── __main__.py     # Entry point (main())
        └── app.py          # GTK4/Adwaita application
```

## License

MIT

