#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

echo "Waiting for database..."

# Wait for the database to be ready (assuming DB_HOST and DB_PORT are set)
# Defaults to 'db' and '3306' if not set
HOST=${DB_HOST:-db}
PORT=${DB_PORT:-3306}

# Only wait for DB if not using SQLite
if [ "$DB_TYPE" != "sqlite" ]; then
    echo "Waiting for database at $HOST:$PORT..."
    # Loop until mysqladmin can successfully connect
    while ! mysqladmin ping -h"$HOST" -u"$DB_USER" -p"$DB_PASSWORD" --silent --skip-ssl; do
        sleep 1
    done
    echo "Database started"
else
    echo "Using SQLite, skipping network DB check."
    # Ensure instance directory exists for SQLite database
    echo "Ensuring instance directory exists..."
    mkdir -p /app/instance
fi



# Run migrations if enabled (Default: true)
if [ "$RUN_MIGRATIONS" = "true" ]; then
    if [ -d "migrations" ]; then
        echo "------------------------------------------------"
        echo "🔄 Checking for database migrations..."
        flask db upgrade
        if [ $? -eq 0 ]; then
            echo "✅ Database is up to date."
        else
            echo "❌ Migration failed! Check logs."
            # Optional: exit 1 # Uncomment to stop container if migration fails
        fi
        
        # Run setup commands to ensure system integrity
        echo "⚙️  Ensuring system roles and resources..."
        flask setup init-admin
        flask setup static-resources
        echo "------------------------------------------------"
    else
        echo "⚠️  'migrations' directory not found. Skipping DB upgrade."
    fi
fi

echo "Starting application..."
exec "$@"
