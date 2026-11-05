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

        return input_devs, output_devs, default_in, default_out
    except Exception as e:
        print(f"?? Fehler beim Abrufen der Audiogeräte: {e}")
        return ["0: Standard-Eingang"], ["0: Standard-Ausgang"], "0: Standard-Eingang", "0: Standard-Ausgang"

def scan_rvc_models():
    """Scannt beide Modell-Verzeichnisse und gibt relative Pfade zurück."""
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR, exist_ok=True)

    models = []

    # 1. Engine-Modelle scannen
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            if file.endswith(".pth"):
                rel_path = os.path.relpath(os.path.join(root, file), MODELS_DIR)
                formatted_path = rel_path.replace("\\", "/")
                if formatted_path not in models:
                    models.append(formatted_path)

    # 2. Applio-Modelle scannen
    if os.path.exists(APPLIO_MODELS_DIR):
        for root, dirs, files in os.walk(APPLIO_MODELS_DIR):
            for file in files:
                if file.endswith(".pth"):
                    rel_path = os.path.relpath(os.path.join(root, file), APPLIO_MODELS_DIR)
                    formatted_path = rel_path.replace("\\", "/")
                    if formatted_path not in models:
                        models.append(formatted_path)

    return sorted(models)

def get_dropdown_data():
    models = scan_rvc_models()
    if not models:
        return ["Keine Modelle in assets/models/ gefunden"], "Keine Modelle in assets/models/ gefunden"
    return models, models[0]

def refresh_models():
    choices, default_val = get_dropdown_data()
    return gr.Dropdown(choices=choices, value=default_val)

def find_associated_index(model_rel_path):
    """Sucht die zugehörige .index-Datei in beiden Verzeichnissen."""
    possible_abs_paths = [
        os.path.join(MODELS_DIR, model_rel_path),
        os.path.join(APPLIO_MODELS_DIR, model_rel_path)
    ]

    for model_abs_path in possible_abs_paths:
        model_dir = os.path.dirname(model_abs_path)
        model_base_name = os.path.splitext(os.path.basename(model_abs_path))[0]

        if os.path.exists(model_dir):
            exact_index_match = os.path.join(model_dir, f"{model_base_name}.index")
            if os.path.exists(exact_index_match):
                return exact_index_match
            fallback_index_files = glob.glob(os.path.join(model_dir, "*.index"))
            if fallback_index_files:
                return fallback_index_files[0]

    return ""

def update_hop_visibility(f0_method_val):
    if "crepe" in f0_method_val:
        return gr.Dropdown(visible=True)
    return gr.Dropdown(visible=False)

def load_preset_values(preset_name):
    """Gibt die gespeicherten Parameter-Werte eines Presets an die UI zurück."""
    if preset_name in STUDIO_PRESETS:
        p = STUDIO_PRESETS[preset_name]
        return (
            p["vocal_gain"], p["noise_red"], p["gate_thresh"], p["gate_release"],
            p["comp_thresh"], p["comp_ratio"], p["comp_attack"], p["comp_release"],
            p["eq_low"], p["eq_mid"], p["eq_high"], p["echo_time"], p["echo_fb"],
            p["reverb_size"], p["fx_mix"]
        )
    return [gr.update() for _ in range(15)]

