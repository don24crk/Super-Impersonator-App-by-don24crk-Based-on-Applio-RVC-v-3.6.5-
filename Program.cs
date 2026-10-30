using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Net.WebSockets;
using System.Diagnostics;
using System.Collections.Generic;

namespace SuperImpersonatorEngine
{
    class Program
    {
        private static string ModelsDir = "./models";

        // Aktuell aktive Inferenz-Dateien (Dynamisch gesetzt via API/WebSocket)
        private static string ActiveModelPath = "default.pth";
        private static string ActiveIndexPath = "";
        private static int ActivePitchShift = 0;

        // DSP Studio FX Parameter (Globale Zustände)
        private static double GateThresholdDb = -45.0;
        private static double GateReleaseMs = 150.0;
        private static double EqLowGainDb = 0.0;
        private static double EqMidGainDb = 0.0;
        private static double EqHighGainDb = 0.0;
        
        // 01.C / TIME & AMBIENCE FX Parameter
        private static double EchoTimeSec = 0.3;
        private static double EchoFeedback = 0.3;
        private static double ReverbSize = 0.5;
        private static double FxWetDryMix = 0.25;

        // 08 / Auto-Ducking Parameter
        private static double DuckingDepthPercent = 60.0;

        // 07 / Feedback Killer State
        private static bool IsFeedbackKillerActive = true;

        private static double _gateCurrentGain = 1.0;

        // Globale Effekt-Instanzen für die Live-Verarbeitung
        private static StudioEchoEffect _echoEffect;
        private static StudioReverbEffect _reverbEffect;

        static async Task Main(string[] args)
        {
            Console.Title = "Super Impersonator app by don24crk - Full DSP Engine";
            Console.OutputEncoding = Encoding.UTF8;

            Console.WriteLine("=======================================================================");
            Console.WriteLine("     SUPER IMPERSONATOR APP ENGINE (FULL AMBIENCE DSP) - BY DON24CRK");
            Console.WriteLine("=======================================================================");
            
            _echoEffect = new StudioEchoEffect(48000, 1.0);
            _reverbEffect = new StudioReverbEffect(48000);

            if (!Directory.Exists(ModelsDir)) Directory.CreateDirectory(ModelsDir);

            string httpUrl = "https://127.0.0.1:6969/";
            using HttpListener listener = new HttpListener();
            listener.Prefixes.Add(httpUrl);
            try 
            {
                listener.Start();
                Console.WriteLine($"[INFO] Full DSP Engine aktiv auf {httpUrl}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[FEHLER] SSL-Zertifikat oder Port-Konflikt bei {httpUrl}: {ex.Message}");
                Console.WriteLine("[TIPP] Nutze das Diagnose-Skript zur automatischen SSL-Reparatur!");
                return;
            }

            while (true)
            {
                try
                {
                    HttpListenerContext context = await listener.GetContextAsync();
                    _ = Task.Run(async () => {
                        try { await HandleRequestAsync(context); } catch { if (context?.Response != null) context.Response.Close(); }
                    });
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[FEHLER] Listener-Fehler: {ex.Message}");
                }
            }
        }

