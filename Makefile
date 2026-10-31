# Super Impersonator Engine - Makefile for Windows (MinGW / GCC)
CXX = g++
CXXFLAGS = -O3 -std=c++17 -Wall
LIBS = -lws2_32 -lcrypt32
TARGET = SuperImpersonatorEngine.exe
SRC = main.cpp

all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) $(SRC) -o $(TARGET) $(LIBS)

clean:
	if exist $(TARGET) del $(TARGET)
