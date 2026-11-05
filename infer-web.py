import os
import sys
import glob
import shutil
import threading
from datetime import datetime
import numpy as np
import sounddevice as sd
import soundfile as sf
import gradio as gr

# Pfade definieren
ENGINE_DIR = os.getcwd()
APPLIO_DIR = r"C:\Users\User\Downloads\ApplioV3.7.1"
FFMPEG_BIN_DIR = r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine"
MODELS_DIR = os.path.join(ENGINE_DIR, "assets", "models")
APPLIO_MODELS_DIR = os.path.join(APPLIO_DIR, "rvc", "models")
RECORDINGS_DIR = os.path.join(ENGINE_DIR, "assets", "recordings")
BACKUP_DIR = r"C:\Backups"

if os.path.exists(FFMPEG_BIN_DIR):
    os.environ["PATH"] += os.pathsep + FFMPEG_BIN_DIR
    print(f"?? FFmpeg & FFprobe Pfad registriert: {FFMPEG_BIN_DIR}")

def inject_applio_paths():
    """Injiziert die Applio-Pfade stabil in das laufende Python-System."""
    if os.path.exists(APPLIO_DIR):
        if APPLIO_DIR not in sys.path:
            sys.path.insert(0, os.path.join(APPLIO_DIR, "src"))
            sys.path.insert(0, APPLIO_DIR)

            applio_venv_packages = os.path.join(APPLIO_DIR, ".venv", "Lib", "site-packages")
            if os.path.exists(applio_venv_packages):
                sys.path.insert(0, applio_venv_packages)
            os.environ["CUSTOM_APPLIO_PATH"] = APPLIO_DIR

# Initiale Injektion für den Hauptthread
inject_applio_paths()

# Globale Kontrollvariablen für Live-Inferenz und Recording
live_streaming = False
live_thread = None
current_live_vc = None
current_live_model_path = ""

is_recording = False
recorded_blocks = []
current_live_vu_level = -60.0
last_recorded_file = None

# Daten-Arrays für den WebformVisualizer im Frontend (per State simuliert)
vocal_waveform_data = [0.0] * 50
bgm_waveform_data = [0.0] * 50

# Definition der Presets
STUDIO_PRESETS = {
    "Standard (Manuell)": {
        "vocal_gain": 0.0, "noise_red": 0, "gate_thresh": -50, "gate_release": 150,
        "comp_thresh": -20, "comp_ratio": 3.5, "comp_attack": 15, "comp_release": 200,
        "eq_low": 0, "eq_mid": 2, "eq_high": 1, "echo_time": 0.3, "echo_fb": 30,
        "reverb_size": 0.5, "fx_mix": 15
    },
    "Radio-Stimme (Fat Voice)": {
        "vocal_gain": 4.0, "noise_red": 40, "gate_thresh": -45, "gate_release": 120,
        "comp_thresh": -24, "comp_ratio": 5.0, "comp_attack": 10, "comp_release": 150,
        "eq_low": 6, "eq_mid": -1, "eq_high": 4, "echo_time": 0.2, "echo_fb": 15,
        "reverb_size": 0.3, "fx_mix": 20
    },
    "Podcast (Warm & Nah)": {
        "vocal_gain": 3.0, "noise_red": 60, "gate_thresh": -48, "gate_release": 200,
        "comp_thresh": -18, "comp_ratio": 3.0, "comp_attack": 20, "comp_release": 250,
        "eq_low": 4, "eq_mid": 3, "eq_high": 0, "echo_time": 0.0, "echo_fb": 0,
        "reverb_size": 0.1, "fx_mix": 5
    },
    "Clear Vocal (Kristallklar)": {
        "vocal_gain": 2.0, "noise_red": 30, "gate_thresh": -52, "gate_release": 100,
        "comp_thresh": -15, "comp_ratio": 2.5, "comp_attack": 8, "comp_release": 100,
        "eq_low": -3, "eq_mid": 1, "eq_high": 6, "echo_time": 0.4, "echo_fb": 25,
        "reverb_size": 0.6, "fx_mix": 25
    }
}

def get_audio_devices():
    """Scannt die System-Hardware nach Audio-Geräten."""
    try:
        devices = sd.query_devices()
        input_devs = []
        output_devs = []
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                input_devs.append(f"{i}: {dev['name']}")
            if dev['max_output_channels'] > 0:
                output_devs.append(f"{i}: {dev['name']}")

        default_in = f"{sd.default.device}: {devices[sd.default.device]['name']}" if sd.default.device >= 0 else None
        default_out = f"{sd.default.device}: {devices[sd.default.device]['name']}" if sd.default.device >= 0 else None
