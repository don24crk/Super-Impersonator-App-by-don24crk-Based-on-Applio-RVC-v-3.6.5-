# Super Impersonator app by don24crk - C# Advanced DSP Studio Engine

Dieses Projekt ist eine hochperformante, native C++ Audio-Workstation (DAW) und Live-Matrix, basierend auf den Prinzipien und Core-Inferenzen der **Applio RVC v3.6.5** Engine.

## 🎛️ Kernkomponenten & DSP-Schnittstellen

- **01.A / Studio Dynamics (Noise Gate):** Pegelabhängige Echtzeit-Rauschunterdrückung mit einstellbarem Schwellenwert (Threshold) und sanfter Ausblendung (Release).
- **01.B / Studio Parametric EQ:** Drei kaskadierte mathematische Biquad-Filter (Low Shelf bei 100 Hz, Mid Peak bei 2.5 kHz, High Shelf bei 10 kHz).
- **01.C / Time & Ambience FX:** Eine zirkuläre Echo-Delay-Line mit Feedback-Rückkopplung gekoppelt mit einem Schroeder-Kammfilter für dichten Raumklang (Reverb) und Wet/Dry-Mischregler.
- **03 / Master Export Router:** Direkte RAM-Formatierung für 24-Bit Linear PCM WAV sowie eine asynchrone FFmpeg-Prozess-Bridge für native Exporte als MP3 (320 kbit/s CBR), FLAC und WMA.
- **04 / VU-Meter Pegelanzeige:** Farbcodierte LED-Pegelanzeigen für den Mikrofoneingang und den DSP-Master-Bus auf HTML5-Canvas-Basis.
- **05 / Live Recorder & 06 / Preset-Manager:** Direkte Aufnahme im Web-Interface und Abspeichern benutzerdefinierter Effekt-Profile.
- **08 / Auto-Ducking:** Intelligente Musik-Dämpfung, sobald das Mikrofon besprochen wird.

## 🚀 Installation & Schnellstart

1. Platziere alle Code-Dateien (`Program.cs`, `index.html`, `Makefile`, `launcher.bat`) im selben Ordner.
2. Starte die Anwendung über einen Doppelklick auf die **`launcher.bat`**.
3. Öffne die **`index.html`** in einem modernen Webbrowser (z.B. Google Chrome oder Microsoft Edge), gewähre die Mikrofon-Rechte und klicke auf **Live-Modus Schalten**.

---
*Entwickelt von don24crk.*
