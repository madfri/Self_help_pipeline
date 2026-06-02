/**
 * Part 2: Business Logic Decoder Server (C++ Example)
 * ======================================================
 * Production-ready C++ application using cpp-httplib (header-only)
 * as the embedded HTTP server. Listens on 127.0.0.1:8080.
 *
 * Endpoints:
 *   POST /process    - Receives JSON metadata envelope, inspects fingerprint,
 *                      dynamically rewrites the itinerary array, mocks S3 write,
 *                      and returns the updated envelope.
 *   GET  /health     - Liveness probe (returns 200).
 *   GET  /ready      - Readiness probe (returns 200).
 */

#include <algorithm>
#include <iostream>
#include <string>
#include <vector>
#include <cstdlib>
#include <chrono>
#include <iomanip>
#include <sstream>

// cpp-httplib is downloaded during Docker build
#include "httplib.h"
// nlohmann/json is available via Alpine packages
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
static constexpr const char* BIND_HOST = "127.0.0.1";
static constexpr int BIND_PORT = 8080;

// ---------------------------------------------------------------------------
// Utility: Generate a timestamped S3 URI for decoded output.
// ---------------------------------------------------------------------------
std::string generate_decoded_uri(const std::string& fingerprint) {
    auto now = std::chrono::system_clock::now();
    auto time_t_now = std::chrono::system_clock::to_time_t(now);
    std::tm utc_tm{};
    gmtime_r(&time_t_now, &utc_tm);

    std::ostringstream oss;
    oss << "s3://packet-storage/decoded/"
        << (utc_tm.tm_year + 1900) << "/"
        << std::setw(2) << std::setfill('0') << (utc_tm.tm_mon + 1) << "/"
        << std::setw(2) << std::setfill('0') << utc_tm.tm_mday << "/"
        << "decoded_" << fingerprint << "_"
        << std::chrono::duration_cast<std::chrono::milliseconds>(
               now.time_since_epoch()).count()
        << ".json";
    return oss.str();
}

