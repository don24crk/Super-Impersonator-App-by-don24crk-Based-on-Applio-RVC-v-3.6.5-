#include <iostream>
#include <vector>
#include <cmath>
#include <string>
#include <cstring>
#include <fstream>
#include <sstream>
#include <memory>
#include <chrono>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#define SOCKET int
#define INVALID_SOCKET -1
#define SOCKET_ERROR -1
#define closesocket close
#endif

// =======================================================================
// DSP STUDIO CORE-EFFEKTE (MATHEMATISCHE SIGNALVERARBEITUNG)
// =======================================================================

class StudioEchoEffect {
private:
    std::vector<double> buffer;
    int writeIndex = 0;
    int sampleRate;
public:
    StudioEchoEffect(int sr, double maxDelay) : sampleRate(sr) {
        buffer.resize(static_cast<int>(sr * maxDelay), 0.0);
    }
    double Process(double input, double sec, double feedback) {
        int delaySamples = static_cast<int>(sec * sampleRate);
        if (delaySamples >= buffer.size()) delaySamples = static_cast<int>(buffer.size()) - 1;
        int readIndex = writeIndex - delaySamples;
        if (readIndex < 0) readIndex += buffer.size();
        double sample = buffer[readIndex];
        buffer[writeIndex] = input + (sample * feedback);
        writeIndex = (writeIndex + 1) % buffer.size();
        return sample;
    }
};

class StudioReverbEffect {
private:
    std::vector<double> combBuffer;
    int writeIndex = 0;
public:
    StudioReverbEffect(int sr) {
        combBuffer.resize(static_cast<int>(sr * 0.05), 0.0);
    }
    double Process(double input, double reverbSize) {
        int delay = (writeIndex - 1200 + combBuffer.size()) % combBuffer.size();
        double output = combBuffer[delay];
        combBuffer[writeIndex] = input + (output * reverbSize);
        writeIndex = (writeIndex + 1) % combBuffer.size();
        return output;
    }
};

class BiquadFilter {
private:
    double x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    double b0 = 0, b1 = 0, b2 = 0, a0 = 1, a1 = 0, a2 = 0;
public:
    static BiquadFilter CreatePeakingEQ(double sr, double cf, double q, double db) {
        BiquadFilter f;
        double a = std::pow(10.0, db / 40.0);
        double omega = 2.0 * 3.141592653589793 * cf / sr;
        double sn = std::sin(omega);
        double cs = std::cos(omega);
        double alpha = sn / (2.0 * q);
        f.b0 = 1.0 + alpha * a; f.b1 = -2.0 * cs; f.b2 = 1.0 - alpha * a;
        f.a0 = 1.0 + alpha / a; f.a1 = -2.0 * cs; f.a2 = 1.0 - alpha / a;
        return f;
    }
    static BiquadFilter CreateNotch(double sr, double cf, double q) {
        BiquadFilter f;
        double omega = 2.0 * 3.141592653589793 * cf / sr;
        double sn = std::sin(omega);
        double cs = std::cos(omega);
        double alpha = sn / (2.0 * q);
        f.b0 = 1.0; f.b1 = -2.0 * cs; f.b2 = 1.0;
        f.a0 = 1.0 + alpha; f.a1 = -2.0 * cs; f.a2 = 1.0 - alpha;
        return f;
    }
    double Process(double inVal) {
        double outVal = (b0 / a0) * inVal + (b1 / a0) * x1 + (b2 / a0) * x2 - (a1 / a0) * y1 - (a2 / a0) * y2;
        x2 = x1; x1 = inVal; y2 = y1; y1 = outVal;
        return outVal;
    }
};

// =======================================================================
// AUDIO PROCESSING DELEGATOR
// =======================================================================

std::vector<char> ApplyStudioDspChain(const std::vector<char>& inputWav, int sampleRate) {
    if (inputWav.size() < 44) return inputWav;
    
    int headerOffset = (inputWav[0] == 'R' && inputWav[1] == 'I') ? 44 : 0;
    int samplesCount = (inputWav.size() - headerOffset) / 2;
    std::vector<short> samples(samplesCount);
    std::memcpy(samples.data(), inputWav.data() + headerOffset, samplesCount * 2);

    BiquadFilter lowBand = BiquadFilter::CreatePeakingEQ(sampleRate, 100.0, 1.0, 0.0);
    BiquadFilter midBand = BiquadFilter::CreatePeakingEQ(sampleRate, 2500.0, 1.2, 0.0);
    BiquadFilter highBand = BiquadFilter::CreatePeakingEQ(sampleRate, 10000.0, 1.0, 0.0);

    StudioEchoEffect echoEffect(sampleRate, 1.0);
    StudioReverbEffect reverbEffect(sampleRate);

    for (size_t i = 0; i < samples.size(); i++) {
        double inputSample = samples[i] / 32768.0;
        double currentSample = highBand.Process(midBand.Process(lowBand.Process(inputSample)));

        double echoSignal = echoEffect.Process(currentSample, 0.3, 0.3);
        double reverbSignal = reverbEffect.Process(currentSample, 0.5);
        double wetSignal = (echoSignal + reverbSignal) * 0.7;
        double finalSample = (currentSample * 0.75) + (wetSignal * 0.25);

        if (finalSample > 1.0) finalSample = 1.0;
        if (finalSample < -1.0) finalSample = -1.0;
        samples[i] = static_cast<short>(finalSample * 32767.0);
    }

    std::vector<char> outputWav = inputWav;
    std::memcpy(outputWav.data() + headerOffset, samples.data(), samplesCount * 2);
    return outputWav;
}

