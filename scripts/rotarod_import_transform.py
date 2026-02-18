"""
scripts/rotarod_import_transform.py
=====================================
Transforme la sortie brute d'un appareil Rotarod (format long multi-essais)
en format Precliniset-compatible pour le pipeline d'import.

Format d'entrée (test_data_rotarod.csv) :
    Animal_ID, Group, Sex, Genotype, Body_Weight_g,
    Day, Trial, Latency_to_fall_s, Speed_rpm, Rotation_direction

Format de sortie (rotarod_precliniset_import.csv) :
    uid (Animal_ID), Group, Sex, Genotype, Body_Weight_g,
    Latency_J1_T1, Latency_J1_T2, Latency_J1_T3,
    Latency_J3_T1, ..., Latency_J21_T3,
    Speed_J1_T1, ..., Speed_J21_T3,
    Mean_Latency_J1, ..., Mean_Latency_J21,
    Best_Latency_J1, ..., Best_Latency_J21

Stratégie de mapping vers Precliniset :
    - uid          → colonne identifiant animal (Animal_ID)
    - Group        → facteur de regroupement (grouping analyte)
    - Sex          → métadonnée animal
    - Genotype     → métadonnée animal
    - Body_Weight_g → analyte numérique (mesure unique)
    - Latency_Jx_Ty → analytes numériques (mesures répétées par jour/essai)
    - Mean_Latency_Jx → analytes calculés (moyenne des essais par jour)
    - Best_Latency_Jx → analytes calculés (meilleur essai par jour)

Usage :
    python scripts/rotarod_import_transform.py [input_csv] [output_csv]

    Par défaut :
        input  = scripts/test_data_rotarod.csv
        output = scripts/rotarod_precliniset_import.csv
"""

import csv
import sys
import os
from collections import defaultdict


