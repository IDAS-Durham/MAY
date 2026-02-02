#include "utils/event_logger.h"
#include <iostream>
#include <stdexcept>
#include <cstring>

namespace june {

EventLogger::EventLogger() {
    // Reserve some space to avoid frequent reallocations
    infections_.reserve(10000);
    symptom_changes_.reserve(50000);
    deaths_.reserve(1000);
    hospital_admissions_.reserve(5000);
    icu_admissions_.reserve(2000);
    hospital_discharges_.reserve(5000);
}

EventLogger::~EventLogger() {
    // Nothing to clean up
}

void EventLogger::logInfection(PersonId person_id, PersonId infector_id, VenueId venue_id, double time) {
    infections_.push_back({person_id, infector_id, venue_id, time});
}

void EventLogger::logSymptomChange(PersonId person_id, VenueId venue_id, double time,
                                   const std::string& old_symptom, const std::string& new_symptom) {
    symptom_changes_.push_back({person_id, venue_id, time, old_symptom, new_symptom});
}

void EventLogger::logDeath(PersonId person_id, VenueId venue_id, double time) {
    deaths_.push_back({person_id, venue_id, time});
}

void EventLogger::logHospitalAdmission(PersonId person_id, VenueId hospital_id, double time,
                                        const std::string& reason) {
    hospital_admissions_.push_back({person_id, hospital_id, time, reason});
}

void EventLogger::logICUAdmission(PersonId person_id, VenueId hospital_id, double time) {
    icu_admissions_.push_back({person_id, hospital_id, time});
}

void EventLogger::logHospitalDischarge(PersonId person_id, VenueId hospital_id, double time,
                                        const std::string& outcome) {
    hospital_discharges_.push_back({person_id, hospital_id, time, outcome});
}

void EventLogger::clear() {
    infections_.clear();
    symptom_changes_.clear();
    deaths_.clear();
    hospital_admissions_.clear();
    icu_admissions_.clear();
    hospital_discharges_.clear();
}

void EventLogger::saveToHDF5(const std::string& filename, const Config& config) {
    std::cout << "\n=== Saving Events to HDF5: " << filename << " ===" << std::endl;
    std::cout << "  Compression level: " << config.simulation.compression_level << std::endl;
    std::cout << "  Infection events: " << infections_.size() << std::endl;
    std::cout << "  Symptom change events: " << symptom_changes_.size() << std::endl;
    std::cout << "  Death events: " << deaths_.size() << std::endl;
    std::cout << "  Hospital admission events: " << hospital_admissions_.size() << std::endl;
    std::cout << "  ICU admission events: " << icu_admissions_.size() << std::endl;
    std::cout << "  Hospital discharge events: " << hospital_discharges_.size() << std::endl;

    try {
        // Create or open HDF5 file
        H5::H5File file(filename, H5F_ACC_TRUNC);

        // Create events group
        H5::Group events_group = file.createGroup("/events");

        // Write each event type
        if (!infections_.empty()) {
            writeInfectionEvents(file);
        }
        if (!symptom_changes_.empty()) {
            writeSymptomChangeEvents(file);
        }
        if (!deaths_.empty()) {
            writeDeathEvents(file);
        }
        if (!hospital_admissions_.empty()) {
            writeHospitalAdmissionEvents(file);
        }
        if (!icu_admissions_.empty()) {
            writeICUAdmissionEvents(file);
        }
        if (!hospital_discharges_.empty()) {
            writeHospitalDischargeEvents(file);
        }

        std::cout << "Events saved successfully!" << std::endl;
    }
    catch (const H5::Exception& e) {
        std::cerr << "HDF5 error while saving events: " << e.getDetailMsg() << std::endl;
        throw std::runtime_error("Failed to save events to HDF5 file");
    }
}

void EventLogger::saveToHDF5WithLookups(const std::string& filename, const WorldState& world, const Config& config) {
    std::cout << "\n=== Saving Events + Lookup Tables to HDF5: " << filename << " ===" << std::endl;
    std::cout << "  Compression level: " << config.simulation.compression_level << std::endl;
    std::cout << "  Person details mode: " << config.simulation.save_full_person_details << std::endl;
    std::cout << "  Population summary: " << (config.simulation.save_population_summary ? "yes" : "no") << std::endl;
    std::cout << "  Person activities mode: " << config.simulation.save_person_activities << std::endl;
    std::cout << "  Infection events: " << infections_.size() << std::endl;
    std::cout << "  Symptom change events: " << symptom_changes_.size() << std::endl;
    std::cout << "  Death events: " << deaths_.size() << std::endl;
    std::cout << "  Hospital admission events: " << hospital_admissions_.size() << std::endl;
    std::cout << "  ICU admission events: " << icu_admissions_.size() << std::endl;
    std::cout << "  Hospital discharge events: " << hospital_discharges_.size() << std::endl;
    std::cout << "  People: " << world.people.size() << std::endl;
    std::cout << "  Venues: " << world.venues.size() << std::endl;

    try {
        // Create or open HDF5 file
        H5::H5File file(filename, H5F_ACC_TRUNC);

        // Create events group
        H5::Group events_group = file.createGroup("/events");

        // Write each event type
        if (!infections_.empty()) {
            writeInfectionEvents(file);
        }
        if (!symptom_changes_.empty()) {
            writeSymptomChangeEvents(file);
        }
        if (!deaths_.empty()) {
            writeDeathEvents(file);
        }
        if (!hospital_admissions_.empty()) {
            writeHospitalAdmissionEvents(file);
        }
        if (!icu_admissions_.empty()) {
            writeICUAdmissionEvents(file);
        }
        if (!hospital_discharges_.empty()) {
            writeHospitalDischargeEvents(file);
        }

        // Create lookups group
        H5::Group lookups_group = file.createGroup("/lookups");

        // Write lookup tables based on config
        if (config.simulation.save_full_person_details != "none") {
            writePersonLookupTable(file, world, config);
        }

        if (config.simulation.save_population_summary) {
            writePopulationSummary(file, world, config);
        }

        writeVenueLookupTable(file, world, config);

        if (config.simulation.save_person_activities != "none") {
            writePersonActivitiesTable(file, world, config);
        }

        std::cout << "Events and lookup tables saved successfully!" << std::endl;
    }
    catch (const H5::Exception& e) {
        std::cerr << "HDF5 error while saving: " << e.getDetailMsg() << std::endl;
        throw std::runtime_error("Failed to save events and lookups to HDF5 file");
    }
}

void EventLogger::writeInfectionEvents(H5::H5File& file) {
    H5::CompType type(sizeof(InfectionEvent));
    type.insertMember("person_id", HOFFSET(InfectionEvent, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("infector_id", HOFFSET(InfectionEvent, infector_id), H5::PredType::NATIVE_INT);
    type.insertMember("venue_id", HOFFSET(InfectionEvent, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(InfectionEvent, time), H5::PredType::NATIVE_DOUBLE);
    writeDatasetTemplate(file, "/events/infections", infections_, type);
}

void EventLogger::writeSymptomChangeEvents(H5::H5File& file) {
    std::vector<detail::SymptomChangeRecord> records(symptom_changes_.size());
    for (size_t i = 0; i < symptom_changes_.size(); ++i) {
        records[i].person_id = symptom_changes_[i].person_id;
        records[i].venue_id = symptom_changes_[i].venue_id;
        records[i].time = symptom_changes_[i].time;
        strncpy(records[i].old_symptom, symptom_changes_[i].old_symptom.c_str(), 63);
        records[i].old_symptom[63] = '\0';
        strncpy(records[i].new_symptom, symptom_changes_[i].new_symptom.c_str(), 63);
        records[i].new_symptom[63] = '\0';
    }

    H5::StrType str_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::SymptomChangeRecord));
    type.insertMember("person_id", HOFFSET(detail::SymptomChangeRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("venue_id", HOFFSET(detail::SymptomChangeRecord, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(detail::SymptomChangeRecord, time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("old_symptom", HOFFSET(detail::SymptomChangeRecord, old_symptom), str_type);
    type.insertMember("new_symptom", HOFFSET(detail::SymptomChangeRecord, new_symptom), str_type);
    
    writeDatasetTemplate(file, "/events/symptom_changes", records, type);
}

void EventLogger::writeDeathEvents(H5::H5File& file) {
    H5::CompType type(sizeof(DeathEvent));
    type.insertMember("person_id", HOFFSET(DeathEvent, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("venue_id", HOFFSET(DeathEvent, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(DeathEvent, time), H5::PredType::NATIVE_DOUBLE);
    writeDatasetTemplate(file, "/events/deaths", deaths_, type);
}

void EventLogger::writeHospitalAdmissionEvents(H5::H5File& file) {
    if (hospital_admissions_.empty()) return;
    std::vector<detail::HospitalAdmissionRecord> records(hospital_admissions_.size());
    for (size_t i = 0; i < hospital_admissions_.size(); ++i) {
        records[i].person_id = hospital_admissions_[i].person_id;
        records[i].hospital_id = hospital_admissions_[i].hospital_id;
        records[i].time = hospital_admissions_[i].time;
        strncpy(records[i].reason, hospital_admissions_[i].reason.c_str(), 63);
        records[i].reason[63] = '\0';
    }

    H5::StrType str_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::HospitalAdmissionRecord));
    type.insertMember("person_id", HOFFSET(detail::HospitalAdmissionRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("hospital_id", HOFFSET(detail::HospitalAdmissionRecord, hospital_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(detail::HospitalAdmissionRecord, time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("reason", HOFFSET(detail::HospitalAdmissionRecord, reason), str_type);
    writeDatasetTemplate(file, "/events/hospital_admissions", records, type);
}

void EventLogger::writeICUAdmissionEvents(H5::H5File& file) {
    H5::CompType type(sizeof(ICUAdmissionEvent));
    type.insertMember("person_id", HOFFSET(ICUAdmissionEvent, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("hospital_id", HOFFSET(ICUAdmissionEvent, hospital_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(ICUAdmissionEvent, time), H5::PredType::NATIVE_DOUBLE);
    writeDatasetTemplate(file, "/events/icu_admissions", icu_admissions_, type);
}

void EventLogger::writeHospitalDischargeEvents(H5::H5File& file) {
    if (hospital_discharges_.empty()) return;
    std::vector<detail::HospitalDischargeRecord> records(hospital_discharges_.size());
    for (size_t i = 0; i < hospital_discharges_.size(); ++i) {
        records[i].person_id = hospital_discharges_[i].person_id;
        records[i].hospital_id = hospital_discharges_[i].hospital_id;
        records[i].time = hospital_discharges_[i].time;
        strncpy(records[i].outcome, hospital_discharges_[i].outcome.c_str(), 63);
        records[i].outcome[63] = '\0';
    }

    H5::StrType str_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::HospitalDischargeRecord));
    type.insertMember("person_id", HOFFSET(detail::HospitalDischargeRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("hospital_id", HOFFSET(detail::HospitalDischargeRecord, hospital_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(detail::HospitalDischargeRecord, time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("outcome", HOFFSET(detail::HospitalDischargeRecord, outcome), str_type);
    writeDatasetTemplate(file, "/events/hospital_discharges", records, type);
}

void EventLogger::mergeEventFiles(const std::vector<std::string>& input_files, 
                                   const std::string& output_file) {
    std::cout << "\n=== Merging Event Files ===" << std::endl;
    std::cout << "Input files: " << input_files.size() << std::endl;
    std::cout << "Output file: " << output_file << std::endl;

    try {
        H5::H5File out_file(output_file, H5F_ACC_TRUNC);
        out_file.createGroup("/events");
        out_file.createGroup("/lookups");

        mergeInfectionEvents(out_file, input_files);
        mergeSymptomChangeEvents(out_file, input_files);
        mergeDeathEvents(out_file, input_files);
        mergeHospitalAdmissionEvents(out_file, input_files);
        mergeICUAdmissionEvents(out_file, input_files);
        mergeHospitalDischargeEvents(out_file, input_files);
        
        mergePeopleLookup(out_file, input_files);
        mergeVenueLookup(out_file, input_files);
        mergePersonActivityLookup(out_file, input_files);

        std::cout << "\nMerge complete!" << std::endl;
    } catch (const H5::Exception& e) {
        std::cerr << "Error writing merged file: " << e.getDetailMsg() << std::endl;
        throw std::runtime_error("Failed to write merged event file");
    }
}

void EventLogger::mergeInfectionEvents(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::CompType type(sizeof(InfectionEvent));
    type.insertMember("person_id", HOFFSET(InfectionEvent, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("infector_id", HOFFSET(InfectionEvent, infector_id), H5::PredType::NATIVE_INT);
    type.insertMember("venue_id", HOFFSET(InfectionEvent, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(InfectionEvent, time), H5::PredType::NATIVE_DOUBLE);
    mergeDatasetTemplate<InfectionEvent>(out_file, "/events/infections", input_files, type);
}

void EventLogger::mergeSymptomChangeEvents(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::StrType str_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::SymptomChangeRecord));
    type.insertMember("person_id", HOFFSET(detail::SymptomChangeRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("venue_id", HOFFSET(detail::SymptomChangeRecord, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(detail::SymptomChangeRecord, time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("old_symptom", HOFFSET(detail::SymptomChangeRecord, old_symptom), str_type);
    type.insertMember("new_symptom", HOFFSET(detail::SymptomChangeRecord, new_symptom), str_type);
    mergeDatasetTemplate<detail::SymptomChangeRecord>(out_file, "/events/symptom_changes", input_files, type);
}

void EventLogger::mergeDeathEvents(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::CompType type(sizeof(DeathEvent));
    type.insertMember("person_id", HOFFSET(DeathEvent, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("venue_id", HOFFSET(DeathEvent, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(DeathEvent, time), H5::PredType::NATIVE_DOUBLE);
    mergeDatasetTemplate<DeathEvent>(out_file, "/events/deaths", input_files, type);
}

void EventLogger::mergeHospitalAdmissionEvents(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::StrType str_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::HospitalAdmissionRecord));
    type.insertMember("person_id", HOFFSET(detail::HospitalAdmissionRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("hospital_id", HOFFSET(detail::HospitalAdmissionRecord, hospital_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(detail::HospitalAdmissionRecord, time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("reason", HOFFSET(detail::HospitalAdmissionRecord, reason), str_type);
    mergeDatasetTemplate<detail::HospitalAdmissionRecord>(out_file, "/events/hospital_admissions", input_files, type);
}

void EventLogger::mergeICUAdmissionEvents(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::CompType type(sizeof(ICUAdmissionEvent));
    type.insertMember("person_id", HOFFSET(ICUAdmissionEvent, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("hospital_id", HOFFSET(ICUAdmissionEvent, hospital_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(ICUAdmissionEvent, time), H5::PredType::NATIVE_DOUBLE);
    mergeDatasetTemplate<ICUAdmissionEvent>(out_file, "/events/icu_admissions", input_files, type);
}

void EventLogger::mergeHospitalDischargeEvents(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::StrType str_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::HospitalDischargeRecord));
    type.insertMember("person_id", HOFFSET(detail::HospitalDischargeRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("hospital_id", HOFFSET(detail::HospitalDischargeRecord, hospital_id), H5::PredType::NATIVE_INT);
    type.insertMember("time", HOFFSET(detail::HospitalDischargeRecord, time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("outcome", HOFFSET(detail::HospitalDischargeRecord, outcome), str_type);
    mergeDatasetTemplate<detail::HospitalDischargeRecord>(out_file, "/events/hospital_discharges", input_files, type);
}

void EventLogger::mergePeopleLookup(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    std::vector<detail::PersonRecord> all_data;
    H5::StrType sex_type(H5::PredType::C_S1, 16);
    H5::StrType schedule_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::PersonRecord));
    type.insertMember("person_id", HOFFSET(detail::PersonRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("age", HOFFSET(detail::PersonRecord, age), H5::PredType::NATIVE_FLOAT);
    type.insertMember("sex", HOFFSET(detail::PersonRecord, sex), sex_type);
    type.insertMember("geo_unit_id", HOFFSET(detail::PersonRecord, geo_unit_id), H5::PredType::NATIVE_INT);
    type.insertMember("is_dead", HOFFSET(detail::PersonRecord, is_dead), H5::PredType::NATIVE_INT);
    type.insertMember("death_time", HOFFSET(detail::PersonRecord, death_time), H5::PredType::NATIVE_DOUBLE);
    type.insertMember("schedule_type", HOFFSET(detail::PersonRecord, schedule_type), schedule_type);
    type.insertMember("num_activities", HOFFSET(detail::PersonRecord, num_activities), H5::PredType::NATIVE_INT);
    type.insertMember("num_residence_venues", HOFFSET(detail::PersonRecord, num_residence_venues), H5::PredType::NATIVE_INT);
    type.insertMember("num_primary_activities", HOFFSET(detail::PersonRecord, num_primary_activities), H5::PredType::NATIVE_INT);
    type.insertMember("num_leisure_venues", HOFFSET(detail::PersonRecord, num_leisure_venues), H5::PredType::NATIVE_INT);
    type.insertMember("num_medical_facilities", HOFFSET(detail::PersonRecord, num_medical_facilities), H5::PredType::NATIVE_INT);

    std::unordered_set<int> seen;
    for (const auto& f : input_files) {
        try {
            H5::H5File file(f, H5F_ACC_RDONLY);
            if (!H5Lexists(file.getId(), "/lookups/people", H5P_DEFAULT)) continue;
            H5::DataSet ds = file.openDataSet("/lookups/people");
            hsize_t dims[1];
            ds.getSpace().getSimpleExtentDims(dims);
            std::vector<detail::PersonRecord> chunk(dims[0]);
            ds.read(chunk.data(), type);
            for (const auto& r : chunk) if (seen.insert(r.person_id).second) all_data.push_back(r);
        } catch (...) {}
    }
    writeDatasetTemplate(out_file, "/lookups/people", all_data, type);
    
    // --- Merge Dynamic Properties ---
    std::unordered_set<std::string> all_prop_keys;
    for (const auto& f : input_files) {
        try {
            H5::H5File file(f, H5F_ACC_RDONLY);
            if (H5Lexists(file.getId(), "/lookups/people_properties", H5P_DEFAULT)) {
                H5::Group group = file.openGroup("/lookups/people_properties");
                hsize_t n = group.getNumObjs();
                for (hsize_t i = 0; i < n; ++i) {
                    all_prop_keys.insert(group.getObjnameByIdx(i));
                }
            }
        } catch (...) {}
    }
    
    if (!all_prop_keys.empty()) {
        H5::Group prop_group = out_file.createGroup("/lookups/people_properties");
        
        // Build map for person_id -> index in all_data
        std::unordered_map<int, size_t> id_to_idx;
        for (size_t i = 0; i < all_data.size(); ++i) {
            id_to_idx[all_data[i].person_id] = i;
        }

        for (const auto& key : all_prop_keys) {
            std::vector<std::string> merged_props(all_data.size(), "unknown");
            
            for (const auto& f : input_files) {
                try {
                    H5::H5File file(f, H5F_ACC_RDONLY);
                    if (!H5Lexists(file.getId(), "/lookups/people", H5P_DEFAULT)) continue;
                    if (!H5Lexists(file.getId(), ("/lookups/people_properties/" + key).c_str(), H5P_DEFAULT)) continue;
                    
                    // Read IDs in this file
                    H5::DataSet id_ds = file.openDataSet("/lookups/people");
                    hsize_t dims[1];
                    id_ds.getSpace().getSimpleExtentDims(dims);
                    if (dims[0] == 0) continue;

                    std::vector<detail::PersonRecord> records(dims[0]);
                    id_ds.read(records.data(), type);
                    
                    // Read property values in this file
                    H5::DataSet prop_ds = file.openDataSet("/lookups/people_properties/" + key);
                    H5::DataSpace prop_space = prop_ds.getSpace();
                    H5::StrType prop_type = prop_ds.getStrType();
                    
                    std::vector<std::string> values(dims[0]);
                    if (prop_type.isVariableStr()) {
                        std::vector<char*> rdata(dims[0]);
                        prop_ds.read(rdata.data(), prop_type);
                        for (size_t i = 0; i < dims[0]; ++i) if (rdata[i]) values[i] = rdata[i];
                        H5::DataSet::vlenReclaim(rdata.data(), prop_type, prop_space);
                    } else {
                        size_t s = prop_type.getSize();
                        std::vector<char> buf(dims[0] * s);
                        prop_ds.read(buf.data(), prop_type);
                        for (size_t i = 0; i < dims[0]; ++i) {
                            values[i] = std::string(&buf[i * s], s);
                            size_t p = values[i].find('\0');
                            if (p != std::string::npos) values[i].resize(p);
                        }
                    }
                    
                    // Map to merged vector
                    for (size_t i = 0; i < dims[0]; ++i) {
                        auto it = id_to_idx.find(records[i].person_id);
                        if (it != id_to_idx.end()) {
                            merged_props[it->second] = values[i];
                        }
                    }
                } catch (...) {}
            }
            
            // Write merged property dataset
            hsize_t out_dims[1] = {merged_props.size()};
            H5::DataSpace out_space(1, out_dims);
            H5::StrType out_type(H5::PredType::C_S1, H5T_VARIABLE);
            H5::DataSet ds = prop_group.createDataSet(key, out_type, out_space);
            std::vector<const char*> c_strs;
            for (const auto& s : merged_props) c_strs.push_back(s.c_str());
            ds.write(c_strs.data(), out_type);
            std::cout << "    - Merged property: " << key << std::endl;
        }
    }
}

void EventLogger::mergeVenueLookup(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    std::vector<detail::VenueRecord> all_data;
    H5::StrType name_type(H5::PredType::C_S1, 128);
    H5::StrType type_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::VenueRecord));
    type.insertMember("venue_id", HOFFSET(detail::VenueRecord, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("name", HOFFSET(detail::VenueRecord, name), name_type);
    type.insertMember("type", HOFFSET(detail::VenueRecord, type), type_type);
    type.insertMember("geo_unit_id", HOFFSET(detail::VenueRecord, geo_unit_id), H5::PredType::NATIVE_INT);
    type.insertMember("n_subsets", HOFFSET(detail::VenueRecord, n_subsets), H5::PredType::NATIVE_INT);

    std::unordered_set<int> seen_venues;
    for (const auto& f : input_files) {
        try {
            H5::H5File file(f, H5F_ACC_RDONLY);
            if (!H5Lexists(file.getId(), "/lookups/venues", H5P_DEFAULT)) continue;
            H5::DataSet ds = file.openDataSet("/lookups/venues");
            hsize_t dims[1];
            ds.getSpace().getSimpleExtentDims(dims);
            std::vector<detail::VenueRecord> chunk(dims[0]);
            ds.read(chunk.data(), type);
            for (const auto& r : chunk) if (seen_venues.insert(r.venue_id).second) all_data.push_back(r);
        } catch (...) {}
    }
    writeDatasetTemplate(out_file, "/lookups/venues", all_data, type);
}

void EventLogger::mergePersonActivityLookup(H5::H5File& out_file, const std::vector<std::string>& input_files) {
    H5::StrType name_type(H5::PredType::C_S1, 64);
    H5::CompType type(sizeof(detail::PersonActivityRecord));
    type.insertMember("person_id", HOFFSET(detail::PersonActivityRecord, person_id), H5::PredType::NATIVE_INT);
    type.insertMember("activity_name", HOFFSET(detail::PersonActivityRecord, activity_name), name_type);
    type.insertMember("venue_id", HOFFSET(detail::PersonActivityRecord, venue_id), H5::PredType::NATIVE_INT);
    type.insertMember("subset_index", HOFFSET(detail::PersonActivityRecord, subset_index), H5::PredType::NATIVE_INT);
    type.insertMember("activity_index", HOFFSET(detail::PersonActivityRecord, activity_index), H5::PredType::NATIVE_INT);
    mergeDatasetTemplate<detail::PersonActivityRecord>(out_file, "/lookups/person_activities", input_files, type);
}

void EventLogger::writePersonLookupTable(H5::H5File& file, const WorldState& world, const Config& config) {
    // Determine which people to save based on config
    std::unordered_set<PersonId> people_to_save;

    if (config.simulation.save_full_person_details == "all") {
        // Save everyone
        for (const auto& person : world.people) {
            people_to_save.insert(person.id);
        }
    } else if (config.simulation.save_full_person_details == "infected_only") {
        // Save only infected people
        people_to_save = getInfectedPersonIds();
    } else {
        // "none" - don't save anything
        return;
    }

    size_t n = people_to_save.size();
    if (n == 0) return;

    std::cout << "  Writing person lookup table (" << config.simulation.save_full_person_details
              << " mode: " << n << " people)..." << std::endl;

    // Convert data to record format (only for selected people)
    std::vector<detail::PersonRecord> records;
    records.reserve(n);
    for (const auto& person : world.people) {
        if (!people_to_save.count(person.id)) {
            continue;  // Skip this person
        }

        detail::PersonRecord record;
        record.person_id = person.id;
        record.age = person.age;

        // Copy sex string
        strncpy(record.sex, person.sex.c_str(), 15);
        record.sex[15] = '\0';

        record.geo_unit_id = person.geo_unit_id;
        record.is_dead = person.is_dead ? 1 : 0;
        record.death_time = person.death_time;

        // Schedule type
        std::string sched_type = person.schedule_type.empty() ? "unknown" : person.schedule_type;
        strncpy(record.schedule_type, sched_type.c_str(), 63);
        record.schedule_type[63] = '\0';

        // Activity counts
        record.num_activities = static_cast<int>(person.activities.size());
        
        const auto& residence = person.getActivities("residence");
        record.num_residence_venues = static_cast<int>(residence.size());

        const auto& primary = person.getActivities("primary_activity");
        record.num_primary_activities = static_cast<int>(primary.size());

        const auto& leisure = person.getActivities("leisure");
        record.num_leisure_venues = static_cast<int>(leisure.size());
        
        const auto& medical = person.getActivities("medical_facility");
        record.num_medical_facilities = static_cast<int>(medical.size());

        records.push_back(record);
    }

    // Create compound datatype
    H5::StrType sex_type(H5::PredType::C_S1, 16);
    H5::StrType schedule_type(H5::PredType::C_S1, 64);

    H5::CompType person_type(sizeof(detail::PersonRecord));
    person_type.insertMember("person_id", HOFFSET(detail::PersonRecord, person_id),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("age", HOFFSET(detail::PersonRecord, age),
                             H5::PredType::NATIVE_FLOAT);
    person_type.insertMember("sex", HOFFSET(detail::PersonRecord, sex),
                             sex_type);
    person_type.insertMember("geo_unit_id", HOFFSET(detail::PersonRecord, geo_unit_id),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("is_dead", HOFFSET(detail::PersonRecord, is_dead),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("death_time", HOFFSET(detail::PersonRecord, death_time),
                             H5::PredType::NATIVE_DOUBLE);
    person_type.insertMember("schedule_type", HOFFSET(detail::PersonRecord, schedule_type),
                             schedule_type);
    person_type.insertMember("num_activities", HOFFSET(detail::PersonRecord, num_activities),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("num_residence_venues", HOFFSET(detail::PersonRecord, num_residence_venues),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("num_primary_activities", HOFFSET(detail::PersonRecord, num_primary_activities),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("num_leisure_venues", HOFFSET(detail::PersonRecord, num_leisure_venues),
                             H5::PredType::NATIVE_INT);
    person_type.insertMember("num_medical_facilities", HOFFSET(detail::PersonRecord, num_medical_facilities),
                             H5::PredType::NATIVE_INT);

    // Create dataspace
    hsize_t dims[1] = {records.size()};
    H5::DataSpace dataspace(1, dims);

    // Create and write dataset with compression
    H5::DataSet dataset = createCompressedDataset(file, "/lookups/people",
                                                   person_type, dataspace,
                                                   config.simulation.compression_level);
    dataset.write(records.data(), person_type);

    std::cout << "  Wrote person lookup table: " << records.size() << " people" << std::endl;

    // --- Dynamic Properties Saving ---
    std::cout << "  Writing dynamic properties..." << std::endl;
    std::cout << "  Writing dynamic properties..." << std::endl;
    // Use the static property names list
    const auto& all_keys = Person::property_names;

    if (!all_keys.empty()) {
        H5::Group prop_group = file.createGroup("/lookups/people_properties");
        for (const auto& key : all_keys) {
            std::vector<std::string> values;
            values.reserve(n);
            for (const auto& person : world.people) {
                if (!people_to_save.count(person.id)) continue;
                
                auto prop = person.getProperty(key);
                if (prop.has_value()) {
                    const auto& val = *prop;
                    if (std::holds_alternative<std::string>(val)) values.push_back(std::get<std::string>(val));
                    else if (std::holds_alternative<int32_t>(val)) values.push_back(std::to_string(std::get<int32_t>(val)));
                    else if (std::holds_alternative<bool>(val)) values.push_back(std::get<bool>(val) ? "true" : "false");
                    else if (std::holds_alternative<float>(val)) values.push_back(std::to_string(std::get<float>(val)));
                    else values.push_back("unknown");
                } else values.push_back("");
            }
            
            hsize_t dims[1] = {values.size()};
            H5::DataSpace space(1, dims);
            H5::StrType type(H5::PredType::C_S1, H5T_VARIABLE);
            H5::DataSet ds = prop_group.createDataSet(key, type, space);
            std::vector<const char*> c_strs;
            for (const auto& s : values) c_strs.push_back(s.c_str());
            ds.write(c_strs.data(), type);
            std::cout << "    - Saved property: " << key << std::endl;
        }
    }
}

void EventLogger::writeVenueLookupTable(H5::H5File& file, const WorldState& world, const Config& config) {
    size_t n = world.venues.size();

    // Convert venue data to record format
    std::vector<detail::VenueRecord> records(n + 1);

    // First, add the special infection_seed venue
    records[0].venue_id = INFECTION_SEED_VENUE_ID;
    strncpy(records[0].name, "infection_seed", 127);
    records[0].name[127] = '\0';
    strncpy(records[0].type, "infection_seed", 63);
    records[0].type[63] = '\0';
    records[0].geo_unit_id = -1;
    records[0].n_subsets = 0;

    // Convert venue data to record format
    for (size_t i = 0; i < n; ++i) {
        const Venue& venue = world.venues[i];
        records[i + 1].venue_id = venue.id;

        // Venue name
        strncpy(records[i + 1].name, venue.name.c_str(), 127);
        records[i + 1].name[127] = '\0';

        // Venue type
        strncpy(records[i + 1].type, venue.type.c_str(), 63);
        records[i + 1].type[63] = '\0';

        records[i + 1].geo_unit_id = venue.geo_unit_id;
        records[i + 1].n_subsets = static_cast<int>(venue.subsets.size());
    }

    // Create compound datatype
    H5::StrType name_type(H5::PredType::C_S1, 128);
    H5::StrType type_type(H5::PredType::C_S1, 64);
    H5::CompType venue_type(sizeof(detail::VenueRecord));
    venue_type.insertMember("venue_id", HOFFSET(detail::VenueRecord, venue_id),
                            H5::PredType::NATIVE_INT);
    venue_type.insertMember("name", HOFFSET(detail::VenueRecord, name),
                            name_type);
    venue_type.insertMember("type", HOFFSET(detail::VenueRecord, type),
                            type_type);
    venue_type.insertMember("geo_unit_id", HOFFSET(detail::VenueRecord, geo_unit_id),
                            H5::PredType::NATIVE_INT);
    venue_type.insertMember("n_subsets", HOFFSET(detail::VenueRecord, n_subsets),
                            H5::PredType::NATIVE_INT);

    // Create dataspace (n venues + 1 for infection_seed)
    hsize_t dims[1] = {n + 1};
    H5::DataSpace dataspace(1, dims);

    // Create and write dataset
    H5::DataSet dataset = file.createDataSet("/lookups/venues",
                                              venue_type, dataspace);
    dataset.write(records.data(), venue_type);

    std::cout << "  Wrote venue lookup table: " << (n + 1) << " venues (including infection_seed)" << std::endl;
}

void EventLogger::writePersonActivitiesTable(H5::H5File& file, const WorldState& world, const Config& config) {
    // Determine which people's activities to save based on config
    std::unordered_set<PersonId> people_to_save;

    if (config.simulation.save_person_activities == "all") {
        // Save everyone's activities
        for (const auto& person : world.people) {
            people_to_save.insert(person.id);
        }
    } else if (config.simulation.save_person_activities == "infected_only") {
        // Save only infected people's activities
        people_to_save = getInfectedPersonIds();
    } else {
        // "none" - don't save anything
        std::cout << "  Skipping person activities (mode: none)" << std::endl;
        return;
    }

    // Count total number of person-activity-venue combinations for selected people
    size_t total_entries = 0;
    for (const auto& person : world.people) {
        if (!people_to_save.count(person.id)) {
            continue;
        }
        for (const auto& entry : person.activities) {
            total_entries += entry.second.size();
        }
    }

    if (total_entries == 0) {
        std::cout << "  No person activities to write" << std::endl;
        return;
    }

    std::cout << "  Writing person activities (" << config.simulation.save_person_activities
              << " mode: " << people_to_save.size() << " people, "
              << total_entries << " activities)..." << std::endl;

    // Flatten the activity map into a table (only for selected people)
    std::vector<detail::PersonActivityRecord> records;
    records.reserve(total_entries);

    for (const auto& person : world.people) {
        if (!people_to_save.count(person.id)) {
            continue;  // Skip this person
        }
        for (const auto& entry : person.activities) {
            int16_t act_idx = entry.first;
            const auto& venues = entry.second;
            
            if (act_idx < 0 || act_idx >= (int16_t)Person::activity_names.size()) continue;
            
            const std::string& activity_name = Person::activity_names[act_idx];
            
            for (size_t idx = 0; idx < venues.size(); ++idx) {
                detail::PersonActivityRecord record;
                record.person_id = person.id;

                // Copy activity name
                strncpy(record.activity_name, activity_name.c_str(), 63);
                record.activity_name[63] = '\0';

                record.venue_id = venues[idx].first;
                record.subset_index = venues[idx].second;
                record.activity_index = static_cast<int>(idx);

                records.push_back(record);
            }
        }
    }

    // Create compound datatype
    H5::StrType activity_name_type(H5::PredType::C_S1, 64);
    H5::CompType activity_type(sizeof(detail::PersonActivityRecord));
    activity_type.insertMember("person_id", HOFFSET(detail::PersonActivityRecord, person_id),
                               H5::PredType::NATIVE_INT);
    activity_type.insertMember("activity_name", HOFFSET(detail::PersonActivityRecord, activity_name),
                               activity_name_type);
    activity_type.insertMember("venue_id", HOFFSET(detail::PersonActivityRecord, venue_id),
                               H5::PredType::NATIVE_INT);
    activity_type.insertMember("subset_index", HOFFSET(detail::PersonActivityRecord, subset_index),
                               H5::PredType::NATIVE_INT);
    activity_type.insertMember("activity_index", HOFFSET(detail::PersonActivityRecord, activity_index),
                               H5::PredType::NATIVE_INT);

    // Create dataspace
    hsize_t dims[1] = {records.size()};
    H5::DataSpace dataspace(1, dims);

    // Create and write dataset
    H5::DataSet dataset = file.createDataSet("/lookups/person_activities",
                                              activity_type, dataspace);
    dataset.write(records.data(), activity_type);

    std::cout << "  Wrote person-activities table: " << records.size() << " mappings" << std::endl;
}

// =============================================================================
// New Helper Methods for Selective Saving and Compression
// =============================================================================

std::unordered_set<PersonId> EventLogger::getInfectedPersonIds() const {
    std::unordered_set<PersonId> infected_ids;

    // Collect all unique person IDs from infection events
    for (const auto& event : infections_) {
        infected_ids.insert(event.person_id);
    }

    return infected_ids;
}

H5::DataSet EventLogger::createCompressedDataset(H5::H5File& file, const std::string& name,
                                                  const H5::DataType& datatype,
                                                  const H5::DataSpace& dataspace,
                                                  int compression_level) {
    if (compression_level <= 0) {
        // No compression
        return file.createDataSet(name, datatype, dataspace);
    }

    // Get dimensions for chunking
    hsize_t dims[1];
    dataspace.getSimpleExtentDims(dims);

    // Set chunk size (use full dataset size if small, otherwise chunk to ~1MB)
    hsize_t chunk_dims[1];
    chunk_dims[0] = std::min(dims[0], hsize_t(100000)); // Reasonable chunk size

    // Create dataset creation property list for compression
    H5::DSetCreatPropList plist;
    plist.setChunk(1, chunk_dims);
    plist.setDeflate(compression_level); // gzip compression

    return file.createDataSet(name, datatype, dataspace, plist);
}

void EventLogger::writePopulationSummary(H5::H5File& file, const WorldState& world, const Config& config) {
    size_t n = world.people.size();
    if (n == 0) return;

    std::cout << "  Writing population summary (" << n << " people, minimal data)..." << std::endl;

    // String-to-code mappings for compression
    std::unordered_map<std::string, uint8_t> sex_codes = {{"male", 0}, {"female", 1}, {"other", 2}};
    std::unordered_map<std::string, uint8_t> schedule_codes;
    std::unordered_map<std::string, uint8_t> ethnicity_codes;
    std::unordered_map<std::string, uint8_t> work_mode_codes;

    // Auto-assign codes for categorical variables
    uint8_t next_schedule_code = 0;
    uint8_t next_ethnicity_code = 0;
    uint8_t next_work_mode_code = 0;

    // Convert data to minimal format
    std::vector<PopulationSummaryRecord> records(n);
    for (size_t i = 0; i < n; ++i) {
        const Person& person = world.people[i];
        records[i].person_id = person.id;

        // Age group (5-year bins: 0-4, 5-9, ..., 85+)
        records[i].age_group = std::min(static_cast<uint8_t>(person.age / 5), uint8_t(17));

        // Sex code
        records[i].sex_code = sex_codes.count(person.sex) ? sex_codes[person.sex] : 2;

        records[i].geo_unit_id = person.geo_unit_id;

        // Ethnicity code (auto-assign)
        std::string ethnicity = "unknown";
        auto eth_prop = person.getProperty("ethnicity");
        if (eth_prop.has_value()) {
            if (std::holds_alternative<std::string>(*eth_prop)) {
                ethnicity = std::get<std::string>(*eth_prop);
            }
        }
        if (!ethnicity_codes.count(ethnicity)) {
            ethnicity_codes[ethnicity] = next_ethnicity_code++;
        }
        records[i].ethnicity_code = ethnicity_codes[ethnicity];

        // Schedule type code
        std::string sched = person.schedule_type.empty() ? "unknown" : person.schedule_type;
        if (!schedule_codes.count(sched)) {
            schedule_codes[sched] = next_schedule_code++;
        }
        records[i].schedule_type_code = schedule_codes[sched];

        // Comorbidities
        records[i].has_comorbidities = 0;
        auto comorbid_prop = person.getProperty("has_comorbidities");
        if (comorbid_prop.has_value()) {
            const auto& prop = *comorbid_prop;
            if (std::holds_alternative<bool>(prop)) {
                records[i].has_comorbidities = std::get<bool>(prop) ? 1 : 0;
            } else if (std::holds_alternative<int32_t>(prop)) {
                records[i].has_comorbidities = std::get<int32_t>(prop) > 0 ? 1 : 0;
            }
        }

        // Work mode code
        std::string work_mode = "unknown";
        auto work_prop = person.getProperty("work_mode");
        if (work_prop.has_value()) {
            const auto& prop = *work_prop;
            if (std::holds_alternative<std::string>(prop)) {
                work_mode = std::get<std::string>(prop);
            }
        }
        if (!work_mode_codes.count(work_mode)) {
            work_mode_codes[work_mode] = next_work_mode_code++;
        }
        records[i].work_mode_code = work_mode_codes[work_mode];
    }

    // Create compound datatype
    H5::CompType pop_type(sizeof(PopulationSummaryRecord));
    pop_type.insertMember("person_id", HOFFSET(PopulationSummaryRecord, person_id),
                          H5::PredType::NATIVE_INT);
    pop_type.insertMember("age_group", HOFFSET(PopulationSummaryRecord, age_group),
                          H5::PredType::NATIVE_UINT8);
    pop_type.insertMember("sex_code", HOFFSET(PopulationSummaryRecord, sex_code),
                          H5::PredType::NATIVE_UINT8);
    pop_type.insertMember("geo_unit_id", HOFFSET(PopulationSummaryRecord, geo_unit_id),
                          H5::PredType::NATIVE_INT);
    pop_type.insertMember("ethnicity_code", HOFFSET(PopulationSummaryRecord, ethnicity_code),
                          H5::PredType::NATIVE_UINT8);
    pop_type.insertMember("schedule_type_code", HOFFSET(PopulationSummaryRecord, schedule_type_code),
                          H5::PredType::NATIVE_UINT8);
    pop_type.insertMember("has_comorbidities", HOFFSET(PopulationSummaryRecord, has_comorbidities),
                          H5::PredType::NATIVE_UINT8);
    pop_type.insertMember("work_mode_code", HOFFSET(PopulationSummaryRecord, work_mode_code),
                          H5::PredType::NATIVE_UINT8);

    // Create dataspace
    hsize_t dims[1] = {n};
    H5::DataSpace dataspace(1, dims);

    // Create and write dataset with compression
    H5::DataSet dataset = createCompressedDataset(file, "/lookups/population_summary",
                                                   pop_type, dataspace,
                                                   config.simulation.compression_level);
    dataset.write(records.data(), pop_type);

    // Save code mappings as attributes for reference
    // TODO: Save mappings if needed for decoding

    std::cout << "  Wrote population summary: " << n << " people ("
              << (n * sizeof(PopulationSummaryRecord)) / (1024.0 * 1024.0)
              << " MB uncompressed, ~"
              << (n * sizeof(PopulationSummaryRecord)) / (1024.0 * 1024.0 * 10.0)
              << " MB compressed)" << std::endl;
}

} // namespace june
