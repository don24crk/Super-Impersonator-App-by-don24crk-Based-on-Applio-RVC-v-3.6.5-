cmake_minimum_required(VERSION 3.15)
project(SuperImpersonatorEngine CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Definiert die ausführbare Datei direkt aus deinem Quellcode
add_executable(SuperImpersonatorEngine SuperImpersonatorEngine.cpp)

# Aktiviert systemnahe Optimierungen für den GCC/MinGW Compiler
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(SuperImpersonatorEngine PRIVATE -O3 -march=native -ffast-math)
endif()

# Bindet die nativen Windows-Netzwerkschnittstellen (Winsock2) ein
target_link_libraries(SuperImpersonatorEngine PRIVATE ws2_32 mswsock winmm)