def transform_rotarod(input_path: str, output_path: str) -> None:
    """
    Transforme le CSV rotarod brut en format Precliniset.
    """
    # ── Lecture des données brutes ─────────────────────────────────────────
    raw_data = defaultdict(lambda: defaultdict(dict))  # animal → day → trial → values
    animal_meta = {}  # animal → {Group, Sex, Genotype, Body_Weight_g}
    days_seen = set()
    trials_seen = set()

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            animal_id = row["Animal_ID"]
            day = int(row["Day"])
            trial = int(row["Trial"])

            days_seen.add(day)
            trials_seen.add(trial)

            # Métadonnées animal (une seule fois)
            if animal_id not in animal_meta:
                animal_meta[animal_id] = {
                    "Group": row["Group"],
                    "Sex": row["Sex"],
                    "Genotype": row["Genotype"],
                    "Body_Weight_g": row["Body_Weight_g"],
                }

            raw_data[animal_id][day][trial] = {
                "latency": float(row["Latency_to_fall_s"]),
                "speed": float(row["Speed_rpm"]),
                "direction": row["Rotation_direction"],
            }

    days = sorted(days_seen)
    trials = sorted(trials_seen)

    # ── Construction des colonnes de sortie ────────────────────────────────
    # Colonnes de base
    base_cols = ["uid", "Group", "Sex", "Genotype", "Body_Weight_g"]

    # Colonnes par essai
    latency_trial_cols = [f"Latency_J{d}_T{t}" for d in days for t in trials]
    speed_trial_cols = [f"Speed_J{d}_T{t}" for d in days for t in trials]
    direction_trial_cols = [f"Direction_J{d}_T{t}" for d in days for t in trials]

    # Colonnes calculées (moyenne et meilleur essai par jour)
    mean_latency_cols = [f"Mean_Latency_J{d}" for d in days]
    best_latency_cols = [f"Best_Latency_J{d}" for d in days]
    mean_speed_cols = [f"Mean_Speed_J{d}" for d in days]

    all_cols = (
        base_cols
        + latency_trial_cols
        + speed_trial_cols
        + direction_trial_cols
        + mean_latency_cols
        + best_latency_cols
        + mean_speed_cols
    )

    # ── Transformation wide ────────────────────────────────────────────────
    output_rows = []

    for animal_id in sorted(animal_meta.keys()):
        meta = animal_meta[animal_id]
        row_out = {
            "uid": animal_id,
            "Group": meta["Group"],
            "Sex": meta["Sex"],
            "Genotype": meta["Genotype"],
            "Body_Weight_g": meta["Body_Weight_g"],
        }

        for day in days:
            day_latencies = []
            day_speeds = []

            for trial in trials:
                col_lat = f"Latency_J{day}_T{trial}"
                col_spd = f"Speed_J{day}_T{trial}"
                col_dir = f"Direction_J{day}_T{trial}"

                trial_data = raw_data[animal_id].get(day, {}).get(trial)
                if trial_data:
                    row_out[col_lat] = round(trial_data["latency"], 1)
                    row_out[col_spd] = round(trial_data["speed"], 1)
                    row_out[col_dir] = trial_data["direction"]
                    day_latencies.append(trial_data["latency"])
                    day_speeds.append(trial_data["speed"])
                else:
                    row_out[col_lat] = ""
                    row_out[col_spd] = ""
                    row_out[col_dir] = ""

            # Calculs agrégés par jour
            if day_latencies:
                row_out[f"Mean_Latency_J{day}"] = round(
                    sum(day_latencies) / len(day_latencies), 2
                )
                row_out[f"Best_Latency_J{day}"] = round(max(day_latencies), 1)
                row_out[f"Mean_Speed_J{day}"] = round(
                    sum(day_speeds) / len(day_speeds), 2
                )
            else:
                row_out[f"Mean_Latency_J{day}"] = ""
                row_out[f"Best_Latency_J{day}"] = ""
                row_out[f"Mean_Speed_J{day}"] = ""

        output_rows.append(row_out)

    # ── Écriture du CSV de sortie ──────────────────────────────────────────
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"✅ Transformation terminée : {output_path}")
    print(f"   {len(output_rows)} animaux × {len(all_cols)} colonnes")
    print()
    print("── Mapping Precliniset suggéré ──────────────────────────────────")
    print("  uid              → Identifiant animal (colonne uid)")
    print("  Group            → Analyte de type 'grouping' (catégoriel)")
    print("  Sex              → Métadonnée animal (catégoriel)")
    print("  Genotype         → Métadonnée animal (catégoriel)")
    print("  Body_Weight_g    → Analyte numérique (poids corporel)")
    print("  Latency_Jx_Ty   → Analytes numériques (latence par essai)")
    print("  Speed_Jx_Ty     → Analytes numériques (vitesse par essai)")
    print("  Direction_Jx_Ty → Analytes catégoriels (direction rotation)")
    print("  Mean_Latency_Jx → Analytes calculés (moyenne latence/jour)")
    print("  Best_Latency_Jx → Analytes calculés (meilleur essai/jour)")
    print("  Mean_Speed_Jx   → Analytes calculés (moyenne vitesse/jour)")
    print()
    print("── Pour l'analyse des mesures répétées ─────────────────────────")
    print("  Paramètres à analyser : Mean_Latency_J1 ... Mean_Latency_J21")
    print("  Facteur de regroupement : Group")
    print("  Identifiant sujet : uid")
    print("  → Test suggéré : Mixed ANOVA (between=Group, within=Day)")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    input_csv = sys.argv[1] if len(sys.argv) > 1 else os.path.join(script_dir, "test_data_rotarod.csv")
    output_csv = sys.argv[2] if len(sys.argv) > 2 else os.path.join(script_dir, "rotarod_precliniset_import.csv")

    if not os.path.exists(input_csv):
        print(f"❌ Fichier d'entrée introuvable : {input_csv}")
        print("   Générez-le d'abord avec : python scripts/generate_rotarod_test_data.py")
        sys.exit(1)

    transform_rotarod(input_csv, output_csv)
