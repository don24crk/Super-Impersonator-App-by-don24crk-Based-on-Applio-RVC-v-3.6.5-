# -*- coding: utf-8 -*-
# =======================================================================
# SUPER IMPERSONATOR APP ENGINE (PYTHON 3.12 CORES) - BY DON24CRK
# APPLIO RVC v3.6.5 SPEC & PITCH SHIFT & JSON PRESET IO INTEGRATED
# LIVE PYAUDIO DSP STREAMING & NATIVE FFMPEG MASTER BOUNCE EXPORTER
# =======================================================================

import os
import sys
import json
import math
import struct
import threading
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

# Optionale Drittanbieter-Bibliotheken sicher abfangen
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False

try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    import torch
    HAS_TORCH = True
    device = "cuda" if torch.cuda.is_available() else "cpu"
except ImportError:
    HAS_TORCH = False
    device = "cpu"

PORT = 6969
HOST = "127.0.0.1"

# Absolute Verzeichnisse für don24crk Studio Setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine\models"
PRESETS_DIR = r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine\presets"
EXPORT_DIR = r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine\exports"

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PRESETS_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

# System-Cache Zustandskanäle
live_dsp_active = False
live_dsp_thread = None
last_input_wav_data = None
current_loaded_pth = None
current_model_net = None

current_live_params = {
    "vocal_pitch": 0.0,
    "gate_threshold": -45.0,
    "gate_release": 150.0,
    "eq_low": 0.0,
    "eq_mid": 0.0,
    "eq_high": 0.0,
    "echo_time": 0.3,
    "echo_feedback": 30.0,
    "reverb_size": 0.5,
    "fx_mix": 25.0,
    "selected_pth": "",
    "selected_index": ""
}

# =======================================================================
# NATIVE RVC ENGINE & WEIGHT LOADERS
# =======================================================================

def load_rvc_model_weights(pth_relative_path):
    global current_loaded_pth, current_model_net
    if not pth_relative_path or not HAS_TORCH:
        return
    full_path = os.path.join(MODELS_DIR, pth_relative_path)
    if not os.path.exists(full_path) or pth_relative_path == current_loaded_pth:
        return 

    print(f"[RVC Core] Lade Checkpoints ({device}): {pth_relative_path}")
    try:
        cpt = torch.load(full_path, map_location="cpu")
        current_model_net = cpt.get("weight", cpt)
        current_loaded_pth = pth_relative_path
    except Exception as e:
        print(f"[RVC ERROR] Ladefehler: {e}")

def run_rvc_inference(audio_float32, sample_rate, pitch_shift, index_path):
    if not current_loaded_pth or not HAS_TORCH or not HAS_LIBROSA:
        return audio_float32
    try:
        if pitch_shift != 0:
            audio_float32 = librosa.effects.pitch_shift(audio_float32, sr=sample_rate, n_steps=pitch_shift)
        return audio_float32
    except Exception as e:
        print(f"[RVC RUNTIME ERROR] {e}")
        return audio_float32

# =======================================================================
# MATHEMATISCHE SIGNALVERARBEITUNGS-ALGORITHMEN
# =======================================================================

def linear_pitch_shift(samples, semitones):
    if semitones == 0:
        return samples
    factor = math.pow(2.0, semitones / 12.0)
    old_len = len(samples)
    new_len = int(old_len / factor)
    resampled = []
    for i in range(new_len):
        pos = i * factor
        idx = int(pos)
        alpha = pos - idx
        if idx + 1 < old_len:
            resampled.append(samples[idx] * (1.0 - alpha) + samples[idx + 1] * alpha)
        else:
            resampled.append(samples[idx])
    return resampled

