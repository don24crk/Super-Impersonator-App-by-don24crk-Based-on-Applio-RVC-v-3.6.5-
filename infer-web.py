import glob
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

import gradio as gr
import numpy as np
import sounddevice as sd
import soundfile as sf


# Pfade
ENGINE_DIR = Path.cwd()
APPLIO_DIR = Path(r"C:\Users\User\Downloads\ApplioV3.7.1")
FFMPEG_BIN_DIR = Path(
    r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine"
)

MODELS_DIR = ENGINE_DIR / "assets" / "models"
APPLIO_MODELS_DIR = APPLIO_DIR / "rvc" / "models"
RECORDINGS_DIR = ENGINE_DIR / "assets" / "recordings"
TEMP_DIR = ENGINE_DIR / "assets" / "temp"

if FFMPEG_BIN_DIR.is_dir():
    os.environ["PATH"] = (
        os.environ.get("PATH", "") + os.pathsep + str(FFMPEG_BIN_DIR)
    )
    print(f"🟢 FFmpeg & FFprobe Pfad registriert: {FFMPEG_BIN_DIR}")


def inject_applio_paths():
    """Fügt Applio-Verzeichnisse dem Importpfad hinzu."""
    if not APPLIO_DIR.is_dir():
        return

    paths = [
        APPLIO_DIR / ".venv" / "Lib" / "site-packages",
        APPLIO_DIR,
        APPLIO_DIR / "src",
    ]
    for path in reversed(paths):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))

    os.environ["CUSTOM_APPLIO_PATH"] = str(APPLIO_DIR)


inject_applio_paths()

# Gemeinsamer Zustand für Live-Inferenz und Aufnahme
state_lock = threading.Lock()
live_streaming = False
live_thread = None
current_live_vc = None
current_live_model_path = ""
is_recording = False
recorded_blocks = []
current_live_vu_level = -60.0
last_recorded_file = None


STUDIO_PRESETS = {
    "Standard (Manuell)": {
        "vocal_gain": 0.0, "noise_red": 0, "gate_thresh": -50,
        "gate_release": 150, "comp_thresh": -20, "comp_ratio": 3.5,
        "comp_attack": 15, "comp_release": 200, "eq_low": 0,
        "eq_mid": 2, "eq_high": 1, "echo_time": 0.3, "echo_fb": 30,
        "reverb_size": 0.5, "fx_mix": 15,
    },
    "Radio-Stimme (Fat Voice)": {
        "vocal_gain": 4.0, "noise_red": 40, "gate_thresh": -45,
        "gate_release": 120, "comp_thresh": -24, "comp_ratio": 5.0,
        "comp_attack": 10, "comp_release": 150, "eq_low": 6,
        "eq_mid": -1, "eq_high": 4, "echo_time": 0.2, "echo_fb": 15,
        "reverb_size": 0.3, "fx_mix": 20,
    },
    "Podcast (Warm & Nah)": {
        "vocal_gain": 3.0, "noise_red": 60, "gate_thresh": -48,
        "gate_release": 200, "comp_thresh": -18, "comp_ratio": 3.0,
        "comp_attack": 20, "comp_release": 250, "eq_low": 4,
        "eq_mid": 3, "eq_high": 0, "echo_time": 0.0, "echo_fb": 0,
        "reverb_size": 0.1, "fx_mix": 5,
    },
    "Clear Vocal (Kristallklar)": {
        "vocal_gain": 2.0, "noise_red": 30, "gate_thresh": -52,
        "gate_release": 100, "comp_thresh": -15, "comp_ratio": 2.5,
        "comp_attack": 8, "comp_release": 100, "eq_low": -3,
        "eq_mid": 1, "eq_high": 6, "echo_time": 0.4, "echo_fb": 25,
        "reverb_size": 0.6, "fx_mix": 25,
    },
}


