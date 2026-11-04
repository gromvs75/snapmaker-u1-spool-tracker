#include "TrackerU1Offline.hpp"
// Compiles the SAME header inserted into Plater.cpp; no wxWidgets or gateway.
int main(int argc, char** argv) {
    if (argc != 5) return 64;
    return TrackerU1Offline::run(argv[1], argv[2], argv[3], std::stoi(argv[4])) ? 0 : 23;
}
