import os
import sys
import glob
import shutil
import gradio as gr

# Pfade definieren
ENGINE_DIR = os.getcwd()
APPLIO_DIR = r"C:\Users\User\Downloads\ApplioV3.7.1"

# Applio-Hauptverzeichnis und dessen Bibliotheken in den Python-Suchpfad aufnehmen
if os.path.exists(APPLIO_DIR):
    sys.path.append(APPLIO_DIR)
    os.environ["CUSTOM_APPLIO_PATH"] = APPLIO_DIR
    print(f"🟢 Applio-Core erfolgreich verknüpft: {APPLIO_DIR}")
else:
    print(f"⚠️ Warnung: Applio-Verzeichnis nicht gefunden unter {APPLIO_DIR}")

# Lokales Modell-Verzeichnis
MODELS_DIR = os.path.join(ENGINE_DIR, "assets", "models")

def scan_rvc_models():
    """Scannt das assets/models Verzeichnis sowie alle Unterordner nach .pth Modellen."""
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR, exist_ok=True)
    
    models = []
    for root, dirs, files in os.walk(MODELS_DIR):
        for file in files:
            if file.endswith(".pth"):
                rel_path = os.path.relpath(os.path.join(root, file), MODELS_DIR)
                models.append(rel_path.replace("\\", "/"))
    
    return sorted(models)

def get_dropdown_data():
    """Gibt die Choices und den passenden Standardwert für das Dropdown zurück."""
    models = scan_rvc_models()
    if not models:
        return ["Keine Modelle in assets/models/ gefunden"], "Keine Modelle in assets/models/ gefunden"
    return models, models

def refresh_models():
    """Erneuert die Auswahl im Dropdown-Menü inklusive Unterordnern."""
    choices, default_val = get_dropdown_data()
    return gr.Dropdown(choices=choices, value=default_val)

def find_associated_index(model_rel_path):
    """Sucht automatisch nach einer passenden .index Datei für das gewählte Modell."""
    model_abs_path = os.path.join(MODELS_DIR, model_rel_path)
    model_dir = os.path.dirname(model_abs_path)
    model_base_name = os.path.splitext(os.path.basename(model_abs_path))[0]
    
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

def convert_codec(input_wav, target_codec):
    """Konvertiert die Master-WAV-Datei in das gewünschte Zielformat."""
    out_dir = os.path.join(ENGINE_DIR, "assets", "outputs")
    os.makedirs(out_dir, exist_ok=True)
    
    ext = target_codec.lower()
    final_output_path = os.path.join(out_dir, f"master_bounce.{ext}")
    
    if ext == "wav":
        shutil.copy(input_wav, final_output_path)
        return final_output_path

    try:
        from pydub import AudioSegment
        sound = AudioSegment.from_wav(input_wav)
        
        if ext == "mp3":
            sound.export(final_output_path, format="mp3", bitrate="320k")
        elif ext == "flac":
            sound.export(final_output_path, format="flac")
        elif ext in ["wma", "vob"]:
            sound.export(final_output_path, format=ext)
            
        return final_output_path
    except Exception as e:
        print(f"⚠️ Codec-Konvertierung fehlgeschlagen ({str(e)}). Gebe WAV aus.")
        fallback_path = os.path.join(out_dir, "master_bounce_fallback.wav")
        shutil.copy(input_wav, fallback_path)
        return fallback_path

