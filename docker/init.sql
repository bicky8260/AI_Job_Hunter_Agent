-- PostgreSQL initialization script
-- Runs automatically when the container is first created
-- Safe to run multiple times (uses IF NOT EXISTS)

-- The database 'jobhunter' is created by the POSTGRES_DB env var.
-- This script can add extensions or default data.

-- Enable UUID extension (useful for ID generation)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set timezone
SET timezone = 'UTC';
