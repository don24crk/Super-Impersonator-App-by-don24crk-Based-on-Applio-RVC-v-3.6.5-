# =======================================================================
#    SUPER IMPERSONATOR APP ENGINE - STUDIO PRODUCTION MAKEFILE
# =======================================================================

.PHONY: all build run clean status

# Projektspezifische Parameter
APP_NAME=SuperImpersonatorEngine
CONFIG=Release
DOTNET_CMD=dotnet

all: build

build:
	@echo "[INFO] Kompiliere C# DSP Matrix im $(CONFIG)-Modus..."
	$(DOTNET_CMD) build -c $(CONFIG)

run:
	@echo "[INFO] Starte Super Impersonator Core Engine (https://127.0.0.1:6969)..."
	@if [ -f bin/Release/net9.0/$(APP_NAME).exe ]; then \
		bin/Release/net9.0/$(APP_NAME).exe; \
	elif [ -f bin/Release/net8.0/$(APP_NAME).exe ]; then \
		bin/Release/net8.0/$(APP_NAME).exe; \
	else \
		$(DOTNET_CMD) run -c $(CONFIG); \
	fi

clean:
	@echo "[INFO] Bereinige temporäre Build-Artefakte und Cache-Verzeichnisse..."
	rm -rf bin obj
	$(DOTNET_CMD) clean >/dev/null 2>&1

status:
	@echo "======================================================================="
	@echo "   STUDIO WORKSPACE STATUS - BY DON24CRK"
	@echo "======================================================================="
	@echo " Vorhandene Modelle (.pth):"
	@find models -name "*.pth" 2>/dev/null || echo " Keine Modelle im Ordner /models gefunden."
	@echo " Vorhandene Indizes (.index):"
	@find models -name "*.index" 2>/dev/null || echo " Keine Indexdateien im Ordner /models gefunden."
	@echo "======================================================================="