def get_audio_devices():
    """Liefert Eingangs- und Ausgangsgeräte sowie die Standardgeräte."""
    try:
        devices = sd.query_devices()
        input_devices = [
            f"{i}: {device['name']}"
            for i, device in enumerate(devices)
            if device["max_input_channels"] > 0
        ]
        output_devices = [
            f"{i}: {device['name']}"
            for i, device in enumerate(devices)
            if device["max_output_channels"] > 0
        ]

        defaults = sd.default.device
        default_input = None
        default_output = None

        if defaults[0] is not None and 0 <= defaults[0] < len(devices):
            if devices[defaults[0]]["max_input_channels"] > 0:
                default_input = f"{defaults[0]}: {devices[defaults[0]]['name']}"

        if defaults[1] is not None and 0 <= defaults[1] < len(devices):
            if devices[defaults[1]]["max_output_channels"] > 0:
                default_output = f"{defaults[1]}: {devices[defaults[1]]['name']}"

        return input_devices, output_devices, default_input, default_output
    except Exception as exc:
        print(f"⚠️ Fehler beim Abrufen der Audiogeräte: {exc}")
        return [], [], None, None


def scan_rvc_models():
    """Durchsucht die Engine- und Applio-Modellverzeichnisse nach .pth-Dateien."""
    models = set()

    for base_dir in (MODELS_DIR, APPLIO_MODELS_DIR):
        if not base_dir.is_dir():
            continue

        for model_path in base_dir.rglob("*.pth"):
            models.add(model_path.relative_to(base_dir).as_posix())

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(models)


def get_dropdown_data():
    models = scan_rvc_models()
    if not models:
        message = "Keine Modelle in assets/models/ gefunden"
        return [message], message
    return models, models[0]


def refresh_models():
    choices, default_value = get_dropdown_data()
    return gr.Dropdown(choices=choices, value=default_value)


def find_model_path(model_rel_path):
    """Findet ein Modell in einem der unterstützten Modellverzeichnisse."""
    relative_path = Path(model_rel_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Ungültiger Modellpfad.")

    for base_dir in (MODELS_DIR, APPLIO_MODELS_DIR):
        candidate = base_dir / relative_path
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(f"Modell nicht gefunden: {model_rel_path}")


def find_associated_index(model_rel_path):
    """Sucht eine passende oder ersatzweise eine .index-Datei."""
    try:
        model_path = find_model_path(model_rel_path)
    except (ValueError, FileNotFoundError):
        return ""

    exact_match = model_path.with_suffix(".index")
    if exact_match.is_file():
        return str(exact_match)

    fallback_matches = sorted(model_path.parent.glob("*.index"))
    return str(fallback_matches[0]) if fallback_matches else ""


def update_hop_visibility(f0_method):
    return gr.Dropdown(visible="crepe" in (f0_method or "").lower())


def load_preset_values(preset_name):
    """Liefert die Werte eines ausgewählten Studio-Presets."""
    preset = STUDIO_PRESETS.get(preset_name)
    if preset is None:
        return [gr.update() for _ in range(15)]

    keys = (
        "vocal_gain", "noise_red", "gate_thresh", "gate_release",
        "comp_thresh", "comp_ratio", "comp_attack", "comp_release",
        "eq_low", "eq_mid", "eq_high", "echo_time", "echo_fb",
        "reverb_size", "fx_mix",
    )
    return [preset[key] for key in keys]


def convert_codec(input_wav, target_codec, mp3_bitrate=320, output_dir=None):
    """Konvertiert eine WAV-Datei und gibt bei Fehlern ein WAV-Backup aus."""
    ext = str(target_codec).lower()
    if ext not in {"wav", "mp3", "flac", "wma", "vob"}:
        raise ValueError(f"Nicht unterstützter Codec: {target_codec}")

    base_dir = Path(output_dir) if output_dir else ENGINE_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    prefix = "live_rec" if base_dir.resolve() == RECORDINGS_DIR.resolve() else "master_bounce"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = base_dir / f"{prefix}_{timestamp}.{ext}"

    if ext == "wav":
        shutil.copy2(input_wav, output_path)
        return str(output_path)

    try:
        from pydub import AudioSegment

        ffmpeg_exe = FFMPEG_BIN_DIR / "ffmpeg.exe"
        if ffmpeg_exe.is_file():
            AudioSegment.converter = str(ffmpeg_exe)

        audio = AudioSegment.from_wav(input_wav)
        export_kwargs = {}
        if ext == "mp3":
            export_kwargs["bitrate"] = f"{int(mp3_bitrate)}k"

        audio.export(output_path, format=ext, **export_kwargs)
        return str(output_path)
    except Exception as exc:
        print(f"⚠️ Codec-Konvertierung fehlgeschlagen ({exc}). Gebe WAV-Backup aus.")
        fallback_path = base_dir / f"{prefix}_{timestamp}_fallback.wav"
        shutil.copy2(input_wav, fallback_path)
        return str(fallback_path)


def create_studio_board(
    vocal_gain, noise_red, gate_thresh, gate_release, comp_thresh, comp_ratio,
    comp_attack, comp_release, eq_low, eq_mid, eq_high, echo_time, echo_fb,
    reverb_size, fx_mix,
):
    """Erstellt die FX-Kette für Offline- und Live-Verarbeitung."""
    from pedalboard import (
        Compressor, Delay, Gain, HighShelfFilter, Limiter, LowShelfFilter,
        Mix, NoiseFilter, NoiseGate, PeakFilter, Pedalboard, Reverb,
    )

    mix_factor = float(fx_mix) / 100.0
    return Pedalboard(
        [
            Gain(gain_db=float(vocal_gain)),
            NoiseFilter(threshold_db=float(-100 + noise_red)),
            NoiseGate(threshold_db=float(gate_thresh), release_ms=float(gate_release)),
            Compressor(
                threshold_db=float(comp_thresh),
                ratio=float(comp_ratio),
                attack_ms=float(comp_attack),
                release_ms=float(comp_release),
            ),
            LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=float(eq_low)),
            PeakFilter(cutoff_frequency_hz=2500.0, gain_db=float(eq_mid), q=1.0),
            HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=float(eq_high)),
            Mix(
                [
                    Pedalboard(
                        [
                            Delay(
                                delay_seconds=float(echo_time),
                                feedback=float(echo_fb) / 100.0,
                                mix=1.0,
                            ),
                            Reverb(
                                room_size=float(reverb_size),
                                wet_level=1.0,
                                dry_level=0.0,
                            ),
                        ]
                    )
                ],
                mix_level=mix_factor,
            ),
            Limiter(threshold_db=-0.5),
        ]
    )


