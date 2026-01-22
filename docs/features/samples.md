# Biobanking & Samples

Tracking physical samples is critical for translational research. This module provides a "lightweight LIMS" (Laboratory Information Management System).

[TOC]

## 1. The Life of a Sample
Precliniverse tracks the lineage of every biological specimen.

### Level 1: Primary Sample
Collected directly from the animal.
*   *Example*: A tumor excision at necropsy.
*   **Creation**: Usually done via **Batch Entry** (see below).
*   **Metadata**: Links to Animal ID, Collection Date, and Organ.

### Level 2: Derived Sample
Processed from a parent.
*   *Example*: The tumor (Primary) is cut into 3 pieces:
    1.  **Piece A** -> Flash Frozen (Derived).
    2.  **Piece B** -> Formalin Fixed (Derived).
    3.  **Piece C** -> DNA Extraction (Derived).
*   **Genealogy**: The system maintains a linked graph. Querying Piece C will show it came from Animal X via Tumor Y.
*   **Result**: 10 new samples are created, legally linked to the parents (Parent-Child relationship compliant with ISO 20387).

![Sample Explorer](../img/samples_list.png)
*Fig. Sample Explorer view showing samples and their storage locations.*

---

## 2. Storage Management
Where is it physically?

### Setup (Admin)
Define your infrastructure first.
1.  **Rooms**: *Room 303*.
2.  **Units**: *Freezer_01* (-80°C).
3.  **Shelves/Racks**: *Rack A*.
4.  **Boxes**: *Box_001* (10x10 Grid).

### Check-In Workflow
1.  Go to **Samples List**.
2.  Select samples to store.
3.  Click **Check In**.
4.  Scanning/Selecting Workflow:
    *   Select **Target Box**.
    *   Click the cell (e.g., A1, A2) to place the sample.
    *   *Visual Aid*: Occupied cells are greyed out.

---

## 3. High-Throughput Workflows

### Batch Entry (Necropsy Mode)
Logging 50 animals manually is slow. Use Batch Entry.

**Scenario**: End of study necropsy for 20 mice. Collecting Blood, Liver, and Spleen for all.

1.  **Navigate**: **Samples** > **Batch Entry**.
2.  **Select Group**: Choose the experimental group.
3.  **Select Animals**: "Select All" (or specific ones).
4.  **Define Protocol**:
    *   Add **Blood** (Primary) -> Condition: *EDTA*.
    *   Add **Liver** (Primary) -> Condition: *Flash Frozen*.
    *   Add **Spleen** (Primary) -> Condition: *Formalin*.
5.  **Generate**: The system creates 60 sample records instantly (20 x 3).
    *   IDs are auto-generated: `M01-Blood-1`, `M01-Liver-1`, etc.

### Batch Derivation
Processing a batch of plasma?
1.  Filter list for `Whole Blood` samples collected `Today`.
2.  Select All (e.g., 20 tubes).
3.  Click **Create Derived**.
4.  New Type: `Plasma`.
5.  **Submit**: 20 Plasma records created, linked 1-to-1 with their blood parents.

!!! tip "Labels"
    The system can generate QR codes for labels (future feature integration). For now, use the exported Excel list to feed your label printer software.