def convert_codec(input_wav, target_codec, mp3_bitrate=320, output_dir=None):
    ext = target_codec.lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = output_dir if output_dir else ENGINE_DIR
    prefix = "live_rec" if output_dir == RECORDINGS_DIR else "master_bounce"
    final_output_path = os.path.join(base_dir, f"{prefix}_{timestamp}.{ext}")

    if ext == "wav":
        shutil.copy(input_wav, final_output_path)
        if output_dir == RECORDINGS_DIR:
            try:
                os.makedirs(BACKUP_DIR, exist_ok=True)
                shutil.copy(final_output_path, os.path.join(BACKUP_DIR, os.path.basename(final_output_path)))
                print(f"??? Redundanz-Backup erfolgreich: {BACKUP_DIR}")
            except Exception as b_err:
                print(f"?? Backup-Fehler: {b_err}")
        return final_output_path
    try:
        from pydub import AudioSegment
        ffmpeg_exe_path = os.path.join(FFMPEG_BIN_DIR, "ffmpeg.exe")
        if os.path.exists(ffmpeg_exe_path):
            AudioSegment.converter = ffmpeg_exe_path
        sound = AudioSegment.from_wav(input_wav)
        if ext == "mp3":
            sound.export(final_output_path, format="mp3", bitrate=f"{int(mp3_bitrate)}k")
        elif ext == "flac":
            sound.export(final_output_path, format="flac")
        elif ext in ["wma", "vob"]:
            sound.export(final_output_path, format=ext)

        if output_dir == RECORDINGS_DIR:
            try:
                os.makedirs(BACKUP_DIR, exist_ok=True)
                shutil.copy(final_output_path, os.path.join(BACKUP_DIR, os.path.basename(final_output_path)))
                print(f"??? Redundanz-Backup erfolgreich: {BACKUP_DIR}")
            except Exception as b_err:
                print(f"?? Backup-Fehler: {b_err}")

        return final_output_path
    except Exception as e:
        print(f"?? Codec-Konvertierung fehlgeschlagen ({str(e)}). Gebe WAV-Backup aus.")
        fallback_path = os.path.join(base_dir, f"{prefix}_{timestamp}_fallback.wav")
        shutil.copy(input_wav, fallback_path)
        return fallback_path

def apply_studio_fx(input_wav_path, vocal_gain, noise_red, gate_thresh, gate_release,
                    comp_thresh, comp_ratio, comp_attack, comp_release,
                    eq_low, eq_mid, eq_high, echo_time, echo_fb,
                    reverb_size, fx_mix, target_sr):
    """Wendet die Studio-Effektkette auf eine WAV-Datei an."""
    try:
        from pedalboard import (
            Pedalboard, Gain, NoiseFilter, NoiseGate, Compressor, PeakFilter,
            LowShelfFilter, HighShelfFilter, Delay, Reverb, Mix, Limiter,
        )
        from pedalboard.io import AudioFile

        with AudioFile(input_wav_path) as audio_file:
            audio = audio_file.read(audio_file.frames)
            source_sr = audio_file.samplerate

        mix_factor = fx_mix / 100.0
        board = Pedalboard([
            Gain(gain_db=vocal_gain),
            NoiseFilter(threshold_db=float(-100 + noise_red)),
            NoiseGate(threshold_db=gate_thresh, release_ms=gate_release),
            Compressor(threshold_db=comp_thresh, ratio=comp_ratio,
                       attack_ms=comp_attack, release_ms=comp_release),
            LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=eq_low),
            PeakFilter(cutoff_frequency_hz=2500.0, gain_db=eq_mid, q=1.0),
            HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=eq_high),
            Mix([Pedalboard([
                Delay(delay_seconds=echo_time, feedback=echo_fb / 100.0, mix=1.0),
                Reverb(room_size=reverb_size, wet_level=1.0, dry_level=0.0),
            ])], mix_level=mix_factor),
            Limiter(threshold_db=-0.5),
        ])
        effected = board(audio, source_sr)
        temp_out_dir = os.path.join(ENGINE_DIR, "assets", "temp")
        os.makedirs(temp_out_dir, exist_ok=True)
        temp_wav = os.path.join(temp_out_dir, "temp_master.wav")
        with AudioFile(temp_wav, "w", target_sr, effected.shape) as output_file:
            output_file.write(effected)
        return temp_wav
    except Exception as fx_err:
        print(f"FX Chain Error: {fx_err}")
        return input_wav_path