        private static async Task HandleRequestAsync(HttpListenerContext context)
        {
            HttpListenerRequest request = context.Request;
            HttpListenerResponse response = context.Response;

            response.Headers.Add("Access-Control-Allow-Origin", "*");
            response.Headers.Add("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
            response.Headers.Add("Access-Control-Allow-Headers", "*");

            if (request.HttpMethod == "OPTIONS")
            {
                response.StatusCode = (int)HttpStatusCode.OK;
                response.Close();
                return;
            }

            if (request.IsWebSocketRequest && request.Url.AbsolutePath == "/ws/live")
            {
                HttpListenerWebSocketContext wsContext = await context.AcceptWebSocketAsync(null);
                await HandleWebSocketAsync(wsContext.WebSocket);
                return;
            }

            if (request.HttpMethod == "GET" && request.Url.AbsolutePath == "/api/models")
            {
                try { await ListAvailableModelsAsync(response); } catch { response.StatusCode = 500; response.Close(); }
                return;
            }

            if (request.HttpMethod == "POST" && request.Url.AbsolutePath == "/api/transform")
            {
                try { await ProcessAudioTransformationAsync(request, response); } catch { response.StatusCode = 500; response.Close(); }
                return;
            }

            if (context.Response != null)
            {
                response.StatusCode = (int)HttpStatusCode.NotFound;
                response.Close();
            }
        }

        private static async Task ListAvailableModelsAsync(HttpListenerResponse response)
        {
            string[] pthFiles = Directory.GetFiles(ModelsDir, "*.pth", SearchOption.AllDirectories);
            string[] indexFiles = Directory.GetFiles(ModelsDir, "*.index", SearchOption.AllDirectories);

            List<string> models = new List<string>();
            List<string> indices = new List<string>();

            foreach (string file in pthFiles) models.Add(Path.GetRelativePath(ModelsDir, file).Replace("\\", "/"));
            foreach (string file in indexFiles) indices.Add(Path.GetRelativePath(ModelsDir, file).Replace("\\", "/"));

            var resultPayload = new { applio_version = "v3.6.5-interop", models = models, index_files = indices };
            string jsonResult = JsonSerializer.Serialize(resultPayload, new JsonSerializerOptions { WriteIndented = true });
            byte[] buffer = Encoding.UTF8.GetBytes(jsonResult);
            
            response.ContentType = "application/json";
            response.StatusCode = (int)HttpStatusCode.OK;
            response.ContentLength64 = buffer.Length;
            await response.OutputStream.WriteAsync(buffer, 0, buffer.Length);
            response.OutputStream.Close();
        }

        private static async Task ProcessAudioTransformationAsync(HttpListenerRequest request, HttpListenerResponse response)
        {
            string modelName = "default.pth";
            string indexName = "";
            int pitchShift = 0;
            string format = "wav";
            int samplerate = 48000;
            byte[] audioBytes = null;

            if (request.ContentType != null && request.ContentType.StartsWith("multipart/form-data"))
            {
                using MemoryStream ms = new MemoryStream();
                await request.InputStream.CopyToAsync(ms);
                byte[] rawMultipartBytes = ms.ToArray();
                string rawBodyText = Encoding.UTF8.GetString(rawMultipartBytes);

                modelName = ParseMultipartField(rawBodyText, "name=\"model\"") ?? modelName;
                indexName = ParseMultipartField(rawBodyText, "name=\"index\"") ?? indexName;
                string pitchStr = ParseMultipartField(rawBodyText, "name=\"pitch\"");
                if (!string.IsNullOrEmpty(pitchStr) && int.TryParse(pitchStr.Trim(), out int parsedPitch)) pitchShift = parsedPitch;
                
                string reqFormat = ParseMultipartField(rawBodyText, "name=\"format\"");
                if (!string.IsNullOrEmpty(reqFormat)) format = reqFormat.Trim().ToLower();

                int riffIndex = System.Array.IndexOf(rawMultipartBytes, (byte)'R');
                while (riffIndex >= 0 && riffIndex < rawMultipartBytes.Length - 4)
                {
                    if (rawMultipartBytes[riffIndex + 1] == 'I' && rawMultipartBytes[riffIndex + 2] == 'F' && rawMultipartBytes[riffIndex + 3] == 'F') break;
                    riffIndex = System.Array.IndexOf(rawMultipartBytes, (byte)'R', riffIndex + 1);
                }
                if (riffIndex >= 0)
                {
                    int audioLength = rawMultipartBytes.Length - riffIndex;
                    if (rawBodyText.Contains("------WebKitFormBoundary")) audioLength -= 100; 
                    if (audioLength > 44)
                    {
                        audioBytes = new byte[audioLength];
                        Array.Copy(rawMultipartBytes, riffIndex, audioBytes, 0, audioLength);
                    }
                }
            }

            Console.WriteLine($"[API-Transform] Modell: {modelName} | Index: {indexName} | Pitch: {pitchShift}ST | Format: {format}");

            byte[] rvcProcessed = ApplyRvcModel(audioBytes, Path.Combine(ModelsDir, modelName), indexName, pitchShift, samplerate);
            byte[] dspProcessed = ApplyStudioDspChain(rvcProcessed, samplerate);
            byte[] finalMasteredAudio = EncodeToTargetFormat(dspProcessed, format, samplerate);

            string mimeType = format switch { "mp3" => "audio/mp3", "flac" => "audio/flac", "wma" => "audio/x-ms-wma", _ => "audio/wav" };
            response.ContentType = mimeType;
            response.StatusCode = (int)HttpStatusCode.OK;
            response.Headers.Add("Content-Disposition", $"attachment; filename=super_impersonator_master.{format}");
            response.ContentLength64 = finalMasteredAudio.Length;
            await response.OutputStream.WriteAsync(finalMasteredAudio, 0, finalMasteredAudio.Length);
            response.OutputStream.Close();
        }

        private static string ParseMultipartField(string rawBody, string fieldName)
        {
            int idx = rawBody.IndexOf(fieldName);
            if (idx == -1) return null;
            int startPos = rawBody.IndexOf("\r\n\r\n", idx);
            if (startPos == -1) return null;
            startPos += 4;
            int endPos = rawBody.IndexOf("\r\n", startPos);
            if (endPos == -1) return null;
            return rawBody.Substring(startPos, endPos - startPos).Trim();
        }

        private static async Task HandleWebSocketAsync(WebSocket webSocket)
        {
            byte[] buffer = new byte[1024 * 32];
            while (webSocket.State == WebSocketState.Open)
            {
                WebSocketReceiveResult r = await webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);
                if (r.MessageType == WebSocketMessageType.Close) break;
                
                if (r.MessageType == WebSocketMessageType.Text)
                {
                    string jsonString = Encoding.UTF8.GetString(buffer, 0, r.Count);
                    using JsonDocument doc = JsonDocument.Parse(jsonString);
                    JsonElement root = doc.RootElement;
                    
                    if (root.TryGetProperty("active_model", out JsonElement am)) ActiveModelPath = am.GetString();
                    if (root.TryGetProperty("active_index", out JsonElement ai)) ActiveIndexPath = ai.GetString();
                    if (root.TryGetProperty("pitch_shift", out JsonElement ps)) ActivePitchShift = ps.GetInt32();
                    if (root.TryGetProperty("is_feedback_killer_active", out JsonElement fk)) IsFeedbackKillerActive = fk.GetBoolean();

                    if (root.TryGetProperty("gate_threshold", out JsonElement gt)) GateThresholdDb = gt.GetDouble();
                    if (root.TryGetProperty("gate_release", out JsonElement gr)) GateReleaseMs = gr.GetDouble();
                    if (root.TryGetProperty("eq_low", out JsonElement el)) EqLowGainDb = el.GetDouble();
                    if (root.TryGetProperty("eq_mid", out JsonElement em)) EqMidGainDb = em.GetDouble();
                    if (root.TryGetProperty("eq_high", out JsonElement eh)) EqHighGainDb = eh.GetDouble();
                    if (root.TryGetProperty("echo_time", out JsonElement et)) EchoTimeSec = et.GetDouble();
                    if (root.TryGetProperty("echo_feedback", out JsonElement ef)) EchoFeedback = ef.GetDouble() / 100.0;
                    if (root.TryGetProperty("reverb_size", out JsonElement rs)) ReverbSize = rs.GetDouble();
                    if (root.TryGetProperty("fx_mix", out JsonElement fm)) FxWetDryMix = fm.GetDouble() / 100.0;
                    if (root.TryGetProperty("ducking_depth", out JsonElement dd)) DuckingDepthPercent = dd.GetDouble();
                }
                else if (r.MessageType == WebSocketMessageType.Binary)
                {
                    byte[] incomingChunk = new byte[r.Count]; 
                    Array.Copy(buffer, incomingChunk, r.Count);
                    
                    Stopwatch inferenceTimer = Stopwatch.StartNew();

                    byte[] rvcLive = ApplyRvcModel(incomingChunk, Path.Combine(ModelsDir, ActiveModelPath), ActiveIndexPath, ActivePitchShift, 48000);
                    byte[] dspLive = ApplyStudioDspChain(rvcLive, 48000);
                    
                    inferenceTimer.Stop();
                    long elapsedMs = inferenceTimer.ElapsedMilliseconds;

                    if (elapsedMs > 30)
                    {
                        Console.WriteLine($"[WARNUNG] Inferenz-Verzögerung: {elapsedMs}ms | Block: {r.Count} B (CPU Engpass)");
                    }
                    else
                    {
                        Console.WriteLine($"[MATRIX] Inferenz: {elapsedMs}ms | DSP-Kette: Aktiv");
                    }
                    
                    await webSocket.SendAsync(new ArraySegment<byte>(dspLive), WebSocketMessageType.Binary, true, CancellationToken.None);
                }
            }
        }