// =======================================================================
// NETZWERK ENGINE (NATIVE THREAD PIPELINE)
// =======================================================================

#ifdef _WIN32
DWORD WINAPI ClientWorkerThread(LPVOID lpParam) {
    SOCKET clientSocket = (SOCKET)lpParam;
#else
void* ClientWorkerThread(void* lpParam) {
    SOCKET clientSocket = *(SOCKET*)lpParam;
    delete (SOCKET*)lpParam;
#endif

    std::vector<char> buffer(1024 * 64, 0);
    int bytesReceived = recv(clientSocket, buffer.data(), buffer.size() - 1, 0);
    
    if (bytesReceived > 0) {
        std::string request(buffer.data(), bytesReceived);
        std::ostringstream response;

        if (request.find("GET /api/models") != std::string::npos) {
            std::string json = "{\n  \"applio_version\": \"v3.6.5-interop\",\n  \"models\": [],\n  \"index_files\": []\n}";
            response << "HTTP/1.1 200 OK\r\n"
                     << "Content-Type: application/json\r\n"
                     << "Access-Control-Allow-Origin: *\r\n"
                     << "Content-Length: " << json.length() << "\r\n\r\n" << json;
        } else {
            std::string html = "<html><body><h1>Super Impersonator DSP C++ Engine aktiv</h1></body></html>";
            response << "HTTP/1.1 200 OK\r\n"
                     << "Content-Type: text/html\r\n"
                     << "Access-Control-Allow-Origin: *\r\n"
                     << "Content-Length: " << html.length() << "\r\n\r\n" << html;
        }

        send(clientSocket, response.str().c_str(), response.str().length(), 0);
    }
    closesocket(clientSocket);
    return 0;
}

int main() {
    std::cout << "=======================================================================" << std::endl;
    std::cout << "     SUPER IMPERSONATOR APP ENGINE (NATIVE C++ CORES) - BY DON24CRK" << std::endl;
    std::cout << "=======================================================================" << std::endl;

#ifdef _WIN32
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        std::cerr << "[FEHLER] Winsock-Initialisierung fehlgeschlagen." << std::endl;
        return 1;
    }
#endif

    SOCKET serverSocket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (serverSocket == INVALID_SOCKET) {
        std::cerr << "[FEHLER] Socket-Erstellung fehlgeschlagen." << std::endl;
        return 1;
    }

    // FIX: SO_REUSEADDR aktivieren, um Port-Blockaden nach Restarts zu verhindern
    int optval = 1;
    setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, (const char*)&optval, sizeof(optval));

    sockaddr_in serverAddr;
    serverAddr.sin_family = AF_INET;
    serverAddr.sin_addr.s_addr = inet_addr("127.0.0.1");
    serverAddr.sin_port = htons(6969);

    if (bind(serverSocket, (sockaddr*)&serverAddr, sizeof(serverAddr)) == SOCKET_ERROR) {
        std::cerr << "[FEHLER] Port-Bindung blockiert. Laeuft die Engine bereits?" << std::endl;
        closesocket(serverSocket);
        return 1;
    }

    if (listen(serverSocket, SOMAXCONN) == SOCKET_ERROR) {
        std::cerr << "[FEHLER] Listener konnte nicht gestartet werden." << std::endl;
        closesocket(serverSocket);
        return 1;
    }

    std::cout << "[INFO] Native DSP Engine aktiv auf http://127.0.0" << std::endl;

    while (true) {
        SOCKET clientSocket = accept(serverSocket, nullptr, nullptr);
        if (clientSocket != INVALID_SOCKET) {
#ifdef _WIN32
            HANDLE threadHandle = CreateThread(NULL, 0, ClientWorkerThread, (LPVOID)clientSocket, 0, NULL);
            if (threadHandle) {
                CloseHandle(threadHandle);
            } else {
                closesocket(clientSocket);
            }
#else
            SOCKET* pClient = new SOCKET(clientSocket);
            pthread_t t;
            pthread_create(&t, NULL, ClientWorkerThread, pClient);
            pthread_detach(t);
#endif
        }
    }

    closesocket(serverSocket);
#ifdef _WIN32
    WSACleanup();
#endif
    return 0;
}
