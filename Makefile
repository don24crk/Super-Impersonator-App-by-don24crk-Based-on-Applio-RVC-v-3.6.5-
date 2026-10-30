.PHONY: all build run clean

APP_NAME=SuperImpersonatorEngine
SRC=Program.cs

all: build

build:
	@echo "[INFO] Kompiliere C# Projekt mit vollständiger DSP Studio Matrix..."
	dotnet new console -n $(APP_NAME) --force
	rm -f $(APP_NAME)/Program.cs
	cp $(SRC) $(APP_NAME)/Program.cs
	cd $(APP_NAME) && dotnet build -c Release

run: build
	@echo "[INFO] Starte Super Impersonator Core Engine..."
	cd $(APP_NAME) && dotnet run -c Release

clean:
	rm -rf $(APP_NAME) bin obj