def process_audio(
    input_audio, rvc_model, vocal_pitch, f0_method, index_rate, protect,
    filter_radius, rms_mix_rate, hop_length, vocal_gain, noise_red,
    gate_threshold, gate_release, comp_thresh, comp_ratio, comp_attack,
    comp_release, eq_low, eq_mid, eq_high, echo_time, echo_feedback,
    reverb_size, fx_mix, export_codec, sample_rate, mp3_bitrate,
):
    inject_applio_paths()
    fixed_input_path = os.path.join(ENGINE_DIR, "audio.wav")
    if not os.path.exists(fixed_input_path):
        return None, f"Fehler: 'audio.wav' wurde nicht gefunden: {fixed_input_path}"
    if not rvc_model or "Keine Modelle" in rvc_model:
        return None, "Fehler: Kein gültiges RVC-Modell ausgewählt."

    model_path = os.path.normpath(os.path.join(MODELS_DIR, rvc_model))
    if not os.path.exists(model_path) and os.path.exists(APPLIO_MODELS_DIR):
        model_path = os.path.normpath(os.path.join(APPLIO_MODELS_DIR, rvc_model))
    index_path = find_associated_index(rvc_model)
    sr_digits = "".join(char for char in str(sample_rate) if char.isdigit())
    target_sr = int(sr_digits) if sr_digits else 48000
    status_msg = (
        f"Modell geladen: {os.path.basename(model_path)}\n"
        f"Index geladen: {os.path.basename(index_path) if index_path else 'Keine (.index fehlt)'}\n"
    )
    try:
        from rvc.modules.vc.modules import VC

        vc = VC()
        vc.get_vc(model_path)
        results = vc.vc_single(
            sid=0, input_audio_path=fixed_input_path, f0_up_key=vocal_pitch,
            f0_file=None, f0_method=f0_method, file_index=index_path,
            file_index2="", index_rate=index_rate,
            filter_radius=int(filter_radius), resample_sr=target_sr,
            rms_mix_rate=rms_mix_rate, protect=protect,
            hop_length=int(hop_length) if "crepe" in f0_method else 128,
        )
        _, rvc_wav_path = results
        temp_master_wav = apply_studio_fx(
            rvc_wav_path, vocal_gain, noise_red, gate_threshold, gate_release,
            comp_thresh, comp_ratio, comp_attack, comp_release, eq_low, eq_mid,
            eq_high, echo_time, echo_feedback, reverb_size, fx_mix, target_sr,
        )
        final_file_path = convert_codec(temp_master_wav, export_codec, mp3_bitrate)
        return final_file_path, status_msg + "Studio Bounce erfolgreich abgeschlossen!"
    except Exception as exc:
        return None, f"Inferenz-Fehler: {exc}"