def apply_studio_fx(
    input_wav_path, vocal_gain, noise_red, gate_thresh, gate_release,
    comp_thresh, comp_ratio, comp_attack, comp_release, eq_low, eq_mid,
    eq_high, echo_time, echo_fb, reverb_size, fx_mix, target_sr,
):
    """Wendet die Studio-Effektkette an und schreibt eine temporäre WAV-Datei."""
    try:
        from pedalboard.io import AudioFile

        with AudioFile(input_wav_path) as audio_file:
            audio = audio_file.read(audio_file.frames)
            sample_rate = audio_file.samplerate

        board = create_studio_board(
            vocal_gain, noise_red, gate_thresh, gate_release, comp_thresh,
            comp_ratio, comp_attack, comp_release, eq_low, eq_mid, eq_high,
            echo_time, echo_fb, reverb_size, fx_mix,
        )
        effected = board(audio, sample_rate)

        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = TEMP_DIR / f"temp_master_{threading.get_ident()}.wav"
        with AudioFile(str(temp_path), "w", int(target_sr), effected.shape) as output:
            output.write(effected)

        return str(temp_path)
    except Exception as exc:
        print(f"⚠️ FX Chain Error: {exc}")
        return input_wav_path


def process_audio(
    input_audio, rvc_model, vocal_pitch, f0_method, index_rate, protect,
    filter_radius, rms_mix_rate, hop_length, vocal_gain, noise_red,
    gate_threshold, gate_release, comp_thresh, comp_ratio, comp_attack,
    comp_release, eq_low, eq_mid, eq_high, echo_time, echo_feedback,
    reverb_size, fx_mix, export_codec, sample_rate, mp3_bitrate,
):
    inject_applio_paths()

    # Behalte das bestehende Verhalten bei: verarbeitet wird assets/audio.wav.
    fixed_input_path = ENGINE_DIR / "audio.wav"
    if not fixed_input_path.is_file():
        return None, f"❌ Fehler: 'audio.wav' wurde nicht gefunden ({fixed_input_path})."

    if not rvc_model or "Keine Modelle" in rvc_model:
        return None, "❌ Fehler: Kein gültiges RVC-Modell ausgewählt."

    try:
        model_path = find_model_path(rvc_model)
        index_path = find_associated_index(rvc_model)
        target_sr = int("".join(char for char in str(sample_rate) if char.isdigit()))
        if target_sr not in {44100, 48000}:
            raise ValueError(f"Ungültige Samplerate: {target_sr}")

        status = (
            f"Modell geladen: {model_path.name}\n"
            f"Index geladen: {Path(index_path).name if index_path else 'Keine (.index fehlt)'}\n"
        )

        from rvc.modules.vc.modules import VC

        vc = VC()
        vc.get_vc(str(model_path))
        results = vc.vc_single(
            sid=0,
            input_audio_path=str(fixed_input_path),
            f0_up_key=int(vocal_pitch),
            f0_file=None,
            f0_method=f0_method,
            file_index=index_path,
            file_index2="",
            index_rate=float(index_rate),
            filter_radius=int(filter_radius),
            resample_sr=target_sr,
            rms_mix_rate=float(rms_mix_rate),
            protect=float(protect),
            hop_length=(
                int(hop_length)
                if "crepe" in str(f0_method).lower()
                else 128
            ),
        )

        if not isinstance(results, (tuple, list)) or len(results) < 2:
            raise RuntimeError(f"Unerwartete RVC-Antwort: {results!r}")

        _, rvc_wav_path = results
        if not rvc_wav_path or not os.path.isfile(rvc_wav_path):
            raise FileNotFoundError("RVC hat keine gültige Ausgabedatei erzeugt.")

        mastered_wav = apply_studio_fx(
            rvc_wav_path, vocal_gain, noise_red, gate_threshold, gate_release,
            comp_thresh, comp_ratio, comp_attack, comp_release, eq_low,
            eq_mid, eq_high, echo_time, echo_feedback, reverb_size, fx_mix,
            target_sr,
        )
        final_path = convert_codec(mastered_wav, export_codec, mp3_bitrate)
        return final_path, status + "🟢 Studio Bounce erfolgreich abgeschlossen!"
    except Exception as exc:
        return None, f"Inferenz-Fehler: {exc}"


