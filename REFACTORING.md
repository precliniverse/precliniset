# 🏗️ MASTER REFACTORING PLAN : PRECLINISET V2 (GLP-READY)

## 🎯 Objectif
Migrer l'application d'une architecture monolithique centrée sur le JSON vers une architecture en couches (Layered Architecture), utilisant un modèle de données Hybride (SQL + JSON), une validation stricte (Pydantic) et une sécurité renforcée.

## ⚠️ Consignes Générales pour l'Agent IA
1.  **Ne jamais supprimer de code** sans avoir créé son remplaçant testé.
2.  **Principe d'Isolation :** Chaque tâche doit être commitable individuellement.
3.  **Type Hinting :** Tout nouveau code doit être strictement typé (Python 3.11+).
4.  **Documentation :** Chaque classe/méthode publique doit avoir une docstring Google Style.

---

## 📅 PHASE 1 : FONDATIONS & VALIDATION (Pydantic)

Cette phase ne casse pas l'existant. Elle met en place les structures de données.

### Tâche 1.1 : Création de la structure d'Exceptions
*   **Fichier cible :** `app/exceptions.py`
*   **Prompt pour l'Agent :**
    > "Crée un fichier d'exceptions personnalisées. Je veux une classe de base `PreclinisetError`. Crée des sous-classes : `ValidationError` (pour les erreurs de données), `BusinessError` (pour les règles métier non respectées), `ResourceNotFoundError` (pour les 404) et `SecurityError` (pour les permissions). Chaque exception doit pouvoir porter un message et un code d'erreur optionnel."

### Tâche 1.2 : Mise en place des Schémas (Pydantic)
*   **Fichier cible :** `app/schemas/animal.py`, `app/schemas/group.py`
*   **Prompt pour l'Agent :**
    > "Installe Pydantic si nécessaire. Crée un schéma `AnimalSchema` qui valide les données suivantes :
    > - `ID` (string, obligatoire)
    > - `Date of Birth` (date, obligatoire, alias='Date of Birth')
    > - `sex` (string, optionnel). **Important :** Ne pas utiliser de `Literal` ou d'`Enum` ici. Ce champ doit accepter n'importe quelle chaîne pour l'instant, car la validation des valeurs autorisées se fera dynamiquement plus tard via la configuration en base de données.
    > - `measurements` (Dict[str, Any], optionnel, pour les données scientifiques dynamiques).
    > Crée ensuite un `GroupCreateSchema` qui contient un nom, un `protocol_id` et une liste d'`AnimalSchema`."

---

## 📅 PHASE 2 : MIGRATION DU MODÈLE DE DONNÉES (Le Cœur)

Passage du "Tout JSON" au modèle Hybride.

### Tâche 2.1 : Création du Modèle SQL `Animal`
*   **Fichier cible :** `app/models/animal.py` (nouveau fichier)
*   **Prompt pour l'Agent :**
    > "Crée un modèle SQLAlchemy `Animal`.
    > - Colonnes : `id` (PK), `uid` (string unique), `group_id` (FK).
    > - Colonne `sex` : Utilise `db.String(50)` (VARCHAR). **Surtout pas de `db.Enum`**, car les valeurs possibles sont définies par l'utilisateur (ex: Male, Female, M, F, Unknown).
    > - Colonne `status` : Utilise `db.String(20)` avec index (ex: 'alive', 'dead').
    > - Colonne Hybride : `measurements` (JSON) pour le reste.
    > - Ajoute les index SQL sur `uid`, `group_id` et `status`.
    > - Ajoute la relation vers `ExperimentalGroup`."

### Tâche 2.2 : Génération de la Migration Alembic
*   **Action :** Terminal / Ligne de commande
*   **Commande :** `flask db migrate -m "Add Animal hybrid table"`
*   **Prompt pour l'Agent :**
    > "Vérifie le script de migration généré dans `migrations/versions`. Assure-toi que la table `animal` est bien créée avec le bon type JSON pour la colonne `measurements` (JSONB si Postgres, JSON si MySQL/MariaDB)."

### Tâche 2.3 : Script de Migration de Données (Data Migration)
*   **Critique :** Il faut extraire les données du JSON `ExperimentalGroup.animal_data` vers la nouvelle table `Animal`.
*   **Fichier cible :** `scripts/migrate_animals_json_to_sql.py`
*   **Prompt pour l'Agent :**
    > "Écris un script Python standalone (avec le contexte de l'application Flask) qui :
    > 1. Itère sur tous les `ExperimentalGroup`.
    > 2. Pour chaque groupe, lit la colonne `animal_data` (le tableau JSON).
    > 3. Pour chaque animal dans ce tableau, crée une entrée dans la nouvelle table `Animal`.
    > 4. Mappe les champs fixes (ID, Date of Birth, Sex) vers les colonnes SQL.
    > 5. Déplace TOUS les autres champs (Poids, Tumeur, etc.) dans la colonne `measurements`.
    > 6. Commit par paquets de 100 pour la performance."