// ---------------------------------------------------------------------------
// Business Logic: Inspect fingerprint and rewrite itinerary dynamically.
// ---------------------------------------------------------------------------
json process_envelope(const json& envelope) {
    json result = envelope;

    // Validate required fields
    if (!result.contains("pcap_uri") || !result["pcap_uri"].is_string()) {
        throw std::runtime_error("Missing or invalid 'pcap_uri' field");
    }
    if (!result.contains("fingerprint") || !result["fingerprint"].is_string()) {
        throw std::runtime_error("Missing or invalid 'fingerprint' field");
    }
    if (!result.contains("itinerary") || !result["itinerary"].is_array()) {
        throw std::runtime_error("Missing or invalid 'itinerary' field");
    }

    const std::string fingerprint = result.value("fingerprint", "");
    const std::string pcap_uri = result.value("pcap_uri", "");

    std::cout << "[Decoder] Processing PCAP: " << pcap_uri << std::endl;
    std::cout << "[Decoder] Fingerprint: " << fingerprint << std::endl;

    // -----------------------------------------------------------------------
    // Dynamic Itinerary Choreography
    // -----------------------------------------------------------------------
    std::vector<std::string> itinerary =
        result["itinerary"].get<std::vector<std::string>>();

    // Example routing rule:
    // If fingerprint matches known threat indicators, inject threat_intel
    // enrichment BEFORE the formatter stage.
    bool is_threat_indicator = false;
    if (fingerprint == "0x8100" || fingerprint == "0x0806" || fingerprint == "0x88E1") {
        is_threat_indicator = true;
    }

    // Locate "formatter.json" position
    auto fmt_it = std::find(itinerary.begin(), itinerary.end(), "formatter.json");

    if (is_threat_indicator && fmt_it != itinerary.end()) {
        // Insert threat intel enrichment before formatter
        itinerary.insert(fmt_it, "enrichment.threat_intel");
        std::cout << "[Decoder] Injected 'enrichment.threat_intel' into itinerary"
                  << std::endl;
    }

    // Additional rule: If fingerprint indicates geo-sensitive protocol,
    // ensure geoip enrichment is present.
    auto geo_it = std::find(itinerary.begin(), itinerary.end(), "enrichment.geoip");
    if (geo_it == itinerary.end() && fmt_it != itinerary.end()) {
        itinerary.insert(fmt_it, "enrichment.geoip");
        std::cout << "[Decoder] Injected 'enrichment.geoip' into itinerary"
                  << std::endl;
    }

    result["itinerary"] = itinerary;

    // -----------------------------------------------------------------------
    // Mock S3 Write: Update decoded_data_uri
    // -----------------------------------------------------------------------
    std::string decoded_uri = generate_decoded_uri(fingerprint);
    result["decoded_data_uri"] = decoded_uri;

    std::cout << "[Decoder] Mock write complete. URI: " << decoded_uri << std::endl;

    // Append metadata about processing
    result["decoder_metadata"] = {
        {"runtime", "C++"},
        {"version", "1.0.0"},
        {"processed_at",
         std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch()).count()},
        {"threat_detected", is_threat_indicator}
    };

    return result;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main(int argc, char* argv[]) {
    // Handle CLI healthcheck probe invoked by Dockerfile HEALTHCHECK
    if (argc > 1 && std::string(argv[1]) == "--healthcheck") {
        httplib::Client cli(std::string(BIND_HOST) + ":" + std::to_string(BIND_PORT));
        auto res = cli.Get("/health");
        return (res && res->status == 200) ? 0 : 1;
    }

    httplib::Server server;

    // -----------------------------------------------------------------------
    // POST /process
    // -----------------------------------------------------------------------
    server.Post("/process", [](const httplib::Request& req, httplib::Response& res) {
        try {
            std::cout << "[Decoder] POST /process received payload size: "
                      << req.body.size() << " bytes" << std::endl;

            // Parse incoming JSON
            json envelope = json::parse(req.body);

            // Execute business logic
            json processed = process_envelope(envelope);

            // Serialize response
            std::string response_body = processed.dump(2);

            res.status = 200;
            res.set_header("Content-Type", "application/json");
            res.set_content(response_body, "application/json");

            std::cout << "[Decoder] POST /process completed successfully (200)"
                      << std::endl;
        } catch (const json::exception& e) {
            std::cerr << "[Decoder] JSON parse error: " << e.what() << std::endl;
            res.status = 400;
            json err = {{"error", "Invalid JSON"}, {"details", e.what()}};
            res.set_content(err.dump(), "application/json");
        } catch (const std::exception& e) {
            std::cerr << "[Decoder] Processing error: " << e.what() << std::endl;
            res.status = 500;
            json err = {{"error", "Processing failed"}, {"details", e.what()}};
            res.set_content(err.dump(), "application/json");
        }
    });

    // -----------------------------------------------------------------------
    // GET /health  (Liveness)
    // -----------------------------------------------------------------------
    server.Get("/health", [](const httplib::Request&, httplib::Response& res) {
        res.status = 200;
        res.set_content("{\"status\":\"alive\"}", "application/json");
    });

    // -----------------------------------------------------------------------
    // GET /ready   (Readiness)
    // -----------------------------------------------------------------------
    server.Get("/ready", [](const httplib::Request&, httplib::Response& res) {
        res.status = 200;
        res.set_content("{\"status\":\"ready\"}", "application/json");
    });

    std::cout << "[Decoder] C++ Business Logic Server starting on "
              << BIND_HOST << ":" << BIND_PORT << std::endl;

    if (!server.listen(BIND_HOST, BIND_PORT)) {
        std::cerr << "[Decoder] Failed to bind to " << BIND_HOST << ":"
                  << BIND_PORT << std::endl;
        return EXIT_FAILURE;
    }

    return EXIT_SUCCESS;
}
