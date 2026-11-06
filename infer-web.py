import base64
import json
import os
import shutil
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import gradio as gr
import numpy as np
import sounddevice as sd
import soundfile as sf


# ---------------------------------------------------------------------------
# Paths and environment
# ---------------------------------------------------------------------------

ENGINE_DIR = Path(__file__).resolve().parent
APPLIO_DIR = Path(
    os.environ.get(
        "APPLIO_DIR",
        r"C:\Users\User\Downloads\ApplioV3.7.1",
    )
)
FFMPEG_BIN_DIR = ENGINE_DIR
MODELS_DIR = ENGINE_DIR / "assets" / "models"
APPLIO_MODELS_DIR = APPLIO_DIR / "rvc" / "models"
RECORDINGS_DIR = ENGINE_DIR / "assets" / "recordings"
TEMP_DIR = ENGINE_DIR / "assets" / "temp"
BACKUP_DIR = Path(r"C:\Backups")
AVATAR_DIR = Path(
    r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine\avatare"
)

ffmpeg_path = FFMPEG_BIN_DIR / "ffmpeg.exe"
if ffmpeg_path.exists():
    os.environ["PATH"] = (
        str(FFMPEG_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")
    )


def inject_applio_paths():
    """Add the configured Applio directories to Python's import path."""
    paths = [
        APPLIO_DIR,
        APPLIO_DIR / "src",
        APPLIO_DIR / ".venv" / "Lib" / "site-packages",
    ]
    for path in paths:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)

    os.environ["CUSTOM_APPLIO_PATH"] = str(APPLIO_DIR)


inject_applio_paths()


# ---------------------------------------------------------------------------
# Shared live-audio state
# ---------------------------------------------------------------------------

live_streaming = False
live_stream = None
is_recording = False
recorded_blocks = []
current_live_vu_level = -60.0


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

STUDIO_PRESETS = {
    "Standard (Manuell)": {
        "vocal_gain": 0.0,
        "noise_red": 0,
        "gate_thresh": -50,
        "gate_release": 150,
        "comp_thresh": -20,
        "comp_ratio": 3.5,
        "comp_attack": 15,
        "comp_release": 200,
        "eq_low": 0,
        "eq_mid": 2,
        "eq_high": 1,
        "echo_time": 0.3,
        "echo_fb": 30,
        "reverb_size": 0.5,
        "fx_mix": 15,
    },
    "Radio-Stimme (Fat Voice)": {
        "vocal_gain": 4.0,
        "noise_red": 40,
        "gate_thresh": -45,
        "gate_release": 120,
        "comp_thresh": -24,
        "comp_ratio": 5.0,
        "comp_attack": 10,
        "comp_release": 150,
        "eq_low": 6,
        "eq_mid": -1,
        "eq_high": 4,
        "echo_time": 0.2,
        "echo_fb": 15,
        "reverb_size": 0.3,
        "fx_mix": 20,
    },
    "Podcast (Warm & Nah)": {
        "vocal_gain": 3.0,
        "noise_red": 60,
        "gate_thresh": -48,
        "gate_release": 200,
        "comp_thresh": -18,
        "comp_ratio": 3.0,
        "comp_attack": 20,
        "comp_release": 250,
        "eq_low": 4,
        "eq_mid": 3,
        "eq_high": 0,
        "echo_time": 0.0,
        "echo_fb": 0,
        "reverb_size": 0.1,
        "fx_mix": 5,
    },
    "Clear Vocal (Kristallklar)": {
        "vocal_gain": 2.0,
        "noise_red": 30,
        "gate_thresh": -52,
        "gate_release": 100,
        "comp_thresh": -15,
        "comp_ratio": 2.5,
        "comp_attack": 8,
        "comp_release": 100,
        "eq_low": -3,
        "eq_mid": 1,
        "eq_high": 6,
        "echo_time": 0.4,
        "echo_fb": 25,
        "reverb_size": 0.6,
        "fx_mix": 25,
    },
}

PRESET_OUTPUT_KEYS = [
    "vocal_gain",
    "noise_red",
    "gate_thresh",
    "gate_release",
    "comp_thresh",
    "comp_ratio",
    "comp_attack",
    "comp_release",
    "eq_low",
    "eq_mid",
    "eq_high",
    "echo_time",
    "echo_fb",
    "reverb_size",
    "fx_mix",
]