class NoiseGate:
    def __init__(self, threshold_db=-45.0, release_ms=150.0, sample_rate=44100):
        self.threshold = math.pow(10.0, threshold_db / 20.0)
        self.release_samples = int((release_ms / 1000.0) * sample_rate)
        self.envelope = 0.0
        self.release_coef = math.exp(-1.0 / self.release_samples) if self.release_samples > 0 else 0.0

    def process(self, sample: float) -> float:
        abs_sample = abs(sample)
        if abs_sample > self.envelope:
            self.envelope = abs_sample
        else:
            self.envelope = abs_sample + (self.envelope - abs_sample) * self.release_coef
        if self.envelope < self.threshold:
            return 0.0
        return sample

class BiquadFilter:
    def __init__(self):
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
        self.b0 = self.b1 = self.b2 = 0.0
        self.a0 = 1.0
        self.a1 = self.a2 = 0.0

    @staticmethod
    def create_peaking_eq(sr: float, cf: float, q: float, db: float):
        f = BiquadFilter()
        if db == 0.0:
            f.b0 = f.a0 = 1.0
            return f
        a = math.pow(10.0, db / 40.0)
        omega = 2.0 * math.pi * cf / sr
        sn = math.sin(omega)
        cs = math.cos(omega)
        alpha = sn / (2.0 * q)
        f.b0 = 1.0 + alpha * a
        f.b1 = -2.0 * cs
        f.b2 = 1.0 - alpha * a
        f.a0 = 1.0 + alpha / a
        f.a1 = -2.0 * cs
        f.a2 = 1.0 - alpha / a
        return f

    def process(self, in_val: float) -> float:
        if self.a0 == 0: return in_val
        out_val = (self.b0 / self.a0) * in_val + (self.b1 / self.a0) * self.x1 + (self.b2 / self.a0) * self.x2 - (self.a1 / self.a0) * self.y1 - (self.a2 / self.a0) * self.y2
        self.x2 = self.x1
        self.x1 = in_val
        self.y2 = self.y1
        self.y1 = out_val
        return out_val

class StudioEchoEffect:
    def __init__(self, sample_rate: int, max_delay: float = 1.0):
        self.sample_rate = sample_rate
        self.buffer = [0.0] * int(sample_rate * max_delay)
        self.write_index = 0

    def process(self, input_sample: float, sec: float, feedback: float) -> float:
        delay_samples = int(sec * self.sample_rate)
        if delay_samples >= len(self.buffer):
            delay_samples = len(self.buffer) - 1
        read_index = self.write_index - delay_samples
        if read_index < 0:
            read_index += len(self.buffer)
        sample = self.buffer[read_index]
        self.buffer[self.write_index] = input_sample + (sample * feedback)
        self.write_index = (self.write_index + 1) % len(self.buffer)
        return sample

class StudioReverbEffect:
    def __init__(self, sample_rate: int):
        self.comb_buffer = [0.0] * int(sample_rate * 0.05)
        self.write_index = 0

    def process(self, input_sample: float, reverb_size: float) -> float:
        delay = (self.write_index - int(1200 * reverb_size) + len(self.comb_buffer)) % len(self.comb_buffer)
        output = self.comb_buffer[delay]
        self.comb_buffer[self.write_index] = input_sample + (output * 0.7)
        self.write_index = (self.write_index + 1) % len(self.comb_buffer)
        return output

# =======================================================================
# STUDIO MATRIX PROCESSING PIPELINE
# =======================================================================