def rvc_live_worker(
    rvc_model, vocal_pitch, f0_method, index_rate, block_size, sample_rate,
    input_idx, output_idx, vocal_gain, noise_red, gate_thresh, gate_release,
    comp_thresh, comp_ratio, comp_attack, comp_release, eq_low, eq_mid,
    eq_high, echo_time, echo_fb, reverb_size, fx_mix,
):
    global live_streaming, current_live_vc, current_live_model_path
    global current_live_vu_level, recorded_blocks, is_recording

    inject_applio_paths()

    try:
        from rvc.modules.vc.modules import VC

        model_path = find_model_path(rvc_model)
        index_path = find_associated_index(rvc_model)

        if current_live_vc is None or current_live_model_path != str(model_path):
            current_live_vc = VC()
            current_live_vc.get_vc(str(model_path))
            current_live_model_path = str(model_path)

        board = create_studio_board(
            vocal_gain, noise_red, gate_thresh, gate_release, comp_thresh,
            comp_ratio, comp_attack, comp_release, eq_low, eq_mid, eq_high,
            echo_time, echo_fb, reverb_size, fx_mix,
        )
        temp_input_path = TEMP_DIR / f"live_in_{threading.get_ident()}.wav"
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        def audio_callback(indata, outdata, frames, _time, status):
            global current_live_vu_level, recorded_blocks, is_recording

            if status:
                print(f"⚠️ Audio-Stream-Status: {status}")

            with state_lock:
                if not live_streaming:
                    raise sd.CallbackStop

            mono_input = indata[:, 0].copy()
            rms = float(np.sqrt(np.mean(np.square(mono_input))))
            with state_lock:
                current_live_vu_level = 20 * np.log10(rms) if rms > 0 else -60.0

            try:
                sf.write(temp_input_path, mono_input, sample_rate)
                _, rvc_wav = current_live_vc.vc_single(
                    sid=0,
                    input_audio_path=str(temp_input_path),
                    f0_up_key=int(vocal_pitch),
                    f0_file=None,
                    f0_method=f0_method,
                    file_index=index_path,
                    file_index2="",
                    index_rate=float(index_rate),
                    filter_radius=3,
                    resample_sr=sample_rate,
                    rms_mix_rate=0.25,
                    protect=0.33,
                    hop_length=128,
                )

                output_data, output_sr = sf.read(rvc_wav, dtype="float32")
                if output_data.ndim == 2:
                    output_data = output_data.mean(axis=1)
                if output_sr != sample_rate:
                    raise ValueError(
                        f"Samplerate der Live-Ausgabe ist {output_sr}, "
                        f"erwartet wurde {sample_rate}."
                    )

                effected = board(output_data, sample_rate)
                effected = np.asarray(effected, dtype=np.float32).reshape(-1)

                if is_recording:
                    with state_lock:
                        if is_recording:
                            recorded_blocks.append(effected.copy())

                output_length = min(frames, len(effected))
                outdata[:output_length, 0] = effected[:output_length]
                if output_length < frames:
                    outdata[output_length:, 0] = 0.0
            except Exception as exc:
                print(f"⚠️ Live-Callback-Fehler: {exc}")
                outdata[:, 0] = mono_input[:frames]

                with state_lock:
                    if is_recording:
                        recorded_blocks.append(mono_input.copy())

        with sd.Stream(
            samplerate=sample_rate,
            blocksize=int(block_size),
            device=(input_idx, output_idx),
            channels=1,
            callback=audio_callback,
        ):
            while True:
                with state_lock:
                    if not live_streaming:
                        break
                sd.sleep(100)
    except Exception as exc:
        print(f"⚠️ Live-Stream-Fehler: {exc}")
    finally:
        with state_lock:
            live_streaming = False


