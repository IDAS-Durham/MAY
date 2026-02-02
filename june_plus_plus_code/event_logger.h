#pragma once

#include <string>
#include <vector>
#include <unordered_set>
#include <H5Cpp.h>
#include "../core/types.h"
#include "../core/world_state.h"
#include "../core/config.h"

namespace june {

// =============================================================================
// Lightweight Population Record for Denominators
// =============================================================================

// Minimal demographic data (~16 bytes instead of 228 bytes)
struct PopulationSummaryRecord {
    int person_id;              // 4 bytes
    uint8_t age_group;          // 1 byte (0-17 for 5-year groups)
    uint8_t sex_code;           // 1 byte (0=M, 1=F, 2=other)
    int geo_unit_id;            // 4 bytes
    uint8_t ethnicity_code;     // 1 byte
    uint8_t schedule_type_code; // 1 byte
    uint8_t has_comorbidities;  // 1 byte (0=no, 1=yes)
    uint8_t work_mode_code;     // 1 byte
    // Total: 16 bytes vs 228 bytes for full PersonRecord
};

// =============================================================================
// Event Types
// =============================================================================

struct InfectionEvent {
    PersonId person_id;
    PersonId infector_id;  // Who infected this person
    VenueId venue_id;
    double time;  // Simulation time in days
};

struct SymptomChangeEvent {
    PersonId person_id;
    VenueId venue_id;  // Current venue at time of symptom change
    double time;
    std::string old_symptom;
    std::string new_symptom;
};

struct DeathEvent {
    PersonId person_id;
    VenueId venue_id;  // Venue where person was at time of death
    double time;
};

struct HospitalAdmissionEvent {
    PersonId person_id;
    VenueId hospital_id;  // Hospital venue ID
    double time;
    std::string reason;   // "hospitalised" or "intensive_care"
};

struct ICUAdmissionEvent {
    PersonId person_id;
    VenueId hospital_id;  // Hospital venue ID (same as where they were)
    double time;
};

struct HospitalDischargeEvent {
    PersonId person_id;
    VenueId hospital_id;  // Hospital venue ID
    double time;
    std::string outcome;  // "recovered", "dead_hospital", "dead_icu", or "transferred_to_icu"
};

// =============================================================================
// HDF5 Record Structures (Local to EventLogger implementation)
// =============================================================================

namespace detail {

struct SymptomChangeRecord {
    int person_id;
    int venue_id;
    double time;
    char old_symptom[64];
    char new_symptom[64];
};

struct HospitalAdmissionRecord {
    int person_id;
    int hospital_id;
    double time;
    char reason[64];
};

struct HospitalDischargeRecord {
    int person_id;
    int hospital_id;
    double time;
    char outcome[64];
};

struct PersonRecord {
    int person_id;
    float age;
    char sex[16];
    int geo_unit_id;
    int is_dead;
    double death_time;
    char schedule_type[64];

    // Activity counts
    int num_activities;
    int num_residence_venues;
    int num_primary_activities;
    int num_leisure_venues;
    int num_medical_facilities;
};

struct PersonActivityRecord {
    int person_id;
    char activity_name[64];
    int venue_id;
    int subset_index;
    int activity_index;
};

struct VenueRecord {
    int venue_id;
    char name[128];
    char type[64];
    int geo_unit_id;
    int n_subsets;
};

} // namespace detail

// =============================================================================
// EventLogger - Collects and saves epidemic events to HDF5
// =============================================================================

class EventLogger {
public:
    EventLogger();
    ~EventLogger();

    // Log events
    void logInfection(PersonId person_id, PersonId infector_id, VenueId venue_id, double time);
    void logSymptomChange(PersonId person_id, VenueId venue_id, double time,
                         const std::string& old_symptom, const std::string& new_symptom);
    void logDeath(PersonId person_id, VenueId venue_id, double time);

    // Log hospitalization events
    void logHospitalAdmission(PersonId person_id, VenueId hospital_id, double time,
                             const std::string& reason);
    void logICUAdmission(PersonId person_id, VenueId hospital_id, double time);
    void logHospitalDischarge(PersonId person_id, VenueId hospital_id, double time,
                             const std::string& outcome);

    // Save all events to HDF5 file
    void saveToHDF5(const std::string& filename, const Config& config);

    // Save all events + lookup tables to HDF5 file (with config-based selective saving)
    void saveToHDF5WithLookups(const std::string& filename, const WorldState& world, const Config& config);

