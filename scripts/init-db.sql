-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Create database schema
CREATE SCHEMA IF NOT EXISTS sowknow;

-- Users table
CREATE TABLE sowknow.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    is_superuser BOOLEAN DEFAULT FALSE,
    can_access_confidential BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create admin user
INSERT INTO sowknow.users (email, hashed_password, full_name, role, is_superuser, can_access_confidential)
VALUES (
    'admin@sowknow.local',
    -- bcrypt hash for 'Admin123!'
    '$2b$12$6Xo5q7v8w9y0z1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4',
    'System Administrator',
    'admin',
    TRUE,
    TRUE
);