def apply_studio_fx(input_wav_path, gate_thresh, gate_release, eq_low, eq_mid, eq_high, echo_time, echo_fb, reverb_size, fx_mix, target_sr):
    """Wendet Noise Gate, 3-Band EQ, Echo und Reverb via Pedalboard an."""
    try:
        from pedalboard import Pedalboard, NoiseGate, PeakFilter, LowShelfFilter, HighShelfFilter, Delay, Reverb, Mix
        from pedalboard.io import AudioFile
        
        with AudioFile(input_wav_path) as f:
            audio = f.read(f.frames)
            sr = f.samplerate
            
        mix_factor = fx_mix / 100.0
        
        board = Pedalboard([
            NoiseGate(threshold_db=gate_thresh, release_ms=gate_release),
            LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=eq_low),
            PeakFilter(cutoff_frequency_hz=2500.0, gain_db=eq_mid, q=1.0),
            HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=eq_high),
            Mix([
                Pedalboard([
                    Delay(delay_seconds=echo_time, feedback=echo_fb / 100.0, mix=1.0),
                    Reverb(room_size=reverb_size, wet_level=1.0, dry_level=0.0)
                ])
            ], mix_level=mix_factor)
        ])
        
        effected = board(audio, sr)
        
        temp_out_dir = os.path.join(ENGINE_DIR, "assets", "temp")
        os.makedirs(temp_out_dir, exist_ok=True)
        temp_wav = os.path.join(temp_out_dir, "temp_master.wav")
        
        with AudioFile(temp_wav, 'w', target_sr, effected.shape) as f:
            f.write(effected)
            
        return temp_wav
    except Exception as fx_err:
        print(f"⚠️ FX Chain Error: {str(fx_err)}.")
        return input_wav_path

def process_audio(
    input_audio, rvc_model, vocal_pitch, f0_method, index_rate, protect, filter_radius, rms_mix_rate, hop_length,
    gate_threshold, gate_release, 
    eq_low, eq_mid, eq_high, 
    echo_time, echo_feedback, reverb_size, fx_mix, 
    export_codec, sample_rate
):
    if not input_audio:
        return None, "Fehler: Kein Eingangs-Audio hochgeladen."
    if not rvc_model or "Keine Modelle" in rvc_model:
        return None, "Fehler: Kein gültiges RVC-Modell ausgewählt."
    
    model_path = os.path.normpath(os.path.join(MODELS_DIR, rvc_model))
    index_path = find_associated_index(rvc_model)
    target_sr = int(sample_rate.split()[0])
    
    status_msg = f"Modell geladen: {os.path.basename(model_path)}\n"
    status_msg += f"Index geladen: {os.path.basename(index_path) if index_path else 'Keine (.index fehlt)'}\n"
    status_msg += "Starte Applio v3.7.1 Inferenz-Pipeline...\n"

    try:
        from rvc.modules.vc.modules import VC
        vc = VC()
        vc.get_vc(model_path)
        
        results = vc.vc_single(
            sid=0,
            input_audio_path=input_audio,
            f0_up_key=vocal_pitch,
            f0_file=None,
            f0_method=f0_method,
            file_index=index_path,
            file_index2="",
            index_rate=index_rate,
            filter_radius=int(filter_radius),
            resample_sr=target_sr,
            rms_mix_rate=rms_mix_rate,
            protect=protect,
            hop_length=int(hop_length) if "crepe" in f0_method else 128
        )
        
        output_info, rvc_wav_path = results
        status_msg += "RVC Inferenz erfolgreich! Rendering Engine v3.0 DYNAMICS FX Chain...\n"
        
        temp_master_wav = apply_studio_fx(
            rvc_wav_path, gate_threshold, gate_release, 
            eq_low, eq_mid, eq_high, 
            echo_time, echo_feedback, reverb_size, fx_mix, target_sr
        )
        
        status_msg += f"Mastering komplett! Konvertiere Ziel-Codec in Richtung: {export_codec}...\n"
        final_file_path = convert_codec(temp_master_wav, export_codec)
        
        status_msg += f"🟢 Vorgang erfolgreich abgeschlossen! Datei bereitgestellt."
        return final_file_path, status_msg

    except Exception as e:
        error_msg = f"Inferenz-Fehler: {str(e)}\nStelle sicher, dass Applio v3.7.1 vollständig einsatzbereit ist."
        print(error_msg)
        return None, error_msg

# Initialisiere die Modellliste
available_choices, default_model = get_dropdown_data()

