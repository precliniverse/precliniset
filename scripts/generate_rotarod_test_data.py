"""
scripts/generate_rotarod_test_data.py
======================================
Génère un fichier CSV simulant la sortie brute d'un appareil Rotarod
(format wide, plusieurs essais par animal par jour).

Usage :
    python scripts/generate_rotarod_test_data.py

Sortie :
    scripts/test_data_rotarod.csv
"""

import csv
import random
import os

random.seed(42)

# ── Paramètres de l'expérience ─────────────────────────────────────────────
GROUPS = {
    "Control":   {"n": 8, "base_latency": 180, "improvement": 5,  "variability": 20},
    "Treatment": {"n": 8, "base_latency": 160, "improvement": 15, "variability": 18},
    "Sham":      {"n": 6, "base_latency": 175, "improvement": 3,  "variability": 22},
}
DAYS = [1, 3, 7, 14, 21]
TRIALS_PER_DAY = 3
MAX_SPEED_RPM = 40
ROTATION_DIRECTIONS = ["CW", "CCW"]  # Clockwise / Counter-clockwise

# ── Génération des données ─────────────────────────────────────────────────
rows = []
animal_counter = 1

for group_name, params in GROUPS.items():
    for i in range(params["n"]):
        animal_id = f"RAT_{animal_counter:03d}"
        sex = "M" if i % 2 == 0 else "F"
        genotype = "WT" if i < params["n"] // 2 else "KO"
        weight_g = round(random.gauss(280 if sex == "M" else 230, 15), 1)

        for day in DAYS:
            # Amélioration progressive selon le groupe
            day_factor = (DAYS.index(day)) * params["improvement"]

            for trial in range(1, TRIALS_PER_DAY + 1):
                # Latence à la chute (secondes) — max 300s
                latency = min(
                    300,
                    max(
                        5,
                        round(
                            params["base_latency"]
                            + day_factor
                            + random.gauss(0, params["variability"]),
                            1,
                        ),
                    ),
                )
                # Vitesse au moment de la chute (rpm)
                speed = round(random.uniform(4, MAX_SPEED_RPM), 1)
                # Direction de rotation
                direction = ROTATION_DIRECTIONS[trial % 2]

                rows.append({
                    "Animal_ID": animal_id,
                    "Group": group_name,
                    "Sex": sex,
                    "Genotype": genotype,
                    "Body_Weight_g": weight_g,
                    "Day": day,
                    "Trial": trial,
                    "Latency_to_fall_s": latency,
                    "Speed_rpm": speed,
                    "Rotation_direction": direction,
                })

        animal_counter += 1

# ── Écriture du CSV ────────────────────────────────────────────────────────
output_path = os.path.join(os.path.dirname(__file__), "test_data_rotarod.csv")
fieldnames = [
    "Animal_ID", "Group", "Sex", "Genotype", "Body_Weight_g",
    "Day", "Trial", "Latency_to_fall_s", "Speed_rpm", "Rotation_direction",
]

with open(output_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"✅ Fichier généré : {output_path}")
print(f"   {len(rows)} lignes ({sum(p['n'] for p in GROUPS.values())} animaux × {len(DAYS)} jours × {TRIALS_PER_DAY} essais)")