def start_live_mode(
    rvc_model, vocal_pitch, f0_method, index_rate, input_device,
    output_device, block_size, vocal_gain, noise_red, gate_thresh,
    gate_release, comp_thresh, comp_ratio, comp_attack, comp_release,
    eq_low, eq_mid, eq_high, echo_time, echo_fb, reverb_size, fx_mix,
):
    global live_streaming, live_thread

    with state_lock:
        if live_streaming:
            return "⚠️ Live-Modus läuft bereits."

    if not rvc_model or "Keine Modelle" in rvc_model:
        return "❌ Fehler: Bitte zuerst ein gültiges RVC-Modell auswählen."

    try:
        input_idx = int(input_device.split(":", 1)[0])
        output_idx = int(output_device.split(":", 1)[0])
        sample_rate = 44100
        block_size = int(block_size)

        sd.check_input_settings(
            device=input_idx, channels=1, samplerate=sample_rate
        )
        sd.check_output_settings(
            device=output_idx, channels=1, samplerate=sample_rate
        )
    except Exception as exc:
        return f"❌ Fehler bei der Audio-Geräteauswahl: {exc}"

    with state_lock:
        live_streaming = True

    live_thread = threading.Thread(
        target=rvc_live_worker,
        args=(
            rvc_model, vocal_pitch, f0_method, index_rate, block_size,
            sample_rate, input_idx, output_idx, vocal_gain, noise_red,
            gate_thresh, gate_release, comp_thresh, comp_ratio, comp_attack,
            comp_release, eq_low, eq_mid, eq_high, echo_time, echo_fb,
            reverb_size, fx_mix,
        ),
        daemon=True,
    )
    live_thread.start()
    return (
        f"🟢 LIVE-INFERENZ AKTIV ({Path(rvc_model).name}) "
        f"// Buffer: {block_size} // Studio-Effektkette live geladen."
    )


def stop_live_mode():
    global live_streaming, is_recording

    with state_lock:
        if not live_streaming:
            return "🔴 Live-Modus ist bereits offline."
        live_streaming = False
        is_recording = False

    return "🔴 LIVE MODE BEENDET // Zurück im Studio-Modus."


def update_live_vu():
    """Aktualisiert den Live-Pegel und den Status im UI."""
    with state_lock:
        streaming = live_streaming
        level = float(current_live_vu_level)

    if not streaming:
        return gr.update(value=-60.0), "🔴 OFFLINE"

    status = "🟢 MONITORING" if level < -0.5 else "⚠️ CLIPPING / TOO LOUD"
    return gr.update(value=level), status


def start_live_recording():
    global is_recording, recorded_blocks

    with state_lock:
        if not live_streaming:
            return "❌ Fehler: Eine Aufnahme ist nur im aktiven Live-Modus möglich."
        if is_recording:
            return "⚠️ Aufnahme läuft bereits."
        recorded_blocks = []
        is_recording = True

    return "🔴 RECORDING GESTARTET // Studio mitschneiden..."