def rvc_live_worker(
    rvc_model, vocal_pitch, f0_method, index_rate, block_size, sr,
    input_idx, output_idx, vocal_gain, noise_red, gate_thresh, gate_release,
    comp_thresh, comp_ratio, comp_attack, comp_release, eq_low, eq_mid,
    eq_high, echo_time, echo_fb, reverb_size, fx_mix, bgm_file, bgm_volume,
    ducking_db, sb_file_1, sb_volume_1, sb_pitch_1, sb_filter_1,
):
    global live_streaming, current_live_vc, current_live_model_path
    global is_recording, recorded_blocks, current_live_vu_level
    global vocal_waveform_data, bgm_waveform_data

    inject_applio_paths()
    try:
        from rvc.modules.vc.modules import VC
        from pedalboard import (
            Pedalboard, Gain, NoiseFilter, NoiseGate, Compressor, PeakFilter,
            LowShelfFilter, HighShelfFilter, Delay, Reverb, Mix, Limiter,
            HighpassFilter, LowPassFilter, PitchShift,
        )

        model_path = os.path.normpath(os.path.join(MODELS_DIR, rvc_model))
        if not os.path.exists(model_path) and os.path.exists(APPLIO_MODELS_DIR):
            model_path = os.path.normpath(os.path.join(APPLIO_MODELS_DIR, rvc_model))
        index_path = find_associated_index(rvc_model)
        if current_live_vc is None or current_live_model_path != model_path:
            current_live_vc = VC()
            current_live_vc.get_vc(model_path)
            current_live_model_path = model_path

        temp_in_file = os.path.join(ENGINE_DIR, "assets", "temp", "live_in.wav")
        os.makedirs(os.path.dirname(temp_in_file), exist_ok=True)

        bgm_data, bgm_sr, bgm_ptr = None, 44100, 0
        if bgm_file and os.path.exists(bgm_file):
            try:
                bgm_data, bgm_sr = sf.read(bgm_file, dtype="float32")
                if bgm_data.ndim > 1:
                    bgm_data = bgm_data[:, 0]
            except Exception as exc:
                print(f"BGM Import-Fehler: {exc}")

        sb_data_1, sb_sr_1, sb_ptr_1 = None, 44100, 0
        if sb_file_1 and os.path.exists(sb_file_1):
            try:
                sb_data_1, sb_sr_1 = sf.read(sb_file_1, dtype="float32")
                if sb_data_1.ndim > 1:
                    sb_data_1 = sb_data_1[:, 0]
                sb_board = Pedalboard()
                if sb_pitch_1 != 0.0:
                    sb_board.append(PitchShift(semitones=sb_pitch_1))
                if sb_filter_1 == "High-Pass (Clean)":
                    sb_board.append(HighpassFilter(cutoff_frequency_hz=300))
                elif sb_filter_1 == "Low-Pass (Muffled)":
                    sb_board.append(LowPassFilter(cutoff_frequency_hz=1200))
                sb_data_1 = sb_board(sb_data_1, sb_sr_1)
            except Exception as exc:
                print(f"Soundboard Import-Fehler: {exc}")
                sb_data_1 = None

        mix_factor = fx_mix / 100.0
        live_board = Pedalboard([
            Gain(gain_db=vocal_gain),
            NoiseFilter(threshold_db=float(-100 + noise_red)),
            NoiseGate(threshold_db=gate_thresh, release_ms=gate_release),
            Compressor(threshold_db=comp_thresh, ratio=comp_ratio,
                       attack_ms=comp_attack, release_ms=comp_release),
            LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=eq_low),
            PeakFilter(cutoff_frequency_hz=2500.0, gain_db=eq_mid, q=1.0),
            HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=eq_high),
            Mix([Pedalboard([
                Delay(delay_seconds=echo_time, feedback=echo_fb / 100.0, mix=1.0),
                Reverb(room_size=reverb_size, wet_level=1.0, dry_level=0.0),
            ])], mix_level=mix_factor),
            Limiter(threshold_db=-0.5),
        ])

        def audio_callback(indata, outdata, frames, time_info, status):
            nonlocal bgm_ptr, sb_ptr_1
            global current_live_vu_level, recorded_blocks
            global vocal_waveform_data, bgm_waveform_data

            if not live_streaming:
                raise sd.CallbackStop
            rms = np.sqrt(np.mean(indata ** 2))
            current_live_vu_level = 20 * np.log10(rms) if rms > 0 else -60.0
            if len(indata) >= 50:
                vocal_waveform_data = indata[:50, 0].tolist()
            is_speaking = current_live_vu_level > gate_thresh
            current_ducking = ducking_db if is_speaking else 0.0
            bgm_scale = 10 ** ((bgm_volume - current_ducking) / 20.0)
            sb_scale = 10 ** (sb_volume_1 / 20.0)

            try:
                sf.write(temp_in_file, indata, sr)
                _, rvc_wav = current_live_vc.vc_single(
                    sid=0, input_audio_path=temp_in_file, f0_up_key=vocal_pitch,
                    f0_file=None, f0_method=f0_method, file_index=index_path,
                    file_index2="", index_rate=index_rate, filter_radius=3,
                    resample_sr=sr, rms_mix_rate=0.25, protect=0.33, hop_length=128,
                )
                out_data, _ = sf.read(rvc_wav)
                effected_live = live_board(out_data, sr)
            except Exception:
                effected_live = indata[:, 0]

            mixed_block = np.zeros(frames, dtype="float32")
            non_vocal_block = np.zeros(frames, dtype="float32")
            vocal_count = min(len(effected_live), frames)
            mixed_block[:vocal_count] += effected_live[:vocal_count]

            if bgm_data is not None and bgm_ptr < len(bgm_data):
                take = min(frames, len(bgm_data) - bgm_ptr)
                chunk = bgm_data[bgm_ptr:bgm_ptr + take] * bgm_scale
                mixed_block[:take] += chunk
                non_vocal_block[:take] += chunk
                bgm_ptr += take

            if sb_data_1 is not None and sb_ptr_1 < len(sb_data_1):
                take_sb = min(frames, len(sb_data_1) - sb_ptr_1)
                chunk = sb_data_1[sb_ptr_1:sb_ptr_1 + take_sb] * sb_scale
                mixed_block[:take_sb] += chunk
                non_vocal_block[:take_sb] += chunk
                sb_ptr_1 += take_sb

            if len(non_vocal_block) >= 50:
                bgm_waveform_data = non_vocal_block[:50].tolist()
            if is_recording:
                recorded_blocks.append(mixed_block.copy().reshape(-1, 1))
            outdata[:, 0] = mixed_block

        with sd.Stream(
            samplerate=sr, blocksize=int(block_size),
            device=(input_idx, output_idx), channels=1, callback=audio_callback,
        ):
            while live_streaming:
                sd.sleep(100)
    except Exception as exc:
        print(f"Live-Stream Fehler: {exc}")
        live_streaming = False


