-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Persons table
CREATE TABLE IF NOT EXISTS persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID NOT NULL,
    name VARCHAR(100) NOT NULL,
    relationship VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persons_owner ON persons(owner_id);

-- Face embeddings table
CREATE TABLE IF NOT EXISTS face_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID REFERENCES persons(id) ON DELETE SET NULL,
    media_id UUID NOT NULL,
    embedding vector(128) NOT NULL,
    bbox_x INTEGER,
    bbox_y INTEGER,
    bbox_width INTEGER,
    bbox_height INTEGER,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vector similarity index (IVFFlat for cosine similarity)
CREATE INDEX IF NOT EXISTS idx_face_embedding_vector 
    ON face_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_face_media ON face_embeddings(media_id);
CREATE INDEX IF NOT EXISTS idx_face_person ON face_embeddings(person_id);

-- Photo-Person mapping (confirmed assignments)
CREATE TABLE IF NOT EXISTS photo_persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    media_id UUID NOT NULL,
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    face_embedding_id UUID REFERENCES face_embeddings(id) ON DELETE SET NULL,
    confirmed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(media_id, person_id)
);

CREATE INDEX IF NOT EXISTS idx_photo_persons_media ON photo_persons(media_id);
CREATE INDEX IF NOT EXISTS idx_photo_persons_person ON photo_persons(person_id);

-- Analysis results (photo metadata)
CREATE TABLE IF NOT EXISTS analysis_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    media_id UUID UNIQUE NOT NULL,
    owner_id UUID NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    face_count INTEGER DEFAULT 0,
    taken_at TIMESTAMPTZ,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    camera_make VARCHAR(100),
    camera_model VARCHAR(100),
    error_message TEXT,
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_media ON analysis_results(media_id);
CREATE INDEX IF NOT EXISTS idx_analysis_owner ON analysis_results(owner_id);
CREATE INDEX IF NOT EXISTS idx_analysis_status ON analysis_results(status);