### Tâche 2.4 : Compatibilité Frontend**
    > Dans le fichier `app/models/experiments.py`, modifie la classe `ExperimentalGroup`.
    > Ajoute une `@property` nommée `animal_data`.
    > Cette propriété doit :
    > 1. Interroger la relation `self.animals` (la nouvelle table SQL).
    > 2. Reconstruire dynamiquement la liste de dictionnaires (JSON) que le frontend attend.
    > 3. Fusionner les champs SQL (`id`, `sex`, `dob`) et le contenu de `measurements`.
---

## 📅 PHASE 3 : REFACTORING DE LA LOGIQUE MÉTIER (Service Layer)

On déplace la logique des routes vers des Services purs.

### Tâche 3.1 : Refactoring de `GroupService`
*   **Fichier cible :** `app/services/group_service.py`
*   **Prompt pour l'Agent :**
    > "Réécris la classe `GroupService`.
    > La méthode `create_group` doit :
    > 1. Charger la définition de l'Analyte 'Sex' depuis la base de données (table `Analyte`) pour récupérer les `allowed_values` configurées par l'utilisateur.
    > 2. Valider que le champ `sex` reçu dans le `GroupCreateSchema` correspond bien à l'une de ces valeurs (si des valeurs sont définies).
    > 3. Créer les entités `Animal`.
    > 4. Stocker les données dynamiques dans le JSON `measurements` après validation dynamique."


### Tâche 3.2 : Mise à jour de `AnalysisService` (Pandas)
*   **Fichier cible :** `app/services/analysis_service.py`
*   **Prompt pour l'Agent :**
    > "Modifie la méthode `prepare_dataframe`.
    > Au lieu de parser un JSON imbriqué, elle doit :
    > 1. Faire une requête SQL performante pour récupérer les animaux d'un groupe (`id`, `sex`, `measurements`).
    > 2. Charger ces données dans un DataFrame Pandas.
    > 3. Utiliser `pd.json_normalize` sur la colonne `measurements` pour aplatir les données scientifiques dynamiques.
    > 4. Fusionner les colonnes SQL et les colonnes dynamiques.
    > Le résultat final (le DataFrame) doit être identique à avant pour ne pas casser les graphiques."

---

## 📅 PHASE 4 : NETTOYAGE DES ROUTES (Controller Layer)

Les routes deviennent minimalistes.

### Tâche 4.1 : Nettoyage de `app/groups/routes.py`
*   **Prompt pour l'Agent :**
    > "Refactorise la route `/groups/create`.
    > 1. Supprime toute la logique métier et validation manuelle.
    > 2. Instancie le schéma Pydantic `GroupCreateSchema` avec `request.get_json()`.
    > 3. Appelle `GroupService.create_group`.
    > 4. Gère les exceptions (`ValidationError` -> 400, `BusinessError` -> 409).
    > 5. Retourne une réponse JSON propre."

### Tâche 4.2 : Nettoyage de `app/datatables/routes.py`
*   **Prompt pour l'Agent :**
    > "Même processus pour la création de DataTables. Utilise un `DataTableService` (à créer ou mettre à jour) pour gérer l'enregistrement des mesures. Assure-toi que les nouvelles mesures mettent à jour la colonne JSON `measurements` de la table `Animal` correspondante."

---

## 📅 PHASE 5 : SÉCURITÉ & API

### Tâche 5.1 : Durcissement de l'Authentification API
*   **Fichier cible :** `app/api/auth.py`
*   **Prompt pour l'Agent :**
    > "Modifie le décorateur `@token_required`.
    > Il doit refuser strictement l'authentification par session (Cookie) si le Header `Authorization: Bearer ...` est absent.
    > Pour les appels AJAX depuis le frontend, crée un décorateur séparé `@session_or_token_required` qui EXIGE la validation CSRF si c'est une session cookie."

### Tâche 5.2 : Validation des Entrées (Input Sanitization)
*   **Prompt pour l'Agent :**
    > "Dans les schémas Pydantic créés en Phase 1, ajoute des validateurs pour les champs texte libre (notes, descriptions) afin d'échapper les caractères HTML/Script potentiels (prévention XSS stockée)."

---

## 📅 PHASE 6 : VÉRIFICATION

### Tâche 6.1 : Tests Unitaires
*   **Prompt pour l'Agent :**
    > "Crée un test unitaire pour `GroupService`.
    > - Teste la création d'un groupe avec des données valides (vérifie que les lignes sont dans la table `animal`).
    > - Teste le rejet de données invalides via Pydantic.
    > - Teste la performance : insère 1000 animaux et mesure le temps d'exécution comparé à l'ancienne méthode JSON (si possible)."