def start_live_mode(
    rvc_model, vocal_pitch, f0_method, index_rate, input_device, output_device,
    block_size, vocal_gain, noise_red, gate_thresh, gate_release, comp_thresh,
    comp_ratio, comp_attack, comp_release, eq_low, eq_mid, eq_high, echo_time,
    echo_fb, reverb_size, fx_mix, bgm_file, bgm_volume, ducking_db,
    sb_file_1, sb_volume_1, sb_pitch_1, sb_filter_1,
):
    global live_streaming, live_thread
    if live_streaming:
        return "Live-Modus läuft bereits."
    if not rvc_model or "Keine Modelle" in rvc_model:
        return "Fehler: RVC-Modell ungültig."
    try:
        input_idx = int(input_device.split(":")[0])
        output_idx = int(output_device.split(":")[0])
    except Exception:
        return "Fehler: Audio-Geräteauswahl fehlerhaft."

    live_streaming = True
    live_thread = threading.Thread(
        target=rvc_live_worker,
        args=(
            rvc_model, vocal_pitch, f0_method, index_rate, block_size, 44100,
            input_idx, output_idx, vocal_gain, noise_red, gate_thresh,
            gate_release, comp_thresh, comp_ratio, comp_attack, comp_release,
            eq_low, eq_mid, eq_high, echo_time, echo_fb, reverb_size, fx_mix,
            bgm_file, bgm_volume, ducking_db, sb_file_1, sb_volume_1,
            sb_pitch_1, sb_filter_1,
        ),
        daemon=True,
    )
    live_thread.start()
    return "LIVE INFERENZ AKTIV // Mischpult & Studio-Effektbänke online."


def stop_live_mode():
    global live_streaming, is_recording
    if not live_streaming:
        return "Live-Modus ist bereits offline."
    live_streaming = False
    is_recording = False
    return "LIVE MODE BEENDET // Zurück im Studio-Modus."


def update_live_vu():
    global current_live_vu_level, live_streaming, vocal_waveform_data, bgm_waveform_data
    if not live_streaming:
        return gr.update(value=-60.0), "OFFLINE", vocal_waveform_data, bgm_waveform_data
    status_text = "MONITORING" if current_live_vu_level < -0.5 else "CLIPPING / OVERLOAD"
    return gr.update(value=float(current_live_vu_level)), status_text, vocal_waveform_data, bgm_waveform_data


def start_live_recording():
    global is_recording, recorded_blocks, live_streaming
    if not live_streaming:
        return "Fehler: Benötigt aktiven LIVE MODE."
    if is_recording:
        return "Aufnahme läuft bereits."
    recorded_blocks = []
    is_recording = True
    return "RECORDING GESTARTET // Studio Master wird aufgezeichnet..."


