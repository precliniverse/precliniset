# API Overview

Precliniverse provides a comprehensive RESTful API for automation and integration.

## Authentication
The API uses **Header-based Authentication**.

1.  **Service API Key**: For server-to-server communication (e.g., from Training Manager).
    *   Header: `X-API-KEY: <your-service-api-key>`
2.  **User Session**: Standard browser session for frontend interactions.

## Endpoints Structure

The API is organized around standard REST principles.
-   `GET`: Retrieve resources.
-   `POST`: Create new resources.
-   `PUT`: Update existing resources.
-   `DELETE`: Remove resources.

### Key Resources

*   `/api/v1/projects`: Project management.
*   `/api/v1/groups`: Experimental group operations.
*   `/api/v1/group_data`: Data entry and retrieval.
*   `/api/v1/samples`: Biobanking and sample tracking.

## Interactive Documentation (Swagger/Redoc)

When the application is running, you can access the full, interactive API specification at:

*   **ReDoc**: `http://localhost:8000/api/v1/redoc` (Recommended for reading)
*   **Swagger UI**: `http://localhost:8000/api/v1/docs` (Recommended for testing)

These interactive docs are automatically generated from the code and provide schemas, example payloads, and a "Try it out" feature.