        private static byte[] ApplyStudioDspChain(byte[] inputWav, int sampleRate)
        {
            if (inputWav == null || inputWav.Length < 44) return inputWav ?? new byte[0];
            int headerOffset = (inputWav[0] == 'R' && inputWav[1] == 'I') ? 44 : 0;
            int samplesCount = (inputWav.Length - headerOffset) / 2;
            short[] samples = new short[samplesCount];
            Buffer.BlockCopy(inputWav, headerOffset, samples, 0, samples.Length * 2);

            BiquadFilter lowBand = BiquadFilter.CreatePeakingEQ(sampleRate, 100.0, 1.0, EqLowGainDb);
            BiquadFilter midBand = BiquadFilter.CreatePeakingEQ(sampleRate, 2500.0, 1.2, EqMidGainDb);
            BiquadFilter highBand = BiquadFilter.CreatePeakingEQ(sampleRate, 10000.0, 1.0, EqHighGainDb);

            BiquadFilter feedbackKiller1 = BiquadFilter.CreateNotch(sampleRate, 1000.0, 15.0);
            BiquadFilter feedbackKiller2 = BiquadFilter.CreateNotch(sampleRate, 2000.0, 15.0);
            BiquadFilter feedbackKiller3 = BiquadFilter.CreateNotch(sampleRate, 4000.0, 15.0);

            double thresholdLinear = Math.Pow(10.0, GateThresholdDb / 20.0);
            double releaseSamples = (GateReleaseMs / 1000.0) * sampleRate;
            double attackCoef = Math.Exp(-1.0 / (0.002 * sampleRate));
            double releaseCoef = Math.Exp(-1.0 / releaseSamples);
            double duckingDepthFactor = (100.0 - DuckingDepthPercent) / 100.0;
            
            for (int i = 0; i < samples.Length; i++)
            {
                double inputSample = samples[i] / 32768.0;
                double env = Math.Abs(inputSample);
                double targetGain = (env >= thresholdLinear) ? 1.0 : 0.0;
                _gateCurrentGain = targetGain > _gateCurrentGain ? attackCoef * _gateCurrentGain + (1.0 - attackCoef) * targetGain : releaseCoef * _gateCurrentGain + (1.0 - releaseCoef) * targetGain;
                
                double currentSample = inputSample * _gateCurrentGain;

                currentSample = highBand.Process(midBand.Process(lowBand.Process(currentSample)));

                if (IsFeedbackKillerActive)
                {
                    currentSample = feedbackKiller3.Process(feedbackKiller2.Process(feedbackKiller1.Process(currentSample)));
                }

                double echoSignal = _echoEffect.Process(currentSample, EchoTimeSec, EchoFeedback);
                double reverbSignal = _reverbEffect.Process(currentSample, ReverbSize);
                double wetSignal = (echoSignal + reverbSignal) * 0.7;
                double finalVoiceSample = (currentSample * (1.0 - FxWetDryMix)) + (wetSignal * FxWetDryMix);

                double currentMusicSample = 0.0; 
                double currentDuckingGain = 1.0 - ((1.0 - duckingDepthFactor) * _gateCurrentGain);
                double finalMusicSample = currentMusicSample * currentDuckingGain;

                double finalSample = finalVoiceSample + finalMusicSample;

                if (finalSample > 1.0) finalSample = 1.0;
                if (finalSample < -1.0) finalSample = -1.0;
                samples[i] = (short)(finalSample * 32767.0);
            }

            byte[] outputWav = new byte[inputWav.Length];
            Array.Copy(inputWav, 0, outputWav, 0, inputWav.Length);
            Buffer.BlockCopy(samples, 0, outputWav, headerOffset, samples.Length * 2);
            return outputWav;
        }