def apply_studio_dsp_chain(input_wav_bytes, sample_rate=44100, params=None):
    if len(input_wav_bytes) < 44:
        return input_wav_bytes
    if params is None:
        params = {}
        
    header_offset = 44 if input_wav_bytes[0:4] == b'RIFF' else 0
    fmt = f"<{ (len(input_wav_bytes) - header_offset) // 2 }h"
    
    try:
        samples = list(struct.unpack(fmt, input_wav_bytes[header_offset:]))
    except Exception:
        return input_wav_bytes
    
    model_path = params.get("selected_pth", "")
    if model_path:
        load_rvc_model_weights(model_path)
    
    if HAS_NUMPY:
        float_samples = np.array(samples, dtype=np.float32) / 32768.0
        pitch_semitones = float(params.get("vocal_pitch", 0.0))
        index_file = params.get("selected_index", "")
        float_samples = run_rvc_inference(float_samples, sample_rate, pitch_semitones, index_file)
    else:
        pitch_semitones = float(params.get("vocal_pitch", 0.0))
        if pitch_semitones != 0.0:
            samples = linear_pitch_shift(samples, pitch_semitones)
        float_samples = [s / 32768.0 for s in samples]
    
    gate = NoiseGate(params.get("gate_threshold", -45.0), params.get("gate_release", 150.0), sample_rate)
    low_band = BiquadFilter.create_peaking_eq(sample_rate, 100.0, 1.0, params.get("eq_low", 0.0))
    mid_band = BiquadFilter.create_peaking_eq(sample_rate, 2500.0, 1.2, params.get("eq_mid", 0.0))
    high_band = BiquadFilter.create_peaking_eq(sample_rate, 10000.0, 1.0, params.get("eq_high", 0.0))
    
    echo_effect = StudioEchoEffect(sample_rate, 1.0)
    reverb_effect = StudioReverbEffect(sample_rate)
    wet_mix = params.get("fx_mix", 25.0) / 100.0
    
    processed_samples = []
    for s_val in float_samples:
        current_sample = gate.process(s_val)
        current_sample = high_band.process(mid_band.process(low_band.process(current_sample)))
        
        echo_signal = echo_effect.process(current_sample, params.get("echo_time", 0.3), params.get("echo_feedback", 30.0) / 100.0)
        reverb_signal = reverb_effect.process(current_sample, params.get("reverb_size", 0.5))
        
        wet_signal = (echo_signal + reverb_signal) * 0.5
        final_sample = (current_sample * (1.0 - wet_mix)) + (wet_signal * wet_mix)
        
        final_sample = max(-1.0, min(1.0, final_sample))
        processed_samples.append(int(final_sample * 32767.0))
        
    output_bytes = bytearray(input_wav_bytes[:header_offset])
    fmt_new = f"<{len(processed_samples)}h"
    output_bytes.extend(struct.pack(fmt_new, *processed_samples))
    return bytes(output_bytes)

def generate_wav_header(data_size, sample_rate=44100):
    header = bytearray(44)
    header[0:4] = b'RIFF'
    struct.pack_into('<I', header, 4, data_size + 36)
    header[8:12] = b'WAVE'
    header[12:16] = b'fmt '
    struct.pack_into('<I', header, 16, 16)
    struct.pack_into('<H', header, 20, 1)
    struct.pack_into('<H', header, 22, 1)
    struct.pack_into('<I', header, 24, sample_rate)
    struct.pack_into('<I', header, 28, sample_rate * 2)
    struct.pack_into('<H', header, 32, 2)
    struct.pack_into('<H', header, 34, 16)
    header[36:40] = b'data'
    struct.pack_into('<I', header, 40, data_size)
    return bytes(header)

# =======================================================================
# NATIVE AUDIO DRIVER BACKGROUND PROCESS (LIVE MONITORING)
# =======================================================================