    // Clear all events (useful for starting fresh)
    void clear();

    // Get event counts
    size_t getInfectionCount() const { return infections_.size(); }
    size_t getSymptomChangeCount() const { return symptom_changes_.size(); }
    size_t getDeathCount() const { return deaths_.size(); }
    size_t getHospitalAdmissionCount() const { return hospital_admissions_.size(); }
    size_t getICUAdmissionCount() const { return icu_admissions_.size(); }
    size_t getHospitalDischargeCount() const { return hospital_discharges_.size(); }

    // Static method to merge multiple event files into one
    static void mergeEventFiles(const std::vector<std::string>& input_files, 
                                const std::string& output_file);

private:
    std::vector<InfectionEvent> infections_;
    std::vector<SymptomChangeEvent> symptom_changes_;
    std::vector<DeathEvent> deaths_;
    std::vector<HospitalAdmissionEvent> hospital_admissions_;
    std::vector<ICUAdmissionEvent> icu_admissions_;
    std::vector<HospitalDischargeEvent> hospital_discharges_;

    // Helper methods for HDF5 writing
    void writeInfectionEvents(H5::H5File& file);
    void writeSymptomChangeEvents(H5::H5File& file);
    void writeDeathEvents(H5::H5File& file);
    void writeHospitalAdmissionEvents(H5::H5File& file);
    void writeICUAdmissionEvents(H5::H5File& file);
    void writeHospitalDischargeEvents(H5::H5File& file);

    // Helper methods for lookup tables
    void writePersonLookupTable(H5::H5File& file, const WorldState& world, const Config& config);
    void writeVenueLookupTable(H5::H5File& file, const WorldState& world, const Config& config);
    void writePersonActivitiesTable(H5::H5File& file, const WorldState& world, const Config& config);

    // Write minimal population summary for denominators
    void writePopulationSummary(H5::H5File& file, const WorldState& world, const Config& config);

    // Static Helpers for Merging (private)
    static void mergeInfectionEvents(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergeSymptomChangeEvents(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergeDeathEvents(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergeHospitalAdmissionEvents(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergeICUAdmissionEvents(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergeHospitalDischargeEvents(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergePeopleLookup(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergeVenueLookup(H5::H5File& out_file, const std::vector<std::string>& input_files);
    static void mergePersonActivityLookup(H5::H5File& out_file, const std::vector<std::string>& input_files);

    // Helper: Create HDF5 dataset with compression
    H5::DataSet createCompressedDataset(H5::H5File& file, const std::string& name,
                                         const H5::DataType& datatype, const H5::DataSpace& dataspace,
                                         int compression_level);

    // Template helper: writing a simple dataset
    template<typename T>
    static void writeDatasetTemplate(H5::H5File& file, const std::string& name,
                                     const std::vector<T>& data, const H5::CompType& type) {
        if (data.empty()) return;
        hsize_t dims[1] = {data.size()};
        H5::DataSpace dataspace(1, dims);
        H5::DataSet dataset = file.createDataSet(name, type, dataspace);
        dataset.write(data.data(), type);
    }

    // Template helper: merging records from multiple files
    template<typename T>
    static void mergeDatasetTemplate(H5::H5File& out_file, const std::string& name,
                                     const std::vector<std::string>& input_files,
                                     const H5::CompType& type) {
        std::vector<T> all_data;
        for (const auto& f : input_files) {
            try {
                H5::H5File file(f, H5F_ACC_RDONLY);
                if (H5Lexists(file.getId(), name.c_str(), H5P_DEFAULT)) {
                    H5::DataSet ds = file.openDataSet(name);
                    H5::DataSpace space = ds.getSpace();
                    hsize_t dims[1];
                    space.getSimpleExtentDims(dims);
                    if (dims[0] > 0) {
                        size_t offset = all_data.size();
                        all_data.resize(offset + dims[0]);
                        ds.read(all_data.data() + offset, type);
                    }
                }
            } catch (...) {}
        }
        if (!all_data.empty()) {
            hsize_t dims[1] = {all_data.size()};
            H5::DataSpace space(1, dims);
            H5::DataSet ds = out_file.createDataSet(name, type, space);
            ds.write(all_data.data(), type);
            std::cout << "  Merged " << all_data.size() << " records for " << name << std::endl;
        }
    }

    // Helper: Get infected person IDs
    std::unordered_set<PersonId> getInfectedPersonIds() const;
};

} // namespace june