        private static byte[] EncodeToTargetFormat(byte[] rawWav, string format, int sampleRate)
        {
            if (rawWav == null || rawWav.Length == 0) return new byte[0];
            if (format == "wav") return ConvertWavTo24Bit(rawWav);
            string arguments = format switch { "mp3" => "-f wav -i pipe:0 -c:a libmp3lame -b:a 320k -f mp3 pipe:1", "flac" => "-f wav -i pipe:0 -c:a flac -f flac pipe:1", "wma" => "-f wav -i pipe:0 -c:a wmav2 -b:a 192k -f asf pipe:1", _ => "-f wav -i pipe:0 -f wav pipe:1" };
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo { FileName = "ffmpeg", Arguments = arguments, RedirectStandardInput = true, RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true };
                using Process ffmpeg = Process.Start(psi);
                using (MemoryStream msInput = new MemoryStream(rawWav)) { msInput.CopyTo(ffmpeg.StandardInput.BaseStream); ffmpeg.StandardInput.Close(); }
                using MemoryStream msOutput = new MemoryStream(); ffmpeg.StandardOutput.BaseStream.CopyTo(msOutput); ffmpeg.WaitForExit();
                if (msOutput.Length > 0) return msOutput.ToArray();
            } catch {}
            return rawWav;
        }