with gr.Blocks(title="Super Impersonator app") as app:
    gr.Markdown("# Super Impersonator app")
    gr.Markdown("### Engine v3.0 DYNAMICS FX // by **don24crk**")
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("## 01 / INPUT SIGNAL & STUDIO FX CHAIN")
            input_audio = gr.Audio(label="Studio I/O (Eingangskanal)", type="filepath")
            
            with gr.Row():
                rvc_model = gr.Dropdown(label="RVC Modell (.pth) [inkl. Unterordner]", choices=available_choices, value=default_model, scale=4)
                refresh_btn = gr.Button("🔄", scale=1)
                
            vocal_pitch = gr.Slider(label="Vocal Pitch (Halbtöne)", minimum=-24, maximum=24, step=1, value=0)
            f0_method = gr.Dropdown(label="F0 Pitch Extraction Method", choices=["rmvpe", "harvest", "crepe", "mangio-crepe", "pm", "dio"], value="rmvpe")
            index_rate = gr.Slider(label="Index Rate (Stimmenähnlichkeit)", minimum=0.0, maximum=1.0, step=0.05, value=0.75)
            protect = gr.Slider(label="Protect (Konsonanten- und Atemschutz)", minimum=0.0, maximum=0.5, step=0.01, value=0.33)
            filter_radius = gr.Slider(label="Filter Radius (F0 Glättung)", minimum=0, maximum=7, step=1, value=3)
            rms_mix_rate = gr.Slider(label="Clean Audio / Autoclean (RMS Mix Rate)", minimum=0.0, maximum=1.0, step=0.05, value=0.25)
            hop_length = gr.Dropdown(label="Crepe Hop Length (Zeitliche Präzision)", choices=["16", "32", "64", "128", "256", "512"], value="128", visible=False)
            
            with gr.Accordion("01.A / STUDIO DYNAMICS (NOISE GATE)", open=False):
                gate_threshold = gr.Slider(label="Gate Threshold (dB)", minimum=-60, maximum=0, step=1, value=-45)
                gate_release = gr.Slider(label="Gate Release (ms)", minimum=10, maximum=1000, step=10, value=150)
            
            with gr.Accordion("01.B / STUDIO PARAMETRIC EQ", open=False):
                eq_low = gr.Slider(label="Low (100 Hz) (dB)", minimum=-12, maximum=12, step=1, value=0)
                eq_mid = gr.Slider(label="Mid (2.5 kHz) (dB)", minimum=-12, maximum=12, step=1, value=0)
                eq_high = gr.Slider(label="High (10 kHz) (dB)", minimum=-12, maximum=12, step=1, value=0)
            
            with gr.Accordion("01.C / TIME & AMBIENCE FX", open=False):
                echo_time = gr.Slider(label="Echo Time (s)", minimum=0.0, maximum=2.0, step=0.1, value=0.3)
                echo_feedback = gr.Slider(label="Echo Feedback (%)", minimum=0, maximum=100, step=5, value=30)
                reverb_size = gr.Slider(label="Reverb Size", minimum=0.0, maximum=1.0, step=0.05, value=0.5)
                fx_mix = gr.Slider(label="FX Wet/Dry Mix (%)", minimum=0, maximum=100, step=5, value=25)

        with gr.Column():
            gr.Markdown("## 02 / HARDWARE MONITORING")
            status_output = gr.Textbox(label="System-Matrix Status", interactive=False, lines=6, value="🟢 ONLINE\nSystem bereit für Inferenz, FX-Mastering und Export Routing.")
            
            gr.Markdown("## 03 / MASTER EXPORT ROUTER")
            export_codec = gr.Radio(choices=["WAV", "MP3", "FLAC", "WMA", "VOB"], value="WAV", label="Ziel-Codec")
            sample_rate = gr.Radio(choices=["48000 Hz", "44100 Hz"], value="48000 Hz", label="Studio Samplerate")
            
            bounce_btn = gr.Button("Bounce Master", variant="primary")
            output_audio = gr.Audio(label="Master Ausgabe")

    f0_method.change(fn=update_hop_visibility, inputs=f0_method, outputs=hop_length)
    refresh_btn.click(fn=refresh_models, inputs=[], outputs=rvc_model)
    bounce_btn.click(
        fn=process_audio,
        inputs=[
            input_audio, rvc_model, vocal_pitch, f0_method, index_rate, protect, filter_radius, rms_mix_rate, hop_length,
            gate_threshold, gate_release,
            eq_low, eq_mid, eq_high,
            echo_time, echo_feedback, reverb_size, fx_mix,
            export_codec, sample_rate
        ],
        outputs=[output_audio, status_output]
    )

if __name__ == "__main__":
    app.launch(server_name="127.0.0.1", server_port=6969)