def load_preset_values(preset_name):
    """Return Gradio updates in the same order as the preset controls."""
    preset = STUDIO_PRESETS.get(preset_name)
    if preset is None:
        return [gr.update() for _ in PRESET_OUTPUT_KEYS]

    return [gr.update(value=preset[key]) for key in PRESET_OUTPUT_KEYS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_audio_devices():
    """Return device labels and valid default input/output labels."""
    try:
        devices = sd.query_devices()

        input_devices = [
            f"{index}: {device['name']}"
            for index, device in enumerate(devices)
            if device["max_input_channels"] > 0
        ]
        output_devices = [
            f"{index}: {device['name']}"
            for index, device in enumerate(devices)
            if device["max_output_channels"] > 0
        ]

        default_input, default_output = sd.default.device
        default_input_label = None
        default_output_label = None

        if (
            default_input is not None
            and 0 <= default_input < len(devices)
            and devices[default_input]["max_input_channels"] > 0
        ):
            default_input_label = (
                f"{default_input}: {devices[default_input]['name']}"
            )

        if (
            default_output is not None
            and 0 <= default_output < len(devices)
            and devices[default_output]["max_output_channels"] > 0
        ):
            default_output_label = (
                f"{default_output}: {devices[default_output]['name']}"
            )

        if not input_devices:
            input_devices = ["0: No input device available"]
        if not output_devices:
            output_devices = ["0: No output device available"]

        if default_input_label not in input_devices:
            default_input_label = input_devices[0]
        if default_output_label not in output_devices:
            default_output_label = output_devices[0]

        return (
            input_devices,
            output_devices,
            default_input_label,
            default_output_label,
        )
    except Exception as exc:
        print(f"Fehler beim Laden der Audiogeräte: {exc}")
        return (
            ["0: Standard-Eingang"],
            ["0: Standard-Ausgang"],
            "0: Standard-Eingang",
            "0: Standard-Ausgang",
        )


def parse_device_index(device_label):
    """Extract the numeric device index from a 'N: name' label."""
    try:
        return int(str(device_label).split(":", 1)[0])
    except (ValueError, IndexError, AttributeError):
        return None


def scan_rvc_models():
    """Find model paths relative to either configured model directory."""
    models = set()

    for directory in (MODELS_DIR, APPLIO_MODELS_DIR):
        if not directory.exists():
            continue

        for model_path in directory.rglob("*.pth"):
            try:
                models.add(model_path.relative_to(directory).as_posix())
            except ValueError:
                continue

    return sorted(models)


def find_associated_index(model_rel_path):
    """Find an index file whose name contains the model's basename."""
    model_base = Path(model_rel_path).stem.lower()

    for directory in (MODELS_DIR, APPLIO_MODELS_DIR):
        if not directory.exists():
            continue

        for index_path in directory.rglob("*.index"):
            if model_base in index_path.stem.lower():
                return str(index_path)

    return ""


def resolve_model_path(model_rel_path):
    """Resolve a model path while preventing paths outside configured roots."""
    if not model_rel_path:
        return None

    relative_path = Path(model_rel_path)
    if relative_path.is_absolute():
        return None

    for directory in (MODELS_DIR, APPLIO_MODELS_DIR):
        root = directory.resolve()
        candidate = (root / relative_path).resolve()

        try:
            candidate.relative_to(root)
        except ValueError:
            continue

        if candidate.is_file():
            return candidate

    return None


def make_output_path(directory, prefix, extension):
    """Create a unique timestamped output path."""
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return directory / f"{prefix}_{timestamp}.{extension}"


def convert_codec(input_wav, target_codec, mp3_bitrate=320, output_dir=None):
    """Convert a WAV file, falling back to WAV if conversion fails."""
    target_codec = str(target_codec).lower()

    if target_codec not in {"wav", "mp3", "flac", "wma"}:
        raise ValueError(f"Unsupported export format: {target_codec}")

    directory = Path(output_dir) if output_dir else ENGINE_DIR
    prefix = "live_rec" if output_dir else "master_bounce"
    final_path = make_output_path(directory, prefix, target_codec)

    if target_codec == "wav":
        shutil.copy2(input_wav, final_path)
    else:
        try:
            from pydub import AudioSegment

            if ffmpeg_path.exists():
                AudioSegment.converter = str(ffmpeg_path)

            audio = AudioSegment.from_wav(str(input_wav))
            export_options = {}

            if target_codec == "mp3":
                export_options["bitrate"] = f"{int(mp3_bitrate)}k"

            audio.export(
                str(final_path),
                format=target_codec,
                **export_options,
            )
        except Exception as exc:
            print(f"Codec-Fehler ({exc}); nutze WAV-Fallback.")
            final_path = make_output_path(directory, prefix, "wav")
            shutil.copy2(input_wav, final_path)

    if output_dir:
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(final_path, BACKUP_DIR / final_path.name)
        except Exception as exc:
            print(f"Redundanz-Backup fehlgeschlagen: {exc}")

    return str(final_path)


# ---------------------------------------------------------------------------
# Studio effects
# ---------------------------------------------------------------------------

def build_effect_boards(
    vocal_gain,
    gate_thresh,
    gate_release,
    comp_thresh,
    comp_ratio,
    comp_attack,
    comp_release,
    eq_low,
    eq_mid,
    eq_high,
    echo_time,
    echo_feedback,
    reverb_size,
):
    """Build dry and wet Pedalboard chains using available plugins."""
    from pedalboard import (
        Compressor,
        Delay,
        Gain,
        HighShelfFilter,
        LowShelfFilter,
        NoiseGate,
        PeakFilter,
        Pedalboard,
        Reverb,
    )

    dry_board = Pedalboard(
        [
            Gain(gain_db=float(vocal_gain)),
            NoiseGate(
                threshold_db=float(gate_thresh),
                release_ms=float(gate_release),
            ),
            Compressor(
                threshold_db=float(comp_thresh),
                ratio=float(comp_ratio),
                attack_ms=float(comp_attack),
                release_ms=float(comp_release),
            ),
            LowShelfFilter(
                cutoff_frequency_hz=100.0,
                gain_db=float(eq_low),
            ),
            PeakFilter(
                cutoff_frequency_hz=2500.0,
                gain_db=float(eq_mid),
                q=1.0,
            ),
            HighShelfFilter(
                cutoff_frequency_hz=10000.0,
                gain_db=float(eq_high),
            ),
        ]
    )

    wet_board = Pedalboard(
        [
            Delay(
                delay_seconds=float(echo_time),
                feedback=float(echo_feedback) / 100.0,
                mix=1.0,
            ),
            Reverb(
                room_size=float(reverb_size),
                wet_level=1.0,
                dry_level=0.0,
            ),
        ]
    )

    return dry_board, wet_board


def apply_studio_fx(
    input_wav_path,
    vocal_gain,
    noise_red,
    gate_thresh,
    gate_release,
    comp_thresh,
    comp_ratio,
    comp_attack,
    comp_release,
    eq_low,
    eq_mid,
    eq_high,
    echo_time,
    echo_fb,
    reverb_size,
    fx_mix,
    target_sr,
):
    """Apply effects and write a correctly shaped WAV file."""
    del noise_red, target_sr  # Noise reduction is not implemented in this chain.

    try:
        dry_board, wet_board = build_effect_boards(
            vocal_gain,
            gate_thresh,
            gate_release,
            comp_thresh,
            comp_ratio,
            comp_attack,
            comp_release,
            eq_low,
            eq_mid,
            eq_high,
            echo_time,
            echo_fb,
            reverb_size,
        )

        audio, source_sr = sf.read(
            input_wav_path,
            dtype="float32",
            always_2d=True,
        )
        audio = audio.T

        dry = dry_board(audio, source_sr)
        wet = wet_board(dry, source_sr)

        mix = float(np.clip(float(fx_mix) / 100.0, 0.0, 1.0))
        output = dry * (1.0 - mix) + wet * mix
        output = np.clip(output, -1.0, 1.0).T

        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        output_path = make_output_path(TEMP_DIR, "temp_master", "wav")
        sf.write(str(output_path), output, source_sr)

        return str(output_path)
    except Exception as exc:
        print(f"FX-Chain-Fehler: {exc}")
        return input_wav_path


def normalize_rvc_result(result, sample_rate):
    """Normalize common Applio/RVC result forms to a WAV path."""
    if isinstance(result, (str, os.PathLike)):
        result_path = Path(result)
        if result_path.is_file():
            return str(result_path)

    audio_result = result

    if isinstance(result, tuple):
        if len(result) == 2 and isinstance(result[1], (tuple, list)):
            # Common RVC result: (message, (sample_rate, audio))
            audio_result = result[1]
        elif len(result) == 2:
            # Also accept (sample_rate, audio).
            audio_result = result
        else:
            raise RuntimeError("RVC returned an unexpected result tuple.")

    if isinstance(audio_result, (tuple, list)) and len(audio_result) == 2:
        returned_sr, audio = audio_result
        audio = np.asarray(audio)

        if audio.ndim == 1:
            audio = audio[:, None]
        elif audio.ndim == 2:
            # RVC typically returns (samples, channels). Handle channel-first
            # output when the first dimension is clearly the channel count.
            if audio.shape[0] <= 8 and audio.shape[1] > audio.shape[0]:
                audio = audio.T
        else:
            raise RuntimeError(
                f"Unsupported RVC audio dimensions: {audio.ndim}"
            )

        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        output_path = make_output_path(TEMP_DIR, "rvc_output", "wav")
        sf.write(str(output_path), audio, int(returned_sr or sample_rate))
        return str(output_path)

    raise RuntimeError("Unrecognized RVC audio result.")


# ---------------------------------------------------------------------------
# Main inference
# ---------------------------------------------------------------------------

def process_audio(
    input_audio,
    rvc_model_path,
    vocal_pitch,
    f0_method,
    index_rate,
    protect,
    filter_radius,
    rms_mix_rate,
    hop_length,
    vocal_gain,
    noise_red,
    gate_threshold,
    gate_release,
    comp_thresh,
    comp_ratio,
    comp_attack,
    comp_release,
    eq_low,
    eq_mid,
    eq_high,
    echo_time,
    echo_feedback,
    reverb_size,
    fx_mix,
    export_codec,
    sample_rate,
    mp3_bitrate,
):
    inject_applio_paths()

    input_path = Path(input_audio) if input_audio else ENGINE_DIR / "audio.wav"
    if not input_path.is_file():
        return None, f"Fehler: Audiodatei nicht gefunden: {input_path}"

    if not rvc_model_path:
        return None, "Fehler: Kein RVC-Modell ausgewählt."

    model_path = resolve_model_path(rvc_model_path)
    if model_path is None:
        return None, f"Fehler: Modell nicht gefunden: {rvc_model_path}"

    try:
        target_sr = int("".join(filter(str.isdigit, str(sample_rate))))
        if target_sr <= 0:
            raise ValueError(f"Ungültige Sample-Rate: {sample_rate}")

        from rvc.modules.vc.modules import VC

        vc = VC()
        vc.get_vc(str(model_path))

        result = vc.vc_single(
            sid=0,
            input_audio_path=str(input_path),
            f0_up_key=int(vocal_pitch),
            f0_file=None,
            f0_method=str(f0_method),
            file_index=find_associated_index(rvc_model_path),
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

        rvc_wav_path = normalize_rvc_result(result, target_sr)
        master_path = apply_studio_fx(
            rvc_wav_path,
            vocal_gain,
            noise_red,
            gate_threshold,
            gate_release,
            comp_thresh,
            comp_ratio,
            comp_attack,
            comp_release,
            eq_low,
            eq_mid,
            eq_high,
            echo_time,
            echo_feedback,
            reverb_size,
            fx_mix,
            target_sr,
        )

        final_path = convert_codec(
            master_path,
            export_codec,
            mp3_bitrate,
        )

        return final_path, "Studio-Inferenz erfolgreich abgeschlossen!"
    except Exception as exc:
        return None, f"Fehler in der Inferenz-Pipeline: {exc}"


# ---------------------------------------------------------------------------
# Live recording
# ---------------------------------------------------------------------------

def _live_audio_callback(indata, frames, time_info, status):
    """Capture audio blocks and update the input peak meter."""
    global current_live_vu_level

    del frames, time_info

    if status:
        print(f"Live-Stream Status: {status}")

    block = np.asarray(indata, dtype=np.float32).copy()
    if block.ndim == 1:
        block = block[:, None]

    if is_recording:
        recorded_blocks.append(block)

    peak = float(np.max(np.abs(block))) if block.size else 0.0
    if peak > 1e-6:
        current_live_vu_level = max(-60.0, 20.0 * np.log10(peak))
    else:
        current_live_vu_level = -60.0


def update_live_vu():
    """Return the current meter value and status label."""
    if not live_streaming:
        return gr.update(value=-60.0), "OFFLINE"

    level = float(np.clip(current_live_vu_level, -60.0, 0.0))
    status = "MONITORING" if level < -1.0 else "CLIPPING / OVERLOAD"
    return gr.update(value=level), status


def start_live_recording(input_device, output_device, block_size):
    """Start microphone recording. The output device is reserved for future monitoring."""
    global is_recording, recorded_blocks, live_streaming, live_stream

    del output_device

    if live_streaming:
        return "Aufnahme läuft bereits..."

    input_idx = parse_device_index(input_device)
    if input_idx is None:
        return "Fehler: Ungültiges Eingabegerät."

    try:
        device_info = sd.query_devices(input_idx)
        max_channels = int(device_info["max_input_channels"])
        if max_channels <= 0:
            return "Fehler: Das ausgewählte Gerät hat keinen Audioeingang."

        channels = max(1, min(max_channels, 2))
        samplerate = int(device_info.get("default_samplerate") or 44100)

        recorded_blocks = []
        is_recording = True
        live_streaming = True

        live_stream = sd.InputStream(
            device=input_idx,
            channels=channels,
            samplerate=samplerate,
            blocksize=int(block_size),
            dtype="float32",
            callback=_live_audio_callback,
        )
        live_stream.start()

        return "AUFNAHME GESTARTET..."
    except Exception as exc:
        is_recording = False
        live_streaming = False
        live_stream = None
        return f"Fehler beim Starten der Aufnahme: {exc}"


def stop_live_recording(export_codec, mp3_bitrate):
    """Stop recording and export the captured audio."""
    global is_recording, recorded_blocks, live_streaming, live_stream

    is_recording = False
    live_streaming = False
    used_samplerate = 44100

    if live_stream is not None:
        try:
            used_samplerate = int(live_stream.samplerate)
            live_stream.stop()
            live_stream.close()
        except Exception as exc:
            print(f"Fehler beim Schließen des Streams: {exc}")
        finally:
            live_stream = None

    if not recorded_blocks:
        return gr.update(), "Keine Audiodaten aufgezeichnet."

    try:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        temp_wav = make_output_path(TEMP_DIR, "live_rec_temp", "wav")
        audio = np.concatenate(recorded_blocks, axis=0)
        recorded_blocks = []

        sf.write(str(temp_wav), audio, used_samplerate)
        final_file = convert_codec(
            str(temp_wav),
            export_codec,
            mp3_bitrate,
            output_dir=RECORDINGS_DIR,
        )

        return (
            gr.update(value=final_file),
            f"Aufnahme exportiert: {Path(final_file).name}",
        )
    except Exception as exc:
        recorded_blocks = []
        return gr.update(), f"Fehler beim Exportieren: {exc}"


# ---------------------------------------------------------------------------
# Setcard UI helpers
# ---------------------------------------------------------------------------

def get_avatar_base64(model_stem):
    """Find a matching avatar and return it as a data URI."""
    if not AVATAR_DIR.exists():
        return ""

    extensions = [".png", ".jpg", ".jpeg", ".webp"]

    for extension in extensions:
        exact_image = AVATAR_DIR / f"{model_stem}{extension}"
        if exact_image.is_file():
            try:
                encoded = base64.b64encode(exact_image.read_bytes()).decode(
                    "utf-8"
                )
                mime_type = "jpeg" if extension == ".jpg" else extension[1:]
                return f"data:image/{mime_type};base64,{encoded}"
            except OSError:
                pass

    for extension in extensions:
        for image_path in AVATAR_DIR.glob(f"*{extension}"):
            image_stem = image_path.stem.lower()
            model_name = model_stem.lower()

            if model_name in image_stem or image_stem in model_name:
                try:
                    encoded = base64.b64encode(image_path.read_bytes()).decode(
                        "utf-8"
                    )
                    mime_type = "jpeg" if extension == ".jpg" else extension[1:]
                    return f"data:image/{mime_type};base64,{encoded}"
                except OSError:
                    pass

    return ""


def generate_setcards_html(models, selected_model):
    """Generate clickable model cards with optional avatars."""
    if not models:
        return "Keine Modelle im Verzeichnis gefunden."

    artist_meta = {
        "michael_jackson": "Pop-Ikone / King of Pop",
        "barack_obama": "Redner / Ex-Präsident",
        "notorious_big": "Rap-Legende / Hip-Hop",
        "conor_maynard": "Pop-Sänger / YouTuber",
        "donald_trump": "Unternehmer / Politiker",
        "joe_biden": "Staatsmann / Politiker",
        "kalomira": "Pop-Sängerin / Entertainer",
        "miley_cyrus": "Pop-Rock-Sängerin",
        "the_weeknd": "RnB-Künstler / Producer",
    }

    cards = []

    for model in models:
        model_stem = Path(model).stem
        model_lower = model_stem.lower()

        category = "RVC Sprachmodell"
        for key, value in artist_meta.items():
            if key in model_lower or key.replace("_", "") in model_lower:
                category = value
                break

        is_selected = model == selected_model
        background = "#10B981" if is_selected else "#1E293B"
        border = "#34D399" if is_selected else "#475569"
        safe_name = escape(model_stem)
        safe_category = escape(category)
        safe_model = escape(model, quote=True)
        js_model = json.dumps(model)

        avatar_src = get_avatar_base64(model_stem)
        if avatar_src:
            avatar_html = (
                f'<img src="{escape(avatar_src, quote=True)}" '
                f'alt="{safe_name}" '
                'style="width:72px;height:72px;object-fit:cover;'
                'border-radius:50%;margin-bottom:10px;">'
            )
        else:
            avatar_html = (
                '<div style="width:72px;height:72px;border-radius:50%;'
                'display:flex;align-items:center;justify-content:center;'
                'background:#334155;color:#fff;font-size:24px;'
                'font-weight:700;margin-bottom:10px;">'
                f'{escape(model_stem[:1].upper() or "?")}'
                '</div>'
            )

        cards.append(
            f'<button type="button" '
            f'data-model="{safe_model}" '
            f'onclick="window.__selectModel({escape(js_model, quote=True)})" '
            'style="cursor:pointer;text-align:center;color:#fff;'
            'padding:16px;border-radius:14px;border:2px solid '
            f'{border};background:{background};min-width:150px;">'
            f'{avatar_html}'
            f'<div style="font-weight:700;margin-bottom:4px;">{safe_name}</div>'
            f'<div style="font-size:12px;color:#CBD5E1;">{safe_category}</div>'
            "</button>"
        )

    return (
        '<div style="display:flex;flex-wrap:wrap;gap:12px;">'
        + "".join(cards)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Gradio interface
# ---------------------------------------------------------------------------

custom_css = """
#app_title h1 {
    font-size: 2.5rem;
    font-weight: 800;
    text-align: center;
    margin-bottom: 20px;
}
.title-super {
    color: #FFFFFF !important;
}
.title-impersonator {
    color: #10B981 !important;
}
.title-app {
    color: #EF4444 !important;
}
"""

models_list = scan_rvc_models()
initial_model = models_list[0] if models_list else ""

try:
    input_devices, output_devices, default_input, default_output = (
        get_audio_devices()
    )
except Exception:
    input_devices, output_devices = [], []
    default_input, default_output = None, None

force_dark_js = """
() => {
    document.documentElement.classList.add('dark');
    document.body.classList.add('dark');

    window.__selectModel = function(model) {
        const root = document.getElementById('hidden_model_trigger');
        if (!root) return;

        const elements = root.querySelectorAll('input, textarea');
        elements.forEach(function(element) {
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                'value'
            ).set;
            setter.call(element, model);
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
        });
    };
}
"""

with gr.Blocks(
    title="Super Impersonator App 3.0",
    css=custom_css,
    js=force_dark_js,
) as demo:
    gr.HTML(
        """
        <div id="app_title">
            <h1>
                <span class="title-super">SUPER</span>
                <span class="title-impersonator">IMPERSONATOR</span>
                <span class="title-app">APP 3.0</span>
            </h1>
        </div>
        """
    )

    selected_model_state = gr.Textbox(
        value=initial_model,
        visible=False,
        elem_id="hidden_model_trigger",
        interactive=True,
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 1. Inferenz-Setup")

            input_audio = gr.Audio(
                label="Audioquelle",
                type="filepath",
                value=(
                    str(ENGINE_DIR / "audio.wav")
                    if (ENGINE_DIR / "audio.wav").exists()
                    else None
                ),
                interactive=True,
            )

            gr.Markdown("#### RVC-Modell (.pth) wählen")
            setcards_container = gr.HTML(
                value=generate_setcards_html(models_list, initial_model)
            )
            setcard_convert_btn = gr.Button(
                "⚡ MIT GEWÄHLTER SETCARD UMWANDELN",
                variant="primary",
            )
            model_dropdown = gr.Dropdown(
                label="Modell (Alternativ-Auswahl)",
                choices=models_list,
                value=initial_model if initial_model else None,
            )

            with gr.Accordion(
                "⚙️ RVC Kern-Einstellungen & Pitch",
                open=True,
            ):
                vocal_pitch = gr.Slider(
                    label="Pitch Shift (Tonhöhe)",
                    minimum=-24,
                    maximum=24,
                    step=1,
                    value=0,
                )
                f0_method = gr.Dropdown(
                    label="F0 Methode (Algorithmus)",
                    choices=["crepe", "rmvpe", "harvest"],
                    value="crepe",
                )
                index_rate = gr.Slider(
                    label="Index Rate (Klangtreue)",
                    minimum=0.0,
                    maximum=1.0,
                    value=1.0,
                )
                protect = gr.Slider(
                    label="Protect (Konsonanten-Schutz)",
                    minimum=0.0,
                    maximum=0.5,
                    value=0.33,
                )

                with gr.Row():
                    filter_radius = gr.Slider(
                        label="Glättungsradius",
                        minimum=0,
                        maximum=7,
                        value=3,
                    )
                    rms_mix_rate = gr.Slider(
                        label="Volume Envelope",
                        minimum=0.0,
                        maximum=1.0,
                        value=0.25,
                    )
                    hop_length = gr.Dropdown(
                        label="Hop Length (Nur für Crepe)",
                        choices=["64", "128", "256"],
                        value="128",
                    )

            gr.Markdown("### 🎛️ Studio-Effektkette")
            studio_preset = gr.Dropdown(
                label="Effekt Presets (Schnellauswahl)",
                choices=list(STUDIO_PRESETS),
                value="Standard (Manuell)",
            )

            with gr.Accordion(
                "🎙️ Eingangspegel & Dynamik (Gate/Comp)",
                open=False,
            ):
                vocal_gain = gr.Slider(
                    label="Mic Gain / Aufholverstärkung (dB)",
                    minimum=-12,
                    maximum=24,
                    value=0.0,
                )
                noise_red = gr.Slider(
                    label="Rauschunterdrückung (%)",
                    minimum=0,
                    maximum=100,
                    value=0,
                )

                with gr.Group():
                    gr.Markdown("Noise Gate (Rausch-Sperre)")
                    gate_threshold = gr.Slider(
                        label="Gate Thresh (Schwellenwert dB)",
                        minimum=-60,
                        maximum=0,
                        value=-50,
                    )
                    gate_release = gr.Slider(
                        label="Gate Release (Abfallzeit ms)",
                        minimum=50,
                        maximum=1000,
                        value=150,
                    )

                with gr.Group():
                    gr.Markdown("Kompressor (Pegelausgleich)")
                    comp_thresh = gr.Slider(
                        label="Comp Thresh (Schwellenwert dB)",
                        minimum=-40,
                        maximum=0,
                        value=-20,
                    )
                    comp_ratio = gr.Slider(
                        label="Comp Ratio (Verhältnis)",
                        minimum=1.0,
                        maximum=10.0,
                        value=3.5,
                    )
                    comp_attack = gr.Slider(
                        label="Comp Attack (Ansprechzeit ms)",
                        minimum=1,
                        maximum=100,
                        value=15,
                    )
                    comp_release = gr.Slider(
                        label="Comp Release (Rücklaufzeit ms)",
                        minimum=10,
                        maximum=1000,
                        value=200,
                    )

            with gr.Accordion(
                "🎚️ Frequenz-Tuning (3-Band EQ)",
                open=False,
            ):
                eq_low = gr.Slider(
                    label="Bass-Bereich (EQ Low dB)",
                    minimum=-12,
                    maximum=12,
                    value=0,
                )
                eq_mid = gr.Slider(
                    label="Stimm-Präsenz (EQ Mid dB)",
                    minimum=-12,
                    maximum=12,
                    value=2,
                )
                eq_high = gr.Slider(
                    label="Brillanz / Höhen (EQ High dB)",
                    minimum=-12,
                    maximum=12,
                    value=1,
                )

            with gr.Accordion(
                "🌌 Raumklang & Zeiteffekte (Delay/Reverb)",
                open=False,
            ):
                with gr.Group():
                    gr.Markdown("Echo / Delay")
                    echo_time = gr.Slider(
                        label="Delay Time (Verzögerung s)",
                        minimum=0.0,
                        maximum=2.0,
                        value=0.3,
                    )
                    echo_feedback = gr.Slider(
                        label="Delay Feedback (Wiederholungen %)",
                        minimum=0,
                        maximum=100,
                        value=30,
                    )

                with gr.Group():
                    gr.Markdown("Hall / Reverb")
                    reverb_size = gr.Slider(
                        label="Reverb Room Size (Raumgröße)",
                        minimum=0.0,
                        maximum=1.0,
                        value=0.5,
                    )
                    fx_mix = gr.Slider(
                        label="Gesamter FX-Mixanteil (Wet %)",
                        minimum=0,
                        maximum=100,
                        value=15,
                    )

        with gr.Column(scale=1):
            gr.Markdown("### 2. Live-Audio & Aufzeichnung")

            input_device = gr.Dropdown(
                label="Mikrofon-Eingang",
                choices=input_devices,
                value=default_input,
            )
            output_device = gr.Dropdown(
                label="Monitor-Ausgang (für zukünftiges Monitoring)",
                choices=output_devices,
                value=default_output,
            )
            live_block_size = gr.Slider(
                label="Buffer-Blockgröße",
                minimum=1024,
                maximum=4096,
                step=1024,
                value=2048,
            )
            live_vu_meter = gr.Slider(
                label="Eingangspegel (dB)",
                minimum=-60,
                maximum=0,
                value=-60,
                interactive=False,
            )
            vu_status_txt = gr.Markdown("OFFLINE")

            bgm_file = gr.File(
                label="Hintergrundmusik (Beat/Track)",
                type="filepath",
            )
            bgm_volume = gr.Slider(
                label="Musik Lautstärke (dB)",
                minimum=-40,
                maximum=12,
                value=0,
            )
            ducking_intensity = gr.Slider(
                label="Sidechain Ducking (dB)",
                minimum=0,
                maximum=30,
                value=12,
            )

            with gr.Row():
                start_rec_btn = gr.Button("REC START", variant="primary")
                stop_rec_btn = gr.Button("REC STOP", variant="stop")

            live_preview_audio = gr.Audio(
                label="Live-Aufnahme-Playback",
                interactive=False,
            )

            gr.Markdown("### 3. Master Export & Format")
            export_codec = gr.Radio(
                ["WAV", "MP3", "FLAC", "WMA"],
                value="WAV",
                label="Exportformat",
            )
            mp3_bitrate = gr.Slider(
                label="Bitrate (kbps)",
                minimum=128,
                maximum=320,
                step=32,
                value=320,
            )
            sample_rate = gr.Radio(
                ["44100 Hz", "48000 Hz"],
                value="48000 Hz",
                label="Sample-Rate",
            )

            bounce_btn = gr.Button(
                "BOUNCE SKRIPT & MASTER EXPORT",
                variant="primary",
            )
            output_audio = gr.Audio(label="Master-Ausgabedatei")
            status_output = gr.Textbox(
                label="System-Log",
                lines=4,
                value="System bereit.",
            )

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    def on_model_select(model):
        if not model:
            return generate_setcards_html(models_list, None), gr.update()

        return (
            generate_setcards_html(models_list, model),
            gr.update(value=model),
        )

    selected_model_state.change(
        fn=on_model_select,
        inputs=[selected_model_state],
        outputs=[setcards_container, model_dropdown],
    )

    def on_dropdown_select(model):
        return model if model else gr.update()

    model_dropdown.change(
        fn=on_dropdown_select,
        inputs=[model_dropdown],
        outputs=[selected_model_state],
    )

    studio_preset.change(
        fn=load_preset_values,
        inputs=[studio_preset],
        outputs=[
            vocal_gain,
            noise_red,
            gate_threshold,
            gate_release,
            comp_thresh,
            comp_ratio,
            comp_attack,
            comp_release,
            eq_low,
            eq_mid,
            eq_high,
            echo_time,
            echo_feedback,
            reverb_size,
            fx_mix,
        ],
    )

    live_vu_timer = gr.Timer(value=0.1, active=True)
    live_vu_timer.tick(
        fn=update_live_vu,
        outputs=[live_vu_meter, vu_status_txt],
    )

    start_rec_btn.click(
        fn=start_live_recording,
        inputs=[input_device, output_device, live_block_size],
        outputs=status_output,
    )

    stop_rec_btn.click(
        fn=stop_live_recording,
        inputs=[export_codec, mp3_bitrate],
        outputs=[live_preview_audio, status_output],
    )

    conversion_inputs = [
        input_audio,
        selected_model_state,
        vocal_pitch,
        f0_method,
        index_rate,
        protect,
        filter_radius,
        rms_mix_rate,
        hop_length,
        vocal_gain,
        noise_red,
        gate_threshold,
        gate_release,
        comp_thresh,
        comp_ratio,
        comp_attack,
        comp_release,
        eq_low,
        eq_mid,
        eq_high,
        echo_time,
        echo_feedback,
        reverb_size,
        fx_mix,
        export_codec,
        sample_rate,
        mp3_bitrate,
    ]

    bounce_btn.click(
        fn=process_audio,
        inputs=conversion_inputs,
        outputs=[output_audio, status_output],
        show_progress="full",
    )

    setcard_convert_btn.click(
        fn=process_audio,
        inputs=conversion_inputs,
        outputs=[output_audio, status_output],
        show_progress="full",
    )


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
    )