def stop_live_recording(export_codec, mp3_bitrate):
    global is_recording, recorded_blocks, last_recorded_file
    if not is_recording:
        return gr.update(), "Keine aktive Live-Aufnahme gefunden."
    is_recording = False
    if not recorded_blocks:
        return gr.update(), "Keine Audio-Blöcke empfangen."
    try:
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        temp_dir = os.path.join(ENGINE_DIR, "assets", "temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_rec_wav = os.path.join(temp_dir, "live_rec_temp.wav")
        full_audio = np.concatenate(recorded_blocks, axis=0)
        sf.write(temp_rec_wav, full_audio, 44100)
        final_file = convert_codec(
            temp_rec_wav, export_codec, mp3_bitrate, output_dir=RECORDINGS_DIR,
        )
        last_recorded_file = final_file
        return gr.update(value=final_file), (
            f"Erfolgreich exportiert & gespiegelt nach {BACKUP_DIR}:\n"
            f"{os.path.basename(final_file)}"
        )
    except Exception as rec_err:
        return gr.update(), f"Fehler beim Schreiben: {rec_err}"


available_choices, default_model = get_dropdown_data()
input_devices, output_devices, def_in, def_out = get_audio_devices()

custom_css = """
.green-title h1 { display: inline-block; color: #22c55e !important; margin-right: 8px; }
.red-title h1 { display: inline-block; color: #ef4444 !important; }
.section-gain { background: #1e293b !important; padding: 15px; border-radius: 8px; border-left: 4px solid #3b82f6; margin-bottom: 10px; }
.section-dynamics { background: #1e293b !important; padding: 10px; border-radius: 8px; border-left: 4px solid #06b6d4; }
.section-eq { background: #1e293b !important; padding: 10px; border-radius: 8px; border-left: 4px solid #64748b; }
.section-time { background: #1e293b !important; padding: 10px; border-radius: 8px; border-left: 4px solid #8b5cf6; }
.section-mixer { background: #111827 !important; padding: 15px; border-radius: 8px; border-left: 4px solid #f59e0b; margin-top: 10px; }
"""

js_daw_pipeline = """
() => {
    document.documentElement.classList.add('dark');
    console.log('DAW Shortcut Matrix & Canvas Engine geladen.');
    window.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'SELECT') {
            e.preventDefault();
            document.querySelectorAll('button').forEach((btn) => {
                if (btn.innerText.includes('REC START') || btn.innerText.includes('REC STOP')) btn.click();
            });
        }
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            document.querySelectorAll('button').forEach((btn) => {
                if (btn.innerText.includes('LIVE MODE START') || btn.innerText.includes('LIVE MODE STOP')) btn.click();
            });
        }
        if (e.key >= '1' && e.key <= '9') {
            const trigger = document.querySelector('#sb_play_trigger');
            if (trigger) trigger.click();
        }
    });
}
"""

with gr.Blocks(title="Super Impersonator app", js=js_daw_pipeline, css=custom_css,
               theme=gr.themes.Default()) as app:
    with gr.Row():
        gr.HTML("Super Impersonator app")
        gr.Markdown("### Engine v3.0 DYNAMICS FX // by don24crk // Space: Rec Toggle | Ctrl+Enter: Live Toggle")

    with gr.Row():
        with gr.Column():
            gr.Markdown("## 01 / INPUT SIGNAL & STUDIO FX CHAIN")
            input_audio = gr.Audio(label="Studio I/O (Gesteuert über lokale audio.wav)", type="filepath")
            with gr.Row():
                rvc_model = gr.Dropdown(label="RVC Modell (.pth) [inkl. Unterordner]", choices=available_choices, value=default_model, scale=4)
                refresh_btn = gr.Button("Refresh", scale=1)
            vocal_pitch = gr.Slider(label="Vocal Pitch (Halbtöne)", minimum=-24, maximum=24, step=1, value=0)
            f0_method = gr.Dropdown(label="F0 Pitch Extraction Method", choices=["rmvpe", "harvest", "crepe", "mangio-crepe", "pm", "dio"], value="crepe")
            index_rate = gr.Slider(label="Index Rate (Stimmenähnlichkeit)", minimum=0.0, maximum=1.0, step=0.05, value=1.00)
            protect = gr.Slider(label="Protect (Konsonanten- und Atemschutz)", minimum=0.0, maximum=0.5, step=0.01, value=0.33)
            filter_radius = gr.Slider(label="Filter Radius (F0 Glättung)", minimum=0, maximum=7, step=1, value=3)
            rms_mix_rate = gr.Slider(label="Clean Audio / Autoclean (RMS Mix Rate)", minimum=0.0, maximum=1.0, step=0.05, value=0.25)
            hop_length = gr.Dropdown(label="Crepe Hop Length (Zeitliche Präzision)", choices=["16", "32", "64", "128", "256", "512"], value="128", visible=True)
            studio_preset = gr.Dropdown(label="Studio FX Presets", choices=list(STUDIO_PRESETS.keys()), value="Standard (Manuell)")

            with gr.Column(elem_classes=["section-gain"]):
                gr.Markdown("### 01.A / DIGITAL HARDWARE GAIN & NOISE REDUCTION")
                vocal_gain = gr.Slider(label="Digital Microphone Gain (dB)", minimum=-12, maximum=24, step=0.5, value=0.0)
                noise_red = gr.Slider(label="Noise Reduction Intensity (%)", minimum=0, maximum=100, step=1, value=0)
            with gr.Accordion("01.B / STUDIO DYNAMICS (NOISE GATE)", open=False, elem_classes=["section-dynamics"]):
                gate_threshold = gr.Slider(label="Gate Threshold (dB)", minimum=-60, maximum=0, step=1, value=-50)
                gate_release = gr.Slider(label="Gate Release (ms)", minimum=10, maximum=1000, step=10, value=150)
            with gr.Accordion("01.C / STUDIO DYNAMICS (COMPRESSOR)", open=False, elem_classes=["section-dynamics"]):
                comp_thresh = gr.Slider(label="Compressor Threshold (dB)", minimum=-40, maximum=0, step=1, value=-20)
                comp_ratio = gr.Slider(label="Compressor Ratio", minimum=1.0, maximum=10.0, step=0.5, value=3.5)
                comp_attack = gr.Slider(label="Compressor Attack (ms)", minimum=1, maximum=100, step=1, value=15)
                comp_release = gr.Slider(label="Compressor Release (ms)", minimum=10, maximum=1000, step=10, value=200)
            with gr.Accordion("01.D / STUDIO PARAMETRIC EQ", open=False, elem_classes=["section-eq"]):
                eq_low = gr.Slider(label="Low (100 Hz) (dB)", minimum=-12, maximum=12, step=1, value=0)
                eq_mid = gr.Slider(label="Mid (2.5 kHz) (dB)", minimum=-12, maximum=12, step=1, value=2)
                eq_high = gr.Slider(label="High (10 kHz) (dB)", minimum=-12, maximum=12, step=1, value=1)
            with gr.Accordion("01.E / TIME & AMBIENCE FX", open=False, elem_classes=["section-time"]):
                echo_time = gr.Slider(label="Stereo Delay Time (s)", minimum=0.0, maximum=2.0, step=0.05, value=0.3)
                echo_feedback = gr.Slider(label="Delay Feedback (%)", minimum=0, maximum=100, step=5, value=30)
                reverb_size = gr.Slider(label="Reverb Room Size", minimum=0.0, maximum=1.0, step=0.05, value=0.5)
                fx_mix = gr.Slider(label="FX Wet/Dry Mix (%)", minimum=0, maximum=100, step=5, value=15)
            convert_btn = gr.Button("Musik umwandeln", variant="primary")
            local_output_audio = gr.Audio(label="Konvertiertes Audio (Direkt-Player)")

        with gr.Column():
            gr.Markdown("## 02 / REALTIME MICROPHONE MATRIX")
            input_device = gr.Dropdown(label="Audio Eingangsgerät (Mikrofon)", choices=input_devices, value=def_in)
            output_device = gr.Dropdown(label="Audio Ausgangsgerät (Monitor)", choices=output_devices, value=def_out)
            live_block_size = gr.Slider(label="Live Buffer Size (Niedriger = Weniger Latenz)", minimum=1024, maximum=8192, step=1024, value=2048)
            live_vu_meter = gr.Slider(label="Microphone Signal Input Level (dB)", minimum=-60, maximum=0, value=-60, interactive=False)
            vu_status_txt = gr.Markdown("OFFLINE")
            vocal_wave_state = gr.State(value=[0.0] * 50)
            bgm_wave_state = gr.State(value=[0.0] * 50)
            live_vu_timer = gr.Timer(value=0.1, active=True)

            with gr.Column(elem_classes=["section-mixer"]):
                gr.Markdown("### STUDIO TWO-CHANNEL MIXER & DUCKING MATRIX")
                bgm_file = gr.File(label="Kanal 2: Hintergrundmusik (Instrumental / Beat)", type="filepath")
                bgm_volume = gr.Slider(label="Music Volume (dB)", minimum=-40, maximum=12, step=1, value=0)
                ducking_intensity = gr.Slider(label="Sidechain Ducking Intensity (dB reduction)", minimum=0, maximum=30, step=1, value=12)
            with gr.Accordion("02.B / STUDIO SOUNDBOARD MATRIX", open=False, elem_classes=["section-mixer"]):
                sb_file_1 = gr.File(label="Soundboard Slot 1 (Tastaturbefehl [1-9])", type="filepath")
                sb_volume_1 = gr.Slider(label="Slot 1 Lautstärke (dB)", minimum=-30, maximum=12, value=0)
                sb_pitch_1 = gr.Slider(label="Slot 1 Pitch Shift (Halbtöne)", minimum=-12, maximum=12, value=0, step=0.5)
                sb_filter_1 = gr.Radio(choices=["Bypass", "High-Pass (Clean)", "Low-Pass (Muffled)"], value="Bypass", label="Slot 1 Filter")
                sb_play_trigger = gr.Button("Soundboard-Trigger (Hidden)", visible=False, elem_id="sb_play_trigger")
            with gr.Row():
                start_live = gr.Button("LIVE MODE START", variant="primary")
                stop_live = gr.Button("LIVE MODE STOP", variant="stop")
            gr.Markdown("### STUDIO STREAM RECORDER")
            with gr.Row():
                start_rec_btn = gr.Button("REC START", variant="primary")
                stop_rec_btn = gr.Button("REC STOP", variant="stop")
            live_preview_audio = gr.Audio(label="Letzte Live-Aufnahme (Vorschau)", interactive=False)

    gr.Markdown("## 03 / HARDWARE MONITORING")
    status_output = gr.Textbox(label="System-Matrix Status", interactive=False, lines=6, value="ONLINE\nSystem bereit für Inferenz, FX-Mastering oder Live-Streaming.")
    gr.Markdown("## 04 / MASTER EXPORT ROUTER")
    export_codec = gr.Radio(choices=["WAV", "MP3", "FLAC", "WMA", "VOB"], value="WAV", label="Ziel-Codec")
    mp3_bitrate = gr.Slider(label="MP3 Export Bitrate (kbps)", minimum=96, maximum=320, step=32, value=320)
    sample_rate = gr.Radio(choices=["48000 Hz", "44100 Hz"], value="48000 Hz", label="Studio Samplerate")
    bounce_btn = gr.Button("Bounce Master", variant="primary")
    output_audio = gr.Audio(label="Master Ausgabe")

    studio_preset.change(
        fn=load_preset_values, inputs=[studio_preset],
        outputs=[vocal_gain, noise_red, gate_threshold, gate_release,
                 comp_thresh, comp_ratio, comp_attack, comp_release,
                 eq_low, eq_mid, eq_high, echo_time, echo_feedback,
                 reverb_size, fx_mix],
    )
    live_vu_timer.tick(fn=update_live_vu, inputs=[], outputs=[live_vu_meter, vu_status_txt, vocal_wave_state, bgm_wave_state])
    start_rec_btn.click(fn=start_live_recording, inputs=[], outputs=status_output)
    stop_rec_btn.click(fn=stop_live_recording, inputs=[export_codec, mp3_bitrate], outputs=[live_preview_audio, status_output])
    f0_method.change(fn=update_hop_visibility, inputs=f0_method, outputs=hop_length)
    refresh_btn.click(fn=refresh_models, inputs=[], outputs=rvc_model)
    start_live.click(
        fn=start_live_mode,
        inputs=[rvc_model, vocal_pitch, f0_method, index_rate, input_device,
                output_device, live_block_size, vocal_gain, noise_red,
                gate_threshold, gate_release, comp_thresh, comp_ratio,
                comp_attack, comp_release, eq_low, eq_mid, eq_high,
                echo_time, echo_feedback, reverb_size, fx_mix, bgm_file,
                bgm_volume, ducking_intensity, sb_file_1, sb_volume_1,
                sb_pitch_1, sb_filter_1],
        outputs=status_output,
    )
    stop_live.click(fn=stop_live_mode, inputs=[], outputs=status_output)
    conversion_inputs = [
        input_audio, rvc_model, vocal_pitch, f0_method, index_rate, protect,
        filter_radius, rms_mix_rate, hop_length, vocal_gain, noise_red,
        gate_threshold, gate_release, comp_thresh, comp_ratio, comp_attack,
        comp_release, eq_low, eq_mid, eq_high, echo_time, echo_feedback,
        reverb_size, fx_mix, export_codec, sample_rate, mp3_bitrate,
    ]
    convert_btn.click(fn=process_audio, inputs=conversion_inputs, outputs=[local_output_audio, status_output])
    bounce_btn.click(fn=process_audio, inputs=conversion_inputs, outputs=[output_audio, status_output])


if __name__ == "__main__":
    app.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
