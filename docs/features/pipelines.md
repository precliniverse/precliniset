# Import Pipelines

The **Import Pipeline** feature allows you to extend the capabilities of the Precliniverse Import Wizard by using custom Python scripts. This is essential for dealing with extremely complex, unstructured, or propriety file formats that cannot be handled by standard row-skipping or text-anchor logic.

[TOC]

## 1. Concept

An **Import Pipeline** is a small Python script stored within the system. It bridges the gap between a messy raw file and the structured data Precliniverse expects.

*   **Input**: The raw path to an uploaded file (Excel, CSV, txt, etc.).
*   **Processing**: Your custom Python logic (pandas, numpy, regex, etc.).
*   **Output**: A clean list of dictionaries (rows), where keys match your Protocol's Analyte names.

When a user selects a Pipeline during import, the system:

1.  **Executes** your script securely in a sandboxed environment.
2.  **Skips** the manual column mapping step (since your script handles it).
3.  **Validates** the output IDs directly against the database logic.

## 2. Managing Pipelines

Pipelines are associated with specific **Protocols**.

### Creating a Pipeline

1.  Go to **Admin > Static Lists > Import Pipelines** (or access via the Protocol details).
2.  Click **Create New Pipeline**.
3.  **Name**: Give it a descriptive name (e.g., *"BioTek Synergy H1 - Tumor Volume Format"*).
4.  **Protocol**: Select the protocol this pipeline belongs to.
5.  **Script**: Enter your Python code (see structure below).

### The Script Interface

Your script **must** define a `parse(file_path)` function.

```python
import pandas as pd
import numpy as np

def parse(file_path):
    """
    Args:
       file_path (str): The absolute path to the uploaded file.
    
    Returns:
       list[dict]: A list of dictionaries. 
                   Keys MUST match Analyte names exactly.
                   One key MUST be 'ID' (for Animal ID).
    """
    
    # Custom parsing logic here
    df = pd.read_excel(file_path)
    
    # ... transformation ...
    
    return df.to_dict(orient='records')
```

## 3. Concrete Example (Input -> Script -> Output)

### The Input (Raw File: `results_raw.csv`)

Imagine a file where the data is trapped between metadata and footer:

```text
Instrument: BioTek Synergy
Date: 2023-10-27
--------------------------
ID, Reading 1, Reading 2
A-101, 0.450, 0.460
A-102, 0.890, 0.910
--------------------------
End of Report
```

### The Script

```python
import pandas as pd

def parse(file_path):
    # 1. Read the file, skipping the metadata header (first 3 rows)
    # 2. Skip the footer (last 2 rows)
    df = pd.read_csv(file_path, skiprows=3, skipfooter=2, engine='python')
    
    # 3. Clean column names to match Analyte names
    # Assuming 'Reading 1' and 'Reading 2' should be averaged into 'Tumor OD'
    df['Tumor OD'] = (df[' Reading 1'] + df[' Reading 2']) / 2
    
    # 4. Rename 'ID' to ensure it's exactly what the system expects
    df = df.rename(columns={'ID': 'ID'})
    
    # 5. Filter only the columns we want to import
    result = df[['ID', 'Tumor OD']]
    
    return result.to_dict(orient='records')
```

### The Output (Internal Data representation)

The script returns this structure to Precliniverse:

```json
[
  {"ID": "A-101", "Tumor OD": 0.455},
  {"ID": "A-102", "Tumor OD": 0.900}
]
```

## 4. Supported Libraries

For security, the environment is sandboxed. Only the following libraries and built-ins are available:

*   **Modules**: `pandas` (as `pd`), `numpy` (as `np`), `re`, `math`, `statistics`, `datetime`, `json`.
*   **Functions**: `print`, `len`, `str`, `int`, `float`, `list`, `dict`, `set`, `sum`, `min`, `max`, `round`, `any`, `all`, `sorted`, `map`, `filter`.

Forbidden operations (e.g., `os`, `sys`, file writing, network access) will cause the script to fail immediately.

## 5. Using a Pipeline in the Wizard

1.  **Open Import Wizard**: Navigate to your DataTable and click **Import Raw**.
2.  **Select Pipeline**: In Step 1, you will see a preset dropdown **"Use Import Pipeline"**.
    *   *Note: This dropdown only appears if pipelines exist for the current protocol.*
3.  **Select File**: Upload your raw file.
4.  **Run**: Click **Next**.
    *   The system executes the script.
    *   It verifies that an `'ID'` column exists in the output.
    *   It **skips Step 2 (Mapping)** completely.
5.  **Validation**: You are taken directly to Step 3 (Validation) to confirm recognized animals.
6.  **Import**: Finalize the import.

## 6. Debugging & Testing

The Pipeline Editor includes a **Test Bench**:

1.  Upload a sample file.
2.  Click **Run Test**.
3.  View the JSON output or error stack trace immediately.
4.  Iterate on your script until the output is perfect.

!!! tip "One-Click Import"
    Pipelines effectively turn complex imports into a "One-Click" operation for end-users. Once the script is written by an Admin/Developer, technicians simply select the preset and upload the file, eliminating mapping errors.
