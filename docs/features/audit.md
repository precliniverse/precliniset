# Audit Trail & GLP Compliance

Precliniset is designed to meet the rigorous standards of **Good Laboratory Practice (GLP)**. 

## The Audit Trail System

Every modification to critical data in Precliniset is automatically recorded. Unlike standard logs, our Audit Trail captures the **state change**.

### What is tracked?
The following entities have full version tracking:
*   Projects
*   Experimental Groups
*   DataTables
*   Samples
*   Ethical Approvals
*   Users & Teams

### Visualizing Changes
Superadmins can access the **Audit Trail** dashboard to see:
1.  **Who** made the change (User, IP Address).
2.  **When** it was made (UTC Timestamp).
3.  **Exactly what** changed:
    *   **Old Value**: The data before the edit.
    *   **New Value**: The data after the edit.
    *   **Diff View**: A visual comparison highlighting the exact fields modified (e.g., changing a Tumor Volume from `100` to `1000`).

!!! tip "GLP Requirement"
    The audit trail is immutable and cannot be deleted or modified by any user, ensuring a permanent record of the study's integrity.

## Granularity
The system is intelligent enough to distinguish between huge updates and small tweaks.
*   **Deep Diff**: For JSON fields (like experimental data rows), we compute the precise difference. We don't just store "Data Changed", we store "Row 3, Col 4 changed from X to Y".
*   **Suppression**: Automated system syncs (that don't change scientific data) are intelligently filtered effectively to prevent log noise, while still maintaining compliance.

## Restoration
While the Audit Trail is primarily read-only for compliance, it also serves as a safety net. Administrators can review previous states to manually recover data in case of accidental deletions or erroneous overwrites.