def stop_live_recording(export_codec, mp3_bitrate):
    global is_recording, recorded_blocks, last_recorded_file

    with state_lock:
        if not is_recording:
            return gr.update(), "⚠️ Keine aktive Live-Aufnahme gefunden."
        is_recording = False
        blocks = recorded_blocks
        recorded_blocks = []

    if not blocks:
        return gr.update(), "⚠️ Aufnahme gestoppt, aber es wurden keine Audiodaten empfangen."

    try:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = TEMP_DIR / f"live_rec_temp_{threading.get_ident()}.wav"

        audio = np.concatenate(blocks, axis=0)
        sf.write(temp_path, audio, 44100)

        final_path = convert_codec(
            str(temp_path),
            export_codec,
            mp3_bitrate,
            output_dir=RECORDINGS_DIR,
        )
        last_recorded_file = final_path
        return (
            gr.update(value=final_path),
            f"💾 Aufnahme gespeichert unter:\n{Path(final_path).name}",
        )
    except Exception as exc:
        return gr.update(), f"❌ Fehler beim Speichern der Aufnahme: {exc}"


# UI initialisieren
available_choices, default_model = get_dropdown_data()
input_devices, output_devices, default_input, default_output = get_audio_devices()

custom_css = """
.green-title h1 { color: #22c55e !important; }
.red-title h1 { color: #ef4444 !important; }
.section-gain { background: #1e293b !important; padding: 15px; border-radius: 8px; border-left: 4px solid #3b82f6; margin-bottom: 10px; }
.section-dynamics { background: #1e293b !important; padding: 10px; border-radius: 8px; border-left: 4px solid #06b6d4; }
.section-eq { background: #1e293b !important; padding: 10px; border-radius: 8px; border-left: 4px solid #64748b; }
.section-time { background: #1e293b !important; padding: 10px; border-radius: 8px; border-left: 4px solid #8b5cf6; }
"""

