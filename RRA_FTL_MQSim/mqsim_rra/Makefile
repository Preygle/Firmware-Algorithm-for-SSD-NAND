# Makefile — RRA-FTL MQSim build
# ==================================
# Usage:
#   1. Clone MQSim: git clone https://github.com/CMU-SAFARI/MQSim.git
#   2. Copy rra_ftl/ files into MQSim/ (see README_INTEGRATION.md)
#   3. Run: make -j$(nproc)
#   4. Run: ./MQSim -i ssdconfig_rra.xml -w workloads/workload_hotspot.xml

CXX      := g++
CXXFLAGS := -std=c++14 -O2 -Wall -Wextra -Wno-unused-parameter
LDFLAGS  :=

# Source directories (relative to MQSim root after integration)
SRC_SSD  := src/ssd
SRC_SIM  := src/sim
SRC_HOST := src/host
SRC_EXEC := src/exec
SRC_NVM  := src/nvm_chip
SRC_UTILS := src/utils

# All .cpp files in the project
SRCS := $(wildcard $(SRC_SSD)/*.cpp) \
        $(wildcard $(SRC_SIM)/*.cpp) \
        $(wildcard $(SRC_HOST)/*.cpp) \
        $(wildcard $(SRC_EXEC)/*.cpp) \
        $(wildcard $(SRC_NVM)/*.cpp) \
        $(wildcard $(SRC_UTILS)/*.cpp) \
        src/main.cpp

OBJS := $(SRCS:.cpp=.o)
TARGET := MQSim

.PHONY: all clean run_hotspot run_sequential run_random

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(LDFLAGS)
	@echo ""
	@echo "Build complete. Run with:"
	@echo "  ./MQSim -i ssdconfig_rra.xml -w workloads/workload_hotspot.xml"

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

# ── Convenience run targets ───────────────────────────────────────────────────

run_hotspot: $(TARGET)
	./$(TARGET) -i ssdconfig_rra.xml -w workloads/workload_hotspot.xml
	@echo ""
	@echo "Parsing output..."
	@python3 parse_mqsim_output.py \
	    workloads/workload_hotspot_scenario_1_baseline.xml \
	    workloads/workload_hotspot_scenario_1.xml || true

run_sequential: $(TARGET)
	./$(TARGET) -i ssdconfig_rra.xml -w workloads/workload_sequential.xml

run_random: $(TARGET)
	./$(TARGET) -i ssdconfig_rra.xml -w workloads/workload_random.xml

run_baseline_hotspot: $(TARGET)
	./$(TARGET) -i ssdconfig_baseline.xml -w workloads/workload_hotspot.xml

clean:
	find . -name "*.o" -delete
	rm -f $(TARGET)