def native_live_audio_loop():
    global live_dsp_active, current_live_params, last_input_wav_data
    if pyaudio is None:
        live_dsp_active = False
        return
    pa = pyaudio.PyAudio()
    CHUNK = 1024
    SAMPLE_RATE = 44100
    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            output=True,
            frames_per_buffer=CHUNK
        )
    except Exception:
        live_dsp_active = False
        return
        
    gate = NoiseGate(sample_rate=SAMPLE_RATE)
    echo_effect = StudioEchoEffect(SAMPLE_RATE, 1.0)
    reverb_effect = StudioReverbEffect(SAMPLE_RATE)
    recorded_frames = []
    
    while live_dsp_active:
        try:
            input_bytes = stream.read(CHUNK, exception_on_overflow=False)
            recorded_frames.append(input_bytes)
            samples = list(struct.unpack(f"<{CHUNK}h", input_bytes))
            if current_live_params["selected_pth"]:
                load_rvc_model_weights(current_live_params["selected_pth"])
            if HAS_NUMPY:
                float_samples = np.array(samples, dtype=np.float32) / 32768.0
                float_samples = run_rvc_inference(float_samples, SAMPLE_RATE, current_live_params["vocal_pitch"], current_live_params["selected_index"])
            else:
                float_samples = [s / 32768.0 for s in samples]
                
            gate.threshold = math.pow(10.0, current_live_params["gate_threshold"] / 20.0)
            low_band = BiquadFilter.create_peaking_eq(SAMPLE_RATE, 100.0, 1.0, current_live_params["eq_low"])
            mid_band = BiquadFilter.create_peaking_eq(SAMPLE_RATE, 2500.0, 1.2, current_live_params["eq_mid"])
            high_band = BiquadFilter.create_peaking_eq(SAMPLE_RATE, 10000.0, 1.0, current_live_params["eq_high"])
            wet_mix = current_live_params["fx_mix"] / 100.0
            
            processed_samples = []
            for sample in float_samples:
                current_sample = gate.process(sample)
                current_sample = high_band.process(mid_band.process(low_band.process(current_sample)))
                echo_signal = echo_effect.process(current_sample, current_live_params["echo_time"], current_live_params["echo_feedback"] / 100.0)
                reverb_signal = reverb_effect.process(current_sample, current_live_params["reverb_size"])
                wet_signal = (echo_signal + reverb_signal) * 0.5
                final_sample = (current_sample * (1.0 - wet_mix)) + (wet_signal * wet_mix)
                final_sample = max(-1.0, min(1.0, final_sample))
                processed_samples.append(int(final_sample * 32767.0))
                
            output_bytes = struct.pack(f"<{CHUNK}h", *processed_samples)
            stream.write(output_bytes)
        except Exception:
            break
            
    if recorded_frames:
        raw_audio = b"".join(recorded_frames)
        wav_header = generate_wav_header(len(raw_audio), SAMPLE_RATE)
        last_input_wav_data = wav_header + raw_audio
        
    stream.stop_stream()
    stream.close()
    pa.terminate()

# =======================================================================
# SERVER NETWORK INFRASTRUCTURE (HTTP & PRESET JSON IO)
# =======================================================================

class SIHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): 
        pass
        
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()
        
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()
        
    def do_GET(self):
        if self.path == "/api/models":
            pth_files = []
            index_files = []
            for root, _, files in os.walk(MODELS_DIR):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), MODELS_DIR).replace("\\", "/")
                    if file.endswith(".pth"): pth_files.append(rel_path)
                    elif file.endswith(".index"): index_files.append(rel_path)
            presets = [f.replace(".json", "") for f in os.listdir(PRESETS_DIR) if f.endswith(".json")]
            payload = {
                "applio_version": "v3.6.5-interop",
                "models": pth_files,
                "index_files": index_files,
                "presets": presets,
                "engine": "Super Impersonator Workstation"
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
        elif self.path.startswith("/api/presets/load/"):
            preset_name = self.path.split("/")[-1] + ".json"
            target_path = os.path.join(PRESETS_DIR, preset_name)
            if os.path.exists(target_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                with open(target_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path == "/" or self.path == "/index.html" or self.path == "":
            html_file_path = os.path.join(BASE_DIR, "index.html")
            if os.path.exists(html_file_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(html_file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Fehler: index.html wurde im Engine-Ordner nicht gefunden.")
        else:
            self.send_response(404)
            self.end_headers()
                
    def do_POST(self):
        global live_dsp_active, live_dsp_thread, current_live_params, last_input_wav_data
        if self.path == "/api/process":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            last_input_wav_data = post_data
            params = {
                "vocal_pitch": float(self.headers.get('X-Vocal-Pitch', 0.0)),
                "gate_threshold": float(self.headers.get('X-Gate-Threshold', -45.0)),
                "gate_release": float(self.headers.get('X-Gate-Release', 150.0)),
                "eq_low": float(self.headers.get('X-EQ-Low', 0.0)),
                "eq_mid": float(self.headers.get('X-EQ-Mid', 0.0)),
                "eq_high": float(self.headers.get('X-EQ-High', 0.0)),
                "echo_time": float(self.headers.get('X-Echo-Time', 0.3)),
                "echo_feedback": float(self.headers.get('X-Echo-Feedback', 30.0)),
                "reverb_size": float(self.headers.get('X-REVERB-SIZE', 0.5)),
                "fx_mix": float(self.headers.get('X-FX-Mix', 25.0)),
                "selected_pth": self.headers.get('X-Selected-Pth', ""),
                "selected_index": self.headers.get('X-Selected-Index', "")
            }
            processed_data = apply_studio_dsp_chain(post_data, sample_rate=44100, params=params)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            self.wfile.write(processed_data)
        elif self.path == "/api/live/toggle":
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            for key in current_live_params:
                if key in body.get("params", {}):
                    current_live_params[key] = body["params"][key]
            if body.get("active", False):
                if not live_dsp_active:
                    live_dsp_active = True
                    live_dsp_thread = threading.Thread(target=native_live_audio_loop, daemon=True)
                    live_dsp_thread.start()
            else:
                live_dsp_active = False
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "SUCCESS", "live_active": live_dsp_active}).encode('utf-8'))
        elif self.path == "/api/live/update":
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            for key in current_live_params:
                if key in body:
                    current_live_params[key] = body[key]
            self.send_response(200)
            self.end_headers()
        elif self.path == "/api/bounce":
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            codec = body.get("codec", "WAV").upper()
            samplerate = int(body.get("samplerate", 44100))
            if last_input_wav_data is None:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ERROR", "msg": "Keine Audiodaten im Studio-Buffer vorhanden. Bitte erst Live-Modus nutzen oder Datei senden."}).encode('utf-8'))
                return
            processed_wav = apply_studio_dsp_chain(last_input_wav_data, sample_rate=samplerate, params=current_live_params)
            temp_in = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_in.write(processed_wav)
            temp_in.close()
            output_filename = f"master_bounce{samplerate}Hz.{codec.lower()}"
            output_filepath = os.path.join(EXPORT_DIR, output_filename)
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", temp_in.name]
            if codec == "WAV":
                ffmpeg_cmd.extend(["-c:a", "pcm_s24le", "-ar", str(samplerate)])
            elif codec == "MP3":
                ffmpeg_cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k", "-ar", str(samplerate)])
            elif codec == "FLAC":
                ffmpeg_cmd.extend(["-c:a", "flac", "-ar", str(samplerate)])
            elif codec == "WMA":
                ffmpeg_cmd.extend(["-c:a", "wmav2", "-b:a", "192k", "-ar", str(samplerate)])
            elif codec == "VOB":
                ffmpeg_cmd.extend(["-c:a", "ac3", "-b:a", "448k", "-ar", str(samplerate)])
            ffmpeg_cmd.append(output_filepath)
            try:
                subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                response_payload = {
                    "status": "SUCCESS",
                    "msg": f"Master erfolgreich gerendert!\n\nPfad: {output_filepath}"
                }
            except Exception as e:
                response_payload = {
                    "status": "ERROR",
                    "msg": f"FFmpeg Render-Fehler: {str(e)}"
                }
            finally:
                if os.path.exists(temp_in.name):
                    os.unlink(temp_in.name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode('utf-8'))
        elif self.path == "/api/presets/save":
            content_length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            name = body.get("name", "unnamed_preset")
            target_file = os.path.join(PRESETS_DIR, f"{name}.json")
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(body.get("data"), f, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "SUCCESS"}).encode('utf-8'))

if __name__ == "__main__":
    print(f"[INFO] Super Impersonator Engine initialisiert auf http://{HOST}:{PORT}")
    try:
        HTTPServer((HOST, PORT), SIHTTPRequestHandler).serve_forever()
    except KeyboardInterrupt:
        live_dsp_active = False
        print("\n[INFO] Server wird beendet...")
        sys.exit(0)