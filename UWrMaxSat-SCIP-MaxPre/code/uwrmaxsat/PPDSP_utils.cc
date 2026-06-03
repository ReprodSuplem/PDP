#include "PPDSP_utils.h"
#include <algorithm>
#include <iostream>
#include <cassert>
#include <fstream>
using namespace std;

double PPDSP_start_time = 0;
int    PPDSP_time_limit = -1;

void PPDSP_utils::buildVarIndexMap(PPDSP_Instance* inst)
{
    inst->id2Var.clear();
    // xVars
    for (int t=0; t < inst->lenOfVehicle; t++){
        for (size_t o=0; o < inst->xVarList[t].size(); o++){
            for (size_t d=0; d < inst->xVarList[t][o].size(); d++){
                int vid = inst->xVarList[t][o][d];
                inst->id2Var[vid] = VarInfo('x', t, o, d);
            }
        }
    }
    // yVars
    for (int r=0; r < inst->lenOfRequest; r++){
        for (int t=0; t < inst->lenOfVehicle; t++){
            int vid = inst->yVarList[r][t];
            inst->id2Var[vid] = VarInfo('y', r, t, -1);
        }
    }
}

void PPDSP_utils::extractXYModel(
    PPDSP_Instance* inst,
    const std::vector<int>& fullModel,
    std::vector<int>& xyModel
){
    xyModel.clear();
    int maxY = inst->getLastYVarID();
    for (int lit : fullModel){
        if (lit > 0 && lit <= maxY)
            xyModel.push_back(lit);
    }
}

void PPDSP_utils::decodeModel(
    PPDSP_Instance* inst,
    const std::vector<int>& xyModel,
    std::vector<std::vector<std::pair<int,int>>>& vehRoutes,
    std::vector<std::vector<int>>& vehReqs
){
    vehRoutes.assign(inst->lenOfVehicle, {});
    vehReqs.assign(inst->lenOfVehicle, {});

    if (inst->id2Var.empty())
        buildVarIndexMap(inst);

    // collect edges & reqs
    for (int vid : xyModel){
        std::unordered_map<int,VarInfo>::const_iterator it = inst->id2Var.find(vid);
        if (it == inst->id2Var.end()) continue;

        const VarInfo &info = it->second;

        if (info.type == 'x'){
            int t = info.a;
            int o = info.b;
            int d = info.c;
            if (o != d)
                vehRoutes[t].push_back(std::make_pair(o,d));
        }
        else if (info.type == 'y'){
            int r = info.a;
            int t = info.b;
            vehReqs[t].push_back(r);
        }
    }

    // reconstruct Hamiltonian path starting from depot = lenOfLocation
    int depot = inst->lenOfLocation;
    for (int t=0; t<inst->lenOfVehicle; t++){
        std::vector<std::pair<int,int> > &edges = vehRoutes[t];
        if (edges.empty()) continue;

        std::unordered_map<int,int> nxt;
        for (size_t i = 0; i < edges.size(); i++)
            nxt[edges[i].first] = edges[i].second;

        std::vector<std::pair<int,int> > route;
        int cur = depot;
        while (nxt.count(cur)){
            int d = nxt[cur];
            route.push_back(std::make_pair(cur, d));
            cur = d;
            if (cur == depot) break;
        }
        vehRoutes[t] = route;
    }
}

bool PPDSP_utils::checkOverload(
    PPDSP_Instance* inst,
    int vehID,
    const std::vector<std::pair<int,int>>& route,
    const std::vector<int>& assigned_reqs,
    std::vector<std::vector<Minisat::Lit>>& learnt_clauses,
    bool enable_broadcast
){
    if (route.empty()) return false;

    int capacity = inst->vehicleList[vehID][0];
    int load = 0;

    vector<int> req_size(inst->lenOfRequest);
    vector<int> pickup(inst->lenOfRequest);
    vector<int> drop(inst->lenOfRequest);

    for (int r = 0; r < inst->lenOfRequest; r++){
        req_size[r] = inst->requestList[r][1];
        pickup[r]   = inst->requestList[r][2];
        drop[r]     = inst->requestList[r][3];
    }

    vector<bool> onboard(inst->lenOfRequest, false);

    // Iterate route in order
    for (size_t k = 0; k < route.size(); k++){
        int d = route[k].second;

        // Update onboard
        for (int r : assigned_reqs){
            // Ignore instant pickup-dropoff at the same location to prevent false overload detection
            if (d == pickup[r] && d == drop[r]) {
                continue;
            }
            else if (d == pickup[r]){
                load += req_size[r];
                onboard[r] = true;
            }
            else if (d == drop[r] && onboard[r]){
                load -= req_size[r];
                onboard[r] = false;
            }
        }

        // ---- Overload found ----
        if (load > capacity){
            learnt_clauses.clear();

            // 1. Collect onboard requests
            vector<int> onboard_reqs;
            for (int r : assigned_reqs)
                if (onboard[r])
                    onboard_reqs.push_back(r);

            // 2. Greedy reduction: find minimal conflict core -- sort by size descending --
            std::sort(onboard_reqs.begin(), onboard_reqs.end(),
                [&](int a, int b){
                    return req_size[a] > req_size[b];
                }
            );

            // 3. Build minimal conflict set
            vector<int> minimal_conflict;
            int current_subset_load = 0;
            for (int r : onboard_reqs) {
                current_subset_load += req_size[r];
                minimal_conflict.push_back(r);
                if (current_subset_load > capacity) {
                    break;
                }
            }

            // 4. Prefix nodes (before or at this step)
            vector<int> prefix_origins;
            for (size_t i = 0; i <= k; i++){
                prefix_origins.push_back(route[i].first);
            }

            // 5. Build learnt clause (broadcasting)
            const auto& group = inst->identicalVehicles[vehID];
            const std::vector<int>* target_vehicles = nullptr;
            std::vector<int> single_vehicle_group;

            if (enable_broadcast) {
                target_vehicles = &group;
            } else {
                single_vehicle_group.push_back(vehID);
                target_vehicles = &single_vehicle_group;
            }

            // Broadcast the generated constraint across the defined target vehicles
            for (int targetID : *target_vehicles) {
                std::vector<Minisat::Lit> clause;
                // yLits (negated y-vars) for minimal conflict requests
                for (int r : minimal_conflict){
                    int vid = inst->yVarList[r][targetID];
                    if(vid!=0) clause.push_back(~Minisat::mkLit(vid - 1));
                }
                // xLits (only prefix origins → dropNode)
                for (int r : minimal_conflict){
                    int dropNode = drop[r];
                    for (int o : prefix_origins){
                        int vid = inst->xVarList[targetID][o][dropNode];
                        if(vid!=0) clause.push_back(Minisat::mkLit(vid - 1));
                    }
                }
                learnt_clauses.push_back(std::move(clause));
            }
            return true;
        }
    }
    return false;
}

