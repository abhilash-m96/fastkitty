#!/bin/bash
set -e

function create_database() {
    local database=$1
    echo "Creating database '$database' if not exists..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        SELECT 'CREATE DATABASE $database'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$database')\gexec
        GRANT ALL PRIVILEGES ON DATABASE $database TO $POSTGRES_USER;
EOSQL
}

# Create databases needed for fastkitty multi-tenancy strategies
create_database "tenant_1"
create_database "tenant_2"
create_database "fastkitty_shared"
