# -*- coding: utf-8 -*-
# =======================================================================
# SUPER IMPERSONATOR APP ENGINE (PYTHON 3.12 CORES) - BY DON24CRK
# APPLIO RVC v3.6.5 SPEC & PITCH SHIFT & JSON PRESET IO INTEGRATED
# =======================================================================

import os
import sys
import json
import math
import struct
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 6969
HOST = "127.0.0.1"

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PRESETS_DIR = r"C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine\presets"

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PRESETS_DIR, exist_ok=True)

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
    
    # Live Vocal Pitch Transformation
    pitch_semitones = float(params.get("vocal_pitch", 0.0))
    if pitch_semitones != 0.0:
        samples = linear_pitch_shift(samples, pitch_semitones)
        fmt = f"<{len(samples)}h"
        
    gate = NoiseGate(params.get("gate_threshold", -45.0), params.get("gate_release", 150.0), sample_rate)
    low_band = BiquadFilter.create_peaking_eq(sample_rate, 100.0, 1.0, params.get("eq_low", 0.0))
    mid_band = BiquadFilter.create_peaking_eq(sample_rate, 2500.0, 1.2, params.get("eq_mid", 0.0))
    high_band = BiquadFilter.create_peaking_eq(sample_rate, 10000.0, 1.0, params.get("eq_high", 0.0))
    
    echo_effect = StudioEchoEffect(sample_rate, 1.0)
    reverb_effect = StudioReverbEffect(sample_rate)
    wet_mix = params.get("fx_mix", 25.0) / 100.0
    
    processed_samples = []
    for sample in samples:
        input_sample = sample / 32768.0
        current_sample = gate.process(input_sample)
        current_sample = high_band.process(mid_band.process(low_band.process(current_sample)))
        
        echo_signal = echo_effect.process(current_sample, params.get("echo_time", 0.3), params.get("echo_feedback", 30.0) / 100.0)
        reverb_signal = reverb_effect.process(current_sample, params.get("reverb_size", 0.5))
        
        wet_signal = (echo_signal + reverb_signal) * 0.5
        final_sample = (current_sample * (1.0 - wet_mix)) + (wet_signal * wet_mix)
        
        final_sample = max(-1.0, min(1.0, final_sample))
        processed_samples.append(int(final_sample * 32767.0))
        
    output_bytes = bytearray(input_wav_bytes[:header_offset])
    output_bytes.extend(struct.pack(fmt, *processed_samples))
    return bytes(output_bytes)

# =======================================================================
# SERVER NETWORK INFRASTRUCTURE (HTTP & PRESET JSON IO)
# =======================================================================

class SIHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

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
                    rel = os.path.relpath(os.path.join(root, file), MODELS_DIR).replace("\\", "/")
                    if file.endswith(".pth"): pth_files.append(rel)
                    elif file.endswith(".index"): index_files.append(rel)
            
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
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), "rb") as f:
                self.wfile.write(f.read())

    def do_POST(self):
        if self.path == "/api/process":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            params = {
                "vocal_pitch": float(self.headers.get('X-Vocal-Pitch', 0.0)),
                "gate_threshold": float(self.headers.get('X-Gate-Threshold', -45.0)),
Verwende Code mit Vorsicht.
"gate_release": float(self.headers.get('X-Gate-Release', 150.0)),
"eq_low": float(self.headers.get('X-EQ-Low', 0.0)),
"eq_mid": float(self.headers.get('X-EQ-Mid', 0.0)),
"eq_high": float(self.headers.get('X-EQ-High', 0.0)),
"echo_time": float(self.headers.get('X-Echo-Time', 0.3)),
"echo_feedback": float(self.headers.get('X-Echo-Feedback', 30.0)),
"reverb_size": float(self.headers.get('X-Reverb-Size', 0.5)),
"fx_mix": float(self.headers.get('X-FX-Mix', 25.0))
}
processed_data = apply_studio_dsp_chain(post_data, sample_rate=44100, params=params)
self.send_response(200)
self.send_header("Content-Type", "audio/wav")
self.end_headers()
self.wfile.write(processed_data)
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
if name == "main":
print(f"[INFO] Super Impersonator Engine initialisiert auf http://{HOST}:{PORT}")
HTTPServer((HOST, PORT), SIHTTPRequestHandler).serve_forever()