bool loadPPDSPInstance(const char* filename, PPDSP_Instance& inst)
{
    std::ifstream in(filename);
    if (!in.good()) {
        std::cerr << "[UWrMaxSAT] Cannot open meta file: " << filename << std::endl;
        return false;
    }

    // Read header: lenOfVehicle lenOfRequest lenOfLocation
    in >> inst.lenOfVehicle >> inst.lenOfRequest >> inst.lenOfLocation;

    // Allocate
    inst.xVarList.assign(inst.lenOfVehicle,
                         std::vector<std::vector<int>>(inst.lenOfLocation+1,
                                                       std::vector<int>(inst.lenOfLocation+1, 0)));
    inst.yVarList.assign(inst.lenOfRequest,
                         std::vector<int>(inst.lenOfVehicle, 0));
    inst.requestList.assign(inst.lenOfRequest,
                            std::vector<int>(4, 0));
    inst.vehicleList.assign(inst.lenOfVehicle,
                            std::vector<int>(2, 0));
    inst.identicalVehicles.assign(inst.lenOfVehicle, {});
    for(int i=0; i<inst.lenOfVehicle; ++i) inst.identicalVehicles[i].push_back(i);

    std::string tag;
    std::string section = "";

    while (in >> tag)
    {
        // Switch section
        if (tag == "#") {
            in >> section; // e.g. xVarList
            continue;
        }

        // Parse according to current section
        if (section == "xVarList") {
            int t = std::stoi(tag);
            int o, d, vid;
            in >> o >> d >> vid;
            inst.xVarList[t][o][d] = vid;
        }
        else if (section == "yVarList") {
            int r = std::stoi(tag);
            int t, vid;
            in >> t >> vid;
            inst.yVarList[r][t] = vid;
        }
        else if (section == "requestList") {
            int r = std::stoi(tag);
            int w, q, pk, dp;
            in >> w >> q >> pk >> dp;
            inst.requestList[r] = {w, q, pk, dp};
        }
        else if (section == "vehicleList") {
            int t = std::stoi(tag);
            double cap, cost;
            in >> cap >> cost;
            inst.vehicleList[t] = {(int)cap, (int)cost};
        }
        else if (section == "vehicleGroups") {
            // int gid = std::stoi(tag);
            int count;
            in >> count;
            std::vector<int> groupMembers;
            for(int k=0; k<count; ++k) {
                int vid;
                in >> vid;
                groupMembers.push_back(vid);
            }
            // Update the map for all members
            for(int vid : groupMembers) {
                inst.identicalVehicles[vid] = groupMembers;
            }
        }
    }

    return true;
}

bool loadAssumptionLits(const char* filename, Minisat::vec<Minisat::Lit>& out_assumps, int maxVarID)
{
    std::ifstream in(filename);
    if (!in.good()){
        std::cerr << "[UWrMaxSAT] Cannot open assumption file: " << filename << std::endl;
        return false;
    }
    
    std::string tok;
    while (in >> tok){
        // tok is like 12 or -45
        int lit = std::stoi(tok);
        int v = std::abs(lit);

        if (v < 1 || v > maxVarID){
            std::cerr << "[UWrMaxSAT] WARNING: assumption literal "
                      << lit << " out of range 1.." << maxVarID << std::endl;
            continue;
        }

        Minisat::Lit L = Minisat::mkLit(v-1, lit < 0);
        out_assumps.push(L);
    }

    std::cout << "[UWrMaxSAT] Loaded " << out_assumps.size()
              << " assumption literals from " << filename << std::endl;

    return true;
}

void PPDSP_setTimeLimit(int seconds) { PPDSP_time_limit = seconds; }

void PPDSP_startTimer() { PPDSP_start_time = std::clock(); }

bool PPDSP_timeout() {
    if (PPDSP_time_limit <= 0) return false;
    double elapsed = (std::clock() - PPDSP_start_time) / CLOCKS_PER_SEC;
    return elapsed >= PPDSP_time_limit;
}