with gr.Blocks(
    title="Super Impersonator app",
    js="() => document.documentElement.classList.add('dark')",
    css=custom_css,
    theme=gr.themes.Default(),
) as app:
    with gr.Row():
        gr.Markdown("# Super Impersonator app", elem_classes=["green-title"])
    with gr.Row():
        gr.Markdown("# App", elem_classes=["red-title"])
        gr.Markdown("### Engine v3.0 DYNAMICS FX // by don24crk")

    with gr.Row():
        with gr.Column():
            gr.Markdown("## 01 / INPUT SIGNAL & STUDIO FX CHAIN")
            input_audio = gr.Audio(
                label="Studio I/O (Gesteuert über lokale audio.wav)",
                type="filepath",
            )
            with gr.Row():
                rvc_model = gr.Dropdown(
                    label="RVC Modell (.pth) [inkl. Unterordner]",
                    choices=available_choices,
                    value=default_model,
                    scale=4,
                )
                refresh_btn = gr.Button("🔄", scale=1)

            vocal_pitch = gr.Slider(
                label="Vocal Pitch (Halbtöne)", minimum=-24, maximum=24,
                step=1, value=0,
            )
            f0_method = gr.Dropdown(
                label="F0 Pitch Extraction Method",
                choices=["rmvpe", "harvest", "crepe", "mangio-crepe", "pm", "dio"],
                value="crepe",
            )
            index_rate = gr.Slider(
                label="Index Rate (Stimmenähnlichkeit)", minimum=0.0,
                maximum=1.0, step=0.05, value=1.0,
            )
            protect = gr.Slider(
                label="Protect (Konsonanten- und Atemschutz)", minimum=0.0,
                maximum=0.5, step=0.01, value=0.33,
            )
            filter_radius = gr.Slider(
                label="Filter Radius (F0 Glättung)", minimum=0, maximum=7,
                step=1, value=3,
            )
            rms_mix_rate = gr.Slider(
                label="Clean Audio / Autoclean (RMS Mix Rate)", minimum=0.0,
                maximum=1.0, step=0.05, value=0.25,
            )
            hop_length = gr.Dropdown(
                label="Crepe Hop Length (Zeitliche Präzision)",
                choices=["16", "32", "64", "128", "256", "512"],
                value="128",
                visible=True,
            )
            studio_preset = gr.Dropdown(
                label="🎛️ Studio FX Presets",
                choices=list(STUDIO_PRESETS),
                value="Standard (Manuell)",
            )

            with gr.Column(elem_classes=["section-gain"]):
                gr.Markdown("### 01.A / DIGITAL HARDWARE GAIN & NOISE REDUCTION")
                vocal_gain = gr.Slider(
                    label="Digital Microphone Gain (dB)", minimum=-12,
                    maximum=24, step=0.5, value=0.0,
                )
                noise_red = gr.Slider(
                    label="Noise Reduction Intensity (%)", minimum=0,
                    maximum=100, step=1, value=0,
                )

            with gr.Accordion(
                "01.B / STUDIO DYNAMICS (NOISE GATE)",
                open=False,
                elem_classes=["section-dynamics"],
            ):
                gate_threshold = gr.Slider(
                    label="Gate Threshold (dB)", minimum=-60, maximum=0,
                    step=1, value=-50,
                )
                gate_release = gr.Slider(
                    label="Gate Release (ms)", minimum=10, maximum=1000,
                    step=10, value=150,
                )

            with gr.Accordion(
                "01.C / STUDIO DYNAMICS (COMPRESSOR)",
                open=False,
                elem_classes=["section-dynamics"],
            ):
                comp_thresh = gr.Slider(
                    label="Compressor Threshold (dB)", minimum=-40,
                    maximum=0, step=1, value=-20,
                )
                comp_ratio = gr.Slider(
                    label="Compressor Ratio", minimum=1.0, maximum=10.0,
                    step=0.5, value=3.5,
                )
                comp_attack = gr.Slider(
                    label="Compressor Attack (ms)", minimum=1, maximum=100,
                    step=1, value=15,
                )
                comp_release = gr.Slider(
                    label="Compressor Release (ms)", minimum=10,
                    maximum=1000, step=10, value=200,
                )

            with gr.Accordion(
                "01.D / STUDIO PARAMETRIC EQ",
                open=False,
                elem_classes=["section-eq"],
            ):
                eq_low = gr.Slider(
                    label="Low (100 Hz) (dB)", minimum=-12, maximum=12,
                    step=1, value=0,
                )
                eq_mid = gr.Slider(
                    label="Mid (2.5 kHz) (dB)", minimum=-12, maximum=12,
                    step=1, value=2,
                )
                eq_high = gr.Slider(
                    label="High (10 kHz) (dB)", minimum=-12, maximum=12,
                    step=1, value=1,
                )

            with gr.Accordion(
                "01.E / TIME & AMBIENCE FX",
                open=False,
                elem_classes=["section-time"],
            ):
                echo_time = gr.Slider(
                    label="Stereo Delay Time (s)", minimum=0.0, maximum=2.0,
                    step=0.05, value=0.3,
                )
                echo_feedback = gr.Slider(
                    label="Delay Feedback (%)", minimum=0, maximum=100,
                    step=5, value=30,
                )
                reverb_size = gr.Slider(
                    label="Reverb Room Size", minimum=0.0, maximum=1.0,
                    step=0.05, value=0.5,
                )
                fx_mix = gr.Slider(
                    label="FX Wet/Dry Mix (%)", minimum=0, maximum=100,
                    step=5, value=15,
                )

            convert_btn = gr.Button("🎵 Musik umwandeln", variant="primary")
            local_output_audio = gr.Audio(label="Konvertiertes Audio (Direkt-Player)")

        with gr.Column():
            gr.Markdown("## 02 / REALTIME MICROPHONE MATRIX")
            input_device = gr.Dropdown(
                label="Audio Eingangsgerät (Mikrofon)",
                choices=input_devices,
                value=default_input,
            )
            output_device = gr.Dropdown(
                label="Audio Ausgangsgerät (Monitor)",
                choices=output_devices,
                value=default_output,
            )
            live_block_size = gr.Slider(
                label="Live Buffer Size (Niedriger = Weniger Latenz)",
                minimum=1024, maximum=8192, step=1024, value=2048,
            )
            live_vu_meter = gr.Slider(
                label="Microphone Signal Input Level (dB)",
                minimum=-60, maximum=0, value=-60, interactive=False,
            )
            vu_status_txt = gr.Markdown("🔴 OFFLINE")
            live_vu_timer = gr.Timer(value=0.1, active=True)

            with gr.Row():
                start_live = gr.Button("🎤 LIVE MODE START", variant="primary")
                stop_live = gr.Button("🛑 LIVE MODE STOP", variant="stop")

            gr.Markdown("### 🎙️ STUDIO STREAM RECORDER")
            with gr.Row():
                start_rec_btn = gr.Button("🔴 REC START", variant="primary")
                stop_rec_btn = gr.Button("⏹️ REC STOP", variant="stop")
            live_preview_audio = gr.Audio(
                label="Letzte Live-Aufnahme (Vorschau)",
                interactive=False,
            )

            gr.Markdown("## 03 / HARDWARE MONITORING")
            status_output = gr.Textbox(
                label="System-Matrix Status",
                interactive=False,
                lines=6,
                value="🟢 ONLINE\nSystem bereit für Inferenz, FX-Mastering oder Live-Streaming.",
            )

            gr.Markdown("## 04 / MASTER EXPORT ROUTER")
            export_codec = gr.Radio(
                choices=["WAV", "MP3", "FLAC", "WMA", "VOB"],
                value="WAV",
                label="Ziel-Codec",
            )
            mp3_bitrate = gr.Slider(
                label="MP3 Export Bitrate (kbps)", minimum=96, maximum=320,
                step=32, value=320,
            )
            sample_rate = gr.Radio(
                choices=["48000 Hz", "44100 Hz"],
                value="48000 Hz",
                label="Studio Samplerate",
            )
            bounce_btn = gr.Button("Bounce Master", variant="primary")
            output_audio = gr.Audio(label="Master Ausgabe")

    studio_preset.change(
        fn=load_preset_values,
        inputs=[studio_preset],
        outputs=[
            vocal_gain, noise_red, gate_threshold, gate_release, comp_thresh,
            comp_ratio, comp_attack, comp_release, eq_low, eq_mid, eq_high,
            echo_time, echo_feedback, reverb_size, fx_mix,
        ],
    )
    live_vu_timer.tick(
        fn=update_live_vu,
        inputs=[],
        outputs=[live_vu_meter, vu_status_txt],
    )
    start_rec_btn.click(
        fn=start_live_recording,
        inputs=[],
        outputs=status_output,
    )
    stop_rec_btn.click(
        fn=stop_live_recording,
        inputs=[export_codec, mp3_bitrate],
        outputs=[live_preview_audio, status_output],
    )
    f0_method.change(
        fn=update_hop_visibility,
        inputs=f0_method,
        outputs=hop_length,
    )
    refresh_btn.click(
        fn=refresh_models,
        inputs=[],
        outputs=rvc_model,
    )

    start_live.click(
        fn=start_live_mode,
        inputs=[
            rvc_model, vocal_pitch, f0_method, index_rate, input_device,
            output_device, live_block_size, vocal_gain, noise_red,
            gate_threshold, gate_release, comp_thresh, comp_ratio,
            comp_attack, comp_release, eq_low, eq_mid, eq_high, echo_time,
            echo_feedback, reverb_size, fx_mix,
        ],
        outputs=status_output,
    )
    stop_live.click(
        fn=stop_live_mode,
        inputs=[],
        outputs=status_output,
    )

    process_inputs = [
        input_audio, rvc_model, vocal_pitch, f0_method, index_rate, protect,
        filter_radius, rms_mix_rate, hop_length, vocal_gain, noise_red,
        gate_threshold, gate_release, comp_thresh, comp_ratio, comp_attack,
        comp_release, eq_low, eq_mid, eq_high, echo_time, echo_feedback,
        reverb_size, fx_mix, export_codec, sample_rate, mp3_bitrate,
    ]

    convert_btn.click(
        fn=process_audio,
        inputs=process_inputs,
        outputs=[local_output_audio, status_output],
    ).then(
        fn=lambda audio: audio,
        inputs=[local_output_audio],
        outputs=[output_audio],
    )

    bounce_btn.click(
        fn=process_audio,
        inputs=process_inputs,
        outputs=[output_audio, status_output],
    )


if __name__ == "__main__":
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
    )