        private static byte[] ConvertWavTo24Bit(byte[] inputWav)
        {
            if (inputWav.Length < 44) return inputWav;
            int headerOffset = (inputWav[0] == 'R' && inputWav[1] == 'I') ? 44 : 0;
            int samplesCount = (inputWav.Length - headerOffset) / 2;
            using MemoryStream output = new MemoryStream();
            using BinaryWriter writer = new BinaryWriter(output);
            int dataChunkSize = samplesCount * 3;
            writer.Write(Encoding.UTF8.GetBytes("RIFF")); writer.Write(36 + dataChunkSize); writer.Write(Encoding.UTF8.GetBytes("WAVEfmt "));
            writer.Write(16); writer.Write((short)1); writer.Write((short)1); writer.Write(48000); writer.Write(48000 * 1 * 3); writer.Write((short)3); writer.Write((short)24);
            writer.Write(Encoding.UTF8.GetBytes("data")); writer.Write(dataChunkSize);
            for (int i = 0; i < samplesCount; i++)
            {
                short sample16 = BitConverter.ToInt16(inputWav, headerOffset + (i * 2));
                int sample24 = sample16 * 256;
                writer.Write((byte)(sample24 & 0xFF)); writer.Write((byte)((sample24 >> 8) & 0xFF)); writer.Write((byte)((sample24 >> 16) & 0xFF));
            }
            return output.ToArray();
        }

        private static byte[] ApplyRvcModel(byte[] i, string m, string index, int p, int s) => i ?? new byte[0];
    }

    public class StudioEchoEffect {
        private double[] _buffer; int _writeIndex = 0; int _sampleRate;
        public StudioEchoEffect(int sr, double maxD) { _sampleRate = sr; _buffer = new double[(int)(sr * maxD)]; }
        public double Process(double i, double sec, double fb) {
            int d = (int)(sec * _sampleRate); if (d >= _buffer.Length) d = _buffer.Length - 1;
            int r = _writeIndex - d; if (r < 0) r += _buffer.Length;
            double s = _buffer[r]; _buffer[_writeIndex] = i + (s * fb);
            _writeIndex = (_writeIndex + 1) % _buffer.Length; return s;
        }
    }
    public class StudioReverbEffect {
        private double[] _combBuffer; int _writeIndex = 0;
        public StudioReverbEffect(int sr) { _combBuffer = new double[(int)(sr * 0.05)]; }
        public double Process(double i, double rs) {
            int d = (_writeIndex - 1200 + _combBuffer.Length) % _combBuffer.Length;
            double o = _combBuffer[d]; _combBuffer[_writeIndex] = i + (o * rs);
            _writeIndex = (_writeIndex + 1) % _combBuffer.Length; return o;
        }
    }
    public class BiquadFilter {
        private double x1, x2, y1, y2, b0, b1, b2, a0, a1, a2;
        public static BiquadFilter CreatePeakingEQ(double sr, double cf, double q, double db) {
            var f = new BiquadFilter();
            double a = Math.Pow(10.0, db / 40.0), o = 2.0 * Math.PI * cf / sr, sn = Math.Sin(o), cs = Math.Cos(o), al = sn / (2.0 * q);
            f.b0 = 1.0 + al * a; f.b1 = -2.0 * cs; f.b2 = 1.0 - al * a; f.a0 = 1.0 + al / a; f.a1 = -2.0 * cs; f.a2 = 1.0 - al / a; return f;
        }
        public static BiquadFilter CreateNotch(double sr, double cf, double q) {
            var f = new BiquadFilter();
            double o = 2.0 * Math.PI * cf / sr, sn = Math.Sin(o), cs = Math.Cos(o), al = sn / (2.0 * q);
            f.b0 = 1.0; f.b1 = -2.0 * cs; f.b2 = 1.0; f.a0 = 1.0 + al; f.a1 = -2.0 * cs; f.a2 = 1.0 - al; return f;
        }
        public double Process(double inVal) {
            double outVal = (b0 / a0) * inVal + (b1 / a0) * x1 + (b2 / a0) * x2 - (a1 / a0) * y1 - (a2 / a0) * y2;
            x2 = x1; x1 = inVal; y2 = y1; y1 = outVal; return outVal;
        }
    }
}